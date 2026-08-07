"""AgentCore Gateway向けSigV4 MCP接続と公開Tool境界。"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from agents.mcp import MCPServerStreamableHttp
from mcp.types import CallToolResult, TextContent
from mcp.types import Tool as MCPTool
from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client

from agent_app.config import AppConfig


MCP_SERVER_NAME = "AgentCoreWeatherGateway"
MCP_AWS_SERVICE = "bedrock-agentcore"
MCP_TRANSPORT_TIMEOUT_SECONDS = 30
MCP_CLIENT_SESSION_TIMEOUT_SECONDS = 10
MCP_CLEANUP_TIMEOUT_SECONDS = 5
_TOOL_NAME_DELIMITER = "___"
_WEATHER_TOOL_NAMES = ("get_weather", "get_time")
TOOL_UNAVAILABLE_MESSAGE = "現在、天気・時刻情報を取得できません。"
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
        transport_factory: TransportFactory = aws_iam_streamablehttp_client,
    ) -> None:
        self._endpoint = endpoint
        self._region = region
        self._transport_factory = transport_factory
        self.required_tool_names = tuple(
            f"{target_name}{_TOOL_NAME_DELIMITER}{tool_name}"
            for tool_name in _WEATHER_TOOL_NAMES
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
            name=MCP_SERVER_NAME,
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
        """allowlist適用後に必須2 Toolが一つずつ揃うことを確認する。"""

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
        """正常なモック結果だけをcanonical JSONとしてWeather Agentへ渡す。"""

        if tool_name not in self.required_tool_names:
            return _unavailable_tool_result()
        try:
            # SDK内のClientSession timeoutだけへ依存せず、このadapter自身も有限時間で
            # base callを打ち切り、無応答のGatewayを固定の利用不能結果へ閉じ込める。
            async with asyncio.timeout(MCP_CLIENT_SESSION_TIMEOUT_SECONDS):
                result = await super().call_tool(tool_name, arguments, meta=meta)
        except asyncio.CancelledError:
            raise
        except Exception:
            # 接続済みsessionでのtransport／Tool例外はturn全体を壊さず、例外本文や
            # 入力値を含まない固定結果へ変換する。connect／cleanup失敗とは区別する。
            return _unavailable_tool_result()

        payload = _normalize_call_tool_result(result)
        short_tool_name = tool_name.rsplit(_TOOL_NAME_DELIMITER, maxsplit=1)[-1]
        if payload is None or not _is_valid_mock_result(short_tool_name, payload):
            # structuredとtextの競合や形式不正を推測で採用せずfail-closedにする。
            return _unavailable_tool_result()
        return _canonical_tool_result(payload)


def create_gateway_mcp_server(
    config: AppConfig,
    *,
    transport_factory: TransportFactory = aws_iam_streamablehttp_client,
) -> AgentCoreGatewayMCPServer:
    """検証済みRuntime設定からリクエスト専用MCP serverを生成する。"""

    return AgentCoreGatewayMCPServer(
        endpoint=config.gateway_url,
        region=config.aws_region,
        target_name=config.gateway_target_name,
        transport_factory=transport_factory,
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
