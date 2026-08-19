"""AgentCore Gateway向けSigV4 MCP接続と公開Tool境界。"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any
from urllib.parse import urlsplit

from agents.mcp import MCPServerStreamableHttp
from mcp.types import CallToolResult, TextContent
from mcp.types import Tool as MCPTool
from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client

from agent_app.config import AppConfig


# AgentCore標準loggerのchildを使い、Runtimeのlogging設定後も安全な障害分類を残す。
logger = logging.getLogger("bedrock_agentcore.app.agent_app.gateway_tools")


MCP_SERVER_NAME = "AgentCoreWeatherGateway"
KNOWLEDGE_MCP_SERVER_NAME = "AgentCoreKnowledgeGateway"
MCP_AWS_SERVICE = "bedrock-agentcore"
MCP_TRANSPORT_TIMEOUT_SECONDS = 30
MCP_CLIENT_SESSION_TIMEOUT_SECONDS = 10
MCP_CLEANUP_TIMEOUT_SECONDS = 5
_TOOL_NAME_DELIMITER = "___"
_WEATHER_TOOL_NAMES = ("get_weather", "get_time")
TOOL_UNAVAILABLE_MESSAGE = "現在、天気・時刻情報を取得できません。"
KNOWLEDGE_TOOL_UNAVAILABLE_MESSAGE = "現在、社内ナレッジを取得できません。"
_KNOWLEDGE_TOOL_NAME = "Retrieve"
_KNOWLEDGE_DOCUMENT_PATHS = frozenset(
    {
        "estimation/estimation_guideline.md",
        "projects/sample_project_alpha.md",
        "standards/aws_architecture_standard.md",
        "standards/monitoring_standard.md",
        "standards/security_standard.md",
    }
)
_KNOWLEDGE_METADATA_FIELDS = frozenset(
    {
        "document_type",
        "version",
        "system_type",
        "environment",
        "service",
        "project_name",
    }
)
_FILTER_OPERATORS = {
    "document_type": "equals",
    "environment": "listContains",
    "service": "listContains",
}
_FILTER_COMPOSITES = frozenset({"andAll", "orAll"})
_MAX_FILTER_COMPOSITE_DEPTH = 2
_MAX_FILTER_CONDITIONS = 8
_MISSING_CONTENT = object()

TransportFactory = Callable[..., AbstractAsyncContextManager[Any]]


class GatewayToolsUnavailableError(RuntimeError):
    """Gatewayの必須Tool集合を安全に利用できない状態。"""

    def __init__(self) -> None:
        super().__init__("Gateway Toolを利用できません。")


class AgentCoreGatewayMCPServer(MCPServerStreamableHttp):
    """Agents SDKのsession管理を保ったままtransportだけをSigV4化する。"""

    def __init__(
        self,
        *,
        endpoint: str,
        region: str,
        target_name: str,
        tool_contract: str = "weather",
        transport_factory: TransportFactory = aws_iam_streamablehttp_client,
    ) -> None:
        self._endpoint = endpoint
        self._region = region
        self._transport_factory = transport_factory
        if tool_contract == "weather":
            tool_names = _WEATHER_TOOL_NAMES
            server_name = MCP_SERVER_NAME
        elif tool_contract == "knowledge":
            tool_names = (_KNOWLEDGE_TOOL_NAME,)
            server_name = KNOWLEDGE_MCP_SERVER_NAME
        else:
            raise ValueError("未対応のGateway Tool契約です。")
        self.tool_contract = tool_contract
        self.required_tool_names = tuple(
            f"{target_name}{_TOOL_NAME_DELIMITER}{tool_name}"
            for tool_name in tool_names
        )

        # proxyはDEBUG時にendpointを記録するため、root loggerを変更せずpackage単位で
        # INFO以上に固定し、内部URLが運用ログへ流れる経路を閉じる。
        logging.getLogger("mcp_proxy_for_aws").setLevel(logging.INFO)
        super().__init__(
            params={
                "url": endpoint,
                "timeout": MCP_TRANSPORT_TIMEOUT_SECONDS,
                "terminate_on_close": True,
            },
            # 接続はリクエスト単位で破棄するため、Tool一覧cacheも同じ境界内だけで使う。
            cache_tools_list=True,
            name=server_name,
            client_session_timeout_seconds=MCP_CLIENT_SESSION_TIMEOUT_SECONDS,
            tool_filter={"allowed_tool_names": list(self.required_tool_names)},
            use_structured_content=False,
            # 同一turn内で自動再試行せず、次のRuntime呼び出しを再試行境界にする。
            max_retry_attempts=0,
            # adapterで想定内のTool失敗だけを固定結果化し、未知のSDK障害はRunnerへ伝える。
            failure_error_function=None,
        )

    def create_streams(self) -> AbstractAsyncContextManager[Any]:
        """標準AWS認証情報チェーンで署名するStreamable HTTP transportを返す。"""

        # 親classのconnect／ClientSession／cleanupを維持するため、session実装ではなく
        # transport生成だけを差し替える。profileや静的credentialは受け取らない。
        return self._transport_factory(
            endpoint=self._endpoint,
            aws_service=MCP_AWS_SERVICE,
            aws_region=self._region,
            timeout=MCP_TRANSPORT_TIMEOUT_SECONDS,
            terminate_on_close=True,
        )

    async def list_tools(
        self,
        run_context: Any | None = None,
        agent: Any | None = None,
    ) -> list[MCPTool]:
        """allowlist適用後に契約上の必須Toolが一つずつ揃うことを確認する。"""

        tools = await super().list_tools(run_context=run_context, agent=agent)
        names = [tool.name for tool in tools]
        if len(names) != len(self.required_tool_names) or set(names) != set(
            self.required_tool_names
        ):
            raise GatewayToolsUnavailableError()
        return tools

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None,
        meta: dict[str, Any] | None = None,
    ) -> CallToolResult:
        """Gateway種別ごとの正常結果だけをcanonical JSONとしてAgentへ渡す。"""

        if tool_name not in self.required_tool_names:
            logger.warning(
                "Gateway Toolを利用不能として継続します: kind=%s stage=tool_name",
                self.tool_contract,
            )
            return self._unavailable_result()
        gateway_arguments = arguments
        if self.tool_contract == "knowledge":
            gateway_arguments = _normalize_retrieve_arguments(arguments)
            if gateway_arguments is None:
                # Gatewayが返すschemaだけに依存せず、公開していない管理者parameterや
                # 複雑すぎるfilterをbackendへ送る前に拒否する。
                logger.warning(
                    "Gateway Toolを利用不能として継続します: "
                    "kind=knowledge stage=arguments"
                )
                return self._unavailable_result()
        try:
            # SDK内のClientSession timeoutだけへ依存せず、このadapter自身も有限時間で
            # base callを打ち切り、無応答のGatewayを固定の利用不能結果へ閉じ込める。
            async with asyncio.timeout(MCP_CLIENT_SESSION_TIMEOUT_SECONDS):
                result = await super().call_tool(
                    tool_name, gateway_arguments, meta=meta
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            # 接続済みsessionでのtransport／Tool例外はturn全体を壊さず、例外本文や
            # 入力値を含まない固定結果へ変換する。connect／cleanup失敗とは区別する。
            logger.warning(
                "Gateway Toolを利用不能として継続します: kind=%s stage=transport",
                self.tool_contract,
            )
            return self._unavailable_result()

        if self.tool_contract == "knowledge":
            payload = _normalize_knowledge_result(result)
            if payload is None:
                logger.warning(
                    "Gateway Toolを利用不能として継続します: "
                    "kind=knowledge stage=result"
                )
                return self._unavailable_result()
            return _canonical_tool_result(payload)

        payload = _normalize_call_tool_result(result)
        short_tool_name = tool_name.rsplit(_TOOL_NAME_DELIMITER, maxsplit=1)[-1]
        if payload is None or not _is_valid_mock_result(short_tool_name, payload):
            # structuredとtextの競合や形式不正を推測で採用せずfail-closedにする。
            logger.warning(
                "Gateway Toolを利用不能として継続します: kind=weather stage=result"
            )
            return self._unavailable_result()
        return _canonical_tool_result(payload)

    def _unavailable_result(self) -> CallToolResult:
        """Gateway種別に対応する内部情報なしの固定失敗結果を返す。"""

        if self.tool_contract == "knowledge":
            return _canonical_tool_result_unchecked(
                {"error": KNOWLEDGE_TOOL_UNAVAILABLE_MESSAGE}
            )
        return _unavailable_tool_result()


def create_gateway_mcp_server(
    config: AppConfig,
    *,
    transport_factory: TransportFactory = aws_iam_streamablehttp_client,
) -> AgentCoreGatewayMCPServer:
    """検証済みRuntime設定からリクエスト専用MCP serverを生成する。"""

    return AgentCoreGatewayMCPServer(
        endpoint=config.weather_gateway.url,
        region=config.weather_gateway.region,
        target_name=config.weather_gateway.target_name,
        transport_factory=transport_factory,
    )


def create_knowledge_gateway_mcp_server(
    config: AppConfig,
    *,
    transport_factory: TransportFactory = aws_iam_streamablehttp_client,
) -> AgentCoreGatewayMCPServer:
    """検証済みKnowledge設定からリクエスト専用MCP serverを生成する。"""

    return AgentCoreGatewayMCPServer(
        endpoint=config.knowledge_gateway.url,
        region=config.knowledge_gateway.region,
        target_name=config.knowledge_gateway.target_name,
        tool_contract="knowledge",
        transport_factory=transport_factory,
    )


def _normalize_retrieve_arguments(
    arguments: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """queryと限定filterを検証し、任意設定の空表現を省略形へ正規化する。"""

    if not isinstance(arguments, Mapping) or not set(arguments).issubset(
        {"retrievalQuery", "retrievalConfiguration"}
    ):
        return None
    query = arguments.get("retrievalQuery")
    if not isinstance(query, Mapping) or set(query) != {"text"}:
        return None
    text = query.get("text")
    if not isinstance(text, str) or not text.strip():
        return None

    normalized: dict[str, Any] = {"retrievalQuery": {"text": text}}

    retrieval_configuration = arguments.get("retrievalConfiguration")
    if retrieval_configuration is None:
        return normalized
    if not isinstance(retrieval_configuration, Mapping):
        return None
    if not retrieval_configuration:
        return normalized
    if set(retrieval_configuration) != {"managedSearchConfiguration"}:
        return None
    managed_configuration = retrieval_configuration.get("managedSearchConfiguration")
    if not isinstance(managed_configuration, Mapping):
        return None
    if not managed_configuration:
        return normalized
    if set(managed_configuration) != {"filter"}:
        return None
    filter_value = managed_configuration.get("filter")
    valid, condition_count = _validate_filter(filter_value, composite_depth=0)
    if not valid or not 1 <= condition_count <= _MAX_FILTER_CONDITIONS:
        return None
    normalized["retrievalConfiguration"] = {
        "managedSearchConfiguration": {"filter": filter_value}
    }
    return normalized


def _validate_filter(value: Any, *, composite_depth: int) -> tuple[bool, int]:
    """許可したleafと最大2段のAND／ORだけを再帰検証する。"""

    if not isinstance(value, Mapping) or len(value) != 1:
        return False, 0
    operator, operand = next(iter(value.items()))
    if operator in _FILTER_COMPOSITES:
        if composite_depth >= _MAX_FILTER_COMPOSITE_DEPTH:
            return False, 0
        if (
            not isinstance(operand, list)
            or not operand
            or len(operand) > _MAX_FILTER_CONDITIONS
        ):
            return False, 0
        total = 0
        for child in operand:
            valid, count = _validate_filter(
                child, composite_depth=composite_depth + 1
            )
            if not valid:
                return False, 0
            total += count
            if total > _MAX_FILTER_CONDITIONS:
                return False, 0
        return True, total

    if operator not in {"equals", "listContains"} or not isinstance(
        operand, Mapping
    ):
        return False, 0
    if set(operand) != {"key", "value"}:
        return False, 0
    key = operand.get("key")
    filter_value = operand.get("value")
    return (
        isinstance(key, str)
        and _FILTER_OPERATORS.get(key) == operator
        and isinstance(filter_value, str)
        and bool(filter_value.strip()),
        1,
    )


def _normalize_knowledge_result(result: CallToolResult) -> dict[str, Any] | None:
    """Retrieve応答を相対sourceと許可metadataだけの結果へ変換する。"""

    if (
        result.isError
        or result.structuredContent is not None
        or len(result.content) != 1
        or not isinstance(result.content[0], TextContent)
    ):
        return None
    try:
        decoded = json.loads(result.content[0].text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(decoded, Mapping) or set(decoded) != {"retrievalResults"}:
        return None
    raw_results = decoded.get("retrievalResults")
    if not isinstance(raw_results, list):
        return None

    normalized_results: list[dict[str, Any]] = []
    for raw_result in raw_results:
        normalized = _normalize_retrieval_item(raw_result)
        if normalized is None:
            return None
        normalized_results.append(normalized)
    return {"retrievalResults": normalized_results}


def _normalize_retrieval_item(value: Any) -> dict[str, Any] | None:
    """Markdown由来のTEXT／S3結果だけをモデル可視のshapeへ変換する。"""

    if not isinstance(value, Mapping):
        return None
    content = value.get("content")
    location = value.get("location")
    if (
        not isinstance(content, Mapping)
        or content.get("type") != "TEXT"
        or not isinstance(content.get("text"), str)
        or not content["text"].strip()
        or not isinstance(location, Mapping)
        or location.get("type") != "S3"
        or not isinstance(location.get("s3Location"), Mapping)
    ):
        return None
    source = _relative_document_path(location["s3Location"].get("uri"))
    if source is None:
        return None

    normalized: dict[str, Any] = {
        "text": content["text"],
        "source": source,
    }
    score = value.get("score")
    if score is not None:
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            return None
        normalized["score"] = score
    metadata = value.get("metadata")
    if metadata is not None:
        if not isinstance(metadata, Mapping):
            return None
        normalized["metadata"] = {
            key: metadata[key]
            for key in _KNOWLEDGE_METADATA_FIELDS
            if key in metadata and _is_safe_metadata_value(metadata[key])
        }
    return normalized


def _relative_document_path(value: Any) -> str | None:
    """S3 locationからbucket名を捨て、許可済み文書pathだけを返す。"""

    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        return None
    document_path = parsed.path.removeprefix("/")
    # Managed Knowledge Baseはlocation.type=S3でもvirtual-hosted HTTPS URIを返す。
    # 任意HTTPSを許可せず、実応答のS3 host suffixと従来のs3 URIだけに限定する。
    is_s3_uri = parsed.scheme == "s3" and bool(parsed.netloc)
    is_s3_https_uri = (
        parsed.scheme == "https"
        and parsed.hostname is not None
        and parsed.hostname.endswith(".s3.amazonaws.com")
        and parsed.hostname != "s3.amazonaws.com"
        and port is None
    )
    if (
        not (is_s3_uri or is_s3_https_uri)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or document_path not in _KNOWLEDGE_DOCUMENT_PATHS
    ):
        return None
    return document_path


def _is_safe_metadata_value(value: Any) -> bool:
    """結果metadataへJSON互換の仕様型だけを残す。"""

    if isinstance(value, str):
        return bool(value.strip())
    return (
        isinstance(value, list)
        and all(isinstance(item, str) and bool(item.strip()) for item in value)
    )


def _normalize_call_tool_result(result: CallToolResult) -> dict[str, Any] | None:
    """MCPの二つの結果表現を曖昧さなく一つのMappingへ正規化する。"""

    if result.isError:
        return None

    structured: dict[str, Any] | None = None
    if result.structuredContent is not None:
        if not isinstance(result.structuredContent, Mapping):
            return None
        structured = dict(result.structuredContent)

    text_payload = _mapping_from_content(result.content)
    if text_payload is _MISSING_CONTENT:
        return structured
    if text_payload is None:
        return None
    if structured is not None and structured != text_payload:
        # 同じ結果を表す二つの表現が競合する場合は、片方を恣意的に採用しない。
        return None
    return structured if structured is not None else text_payload


def _mapping_from_content(content: list[Any]) -> dict[str, Any] | None | object:
    """単一TextContentのJSON objectを返し、空contentだけを別状態で表す。"""

    if not content:
        return _MISSING_CONTENT
    if len(content) != 1 or not isinstance(content[0], TextContent):
        return None
    try:
        decoded = json.loads(content[0].text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(decoded, Mapping):
        return None
    return dict(decoded)


def _is_valid_mock_result(tool_name: str, payload: Mapping[str, Any]) -> bool:
    """Lambdaの失敗結果とTool別の正常モック契約を区別する。"""

    if "error" in payload or payload.get("data_type") != "mock":
        return False
    required_fields = {
        "get_weather": ("location", "weather"),
        "get_time": ("timezone", "local_time"),
    }.get(tool_name)
    return required_fields is not None and all(
        isinstance(payload.get(field), str) and bool(payload[field].strip())
        for field in required_fields
    )


def _canonical_tool_result(payload: Mapping[str, Any]) -> CallToolResult:
    """use_structured_content=Falseでもモデルが読める単一JSON textへ揃える。"""

    normalized = dict(payload)
    try:
        text = json.dumps(
            normalized,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError):
        return _unavailable_tool_result()
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structuredContent=normalized,
        isError=False,
    )


def _unavailable_tool_result() -> CallToolResult:
    """内部情報を含まないモデル可視の固定利用不能結果を返す。"""

    return _canonical_tool_result_unchecked({"error": TOOL_UNAVAILABLE_MESSAGE})


def _canonical_tool_result_unchecked(payload: dict[str, Any]) -> CallToolResult:
    """静的なJSON互換payloadだけをCallToolResultへ格納する。"""

    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            )
        ],
        structuredContent=payload,
        isError=False,
    )
