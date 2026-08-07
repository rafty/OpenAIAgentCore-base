"""AgentCore Gateway向けSigV4 MCPアダプターの失敗閉包を検証する。"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import pytest
from agents.mcp import MCPServerStreamableHttp
from mcp.types import CallToolResult, ImageContent, ListToolsResult, TextContent, Tool

import agent_app.gateway_tools as gateway_tools_module
from agent_app.config import AppConfig
from agent_app.gateway_tools import (
    MCP_AWS_SERVICE,
    MCP_CLIENT_SESSION_TIMEOUT_SECONDS,
    MCP_SERVER_NAME,
    MCP_TRANSPORT_TIMEOUT_SECONDS,
    TOOL_UNAVAILABLE_MESSAGE,
    AgentCoreGatewayMCPServer,
    GatewayToolsUnavailableError,
    create_gateway_mcp_server,
)


ENDPOINT = (
    "https://gateway-id.gateway.bedrock-agentcore.us-east-2.amazonaws.com/mcp"
)
WEATHER_TOOL = "WeatherTimeMock___get_weather"
TIME_TOOL = "WeatherTimeMock___get_time"
EXPECTED_TOOLS = (WEATHER_TOOL, TIME_TOOL)


def _server(*, transport_factory: Any | None = None) -> AgentCoreGatewayMCPServer:
    return AgentCoreGatewayMCPServer(
        endpoint=ENDPOINT,
        region="us-east-2",
        target_name="WeatherTimeMock",
        transport_factory=transport_factory or (lambda **_: object()),
    )


def _result(
    *,
    content: list[Any] | None = None,
    structured: Any = None,
    is_error: bool = False,
) -> CallToolResult:
    return CallToolResult(
        content=content or [],
        structuredContent=structured,
        isError=is_error,
    )


def _decoded(result: CallToolResult) -> dict[str, Any]:
    assert result.isError is False
    assert result.structuredContent is not None
    assert len(result.content) == 1
    assert isinstance(result.content[0], TextContent)
    assert json.loads(result.content[0].text) == result.structuredContent
    return dict(result.structuredContent)


def _run(coroutine: Any) -> Any:
    """追加のpytest pluginへ依存せずasync境界を決定的に実行する。"""

    return asyncio.run(coroutine)


def test_transport_and_sdk_options_are_fixed_without_explicit_credentials() -> None:
    calls: list[dict[str, Any]] = []

    def transport_factory(**kwargs: Any) -> object:
        calls.append(kwargs)
        return object()

    server = _server(transport_factory=transport_factory)

    assert server.create_streams() is not None
    assert calls == [
        {
            "endpoint": ENDPOINT,
            "aws_service": MCP_AWS_SERVICE,
            "aws_region": "us-east-2",
            "timeout": MCP_TRANSPORT_TIMEOUT_SECONDS,
            "terminate_on_close": True,
        }
    ]
    # 標準認証情報チェーン以外の注入経路とBearer headerをtransportへ渡さない。
    assert not {
        "aws_profile",
        "credentials",
        "headers",
        "authorization",
        "token",
    }.intersection(calls[0])
    assert server.name == MCP_SERVER_NAME
    assert server.cache_tools_list is True
    assert server.client_session_timeout_seconds == MCP_CLIENT_SESSION_TIMEOUT_SECONDS
    assert server.max_retry_attempts == 0
    assert server.params == {
        "url": ENDPOINT,
        "timeout": MCP_TRANSPORT_TIMEOUT_SECONDS,
        "terminate_on_close": True,
    }
    assert server.tool_filter == {"allowed_tool_names": list(EXPECTED_TOOLS)}
    assert server.use_structured_content is False


def test_factory_wires_config_to_target_and_sigv4_transport_without_credentials() -> None:
    endpoint = (
        "https://factory-id.gateway.bedrock-agentcore.us-east-2.amazonaws.com/mcp"
    )
    config = AppConfig(
        aws_region="us-east-2",
        model_id="openai.gpt-5.5",
        memory_id="memory-id",
        tracing_disabled="1",
        gateway_url=endpoint,
        gateway_target_name="FactoryTarget",
    )
    calls: list[dict[str, Any]] = []
    stream_context = object()

    def transport_factory(**kwargs: Any) -> object:
        calls.append(kwargs)
        return stream_context

    server = create_gateway_mcp_server(
        config,
        transport_factory=transport_factory,
    )

    assert server.create_streams() is stream_context
    assert server.params["url"] == endpoint
    assert server.required_tool_names == (
        "FactoryTarget___get_weather",
        "FactoryTarget___get_time",
    )
    assert calls == [
        {
            "endpoint": endpoint,
            "aws_service": MCP_AWS_SERVICE,
            "aws_region": config.aws_region,
            "timeout": MCP_TRANSPORT_TIMEOUT_SECONDS,
            "terminate_on_close": True,
        }
    ]
    # factory経由でも標準認証情報チェーンだけを使い、静的credentialやheaderを渡さない。
    assert not {
        "aws_profile",
        "credentials",
        "headers",
        "authorization",
        "token",
    }.intersection(calls[0])


def test_list_tools_validates_allowlist_and_uses_request_local_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def list_page(*_: Any, **__: Any) -> ListToolsResult:
        nonlocal calls
        calls += 1
        return ListToolsResult(
            tools=[
                Tool(name=WEATHER_TOOL, description="weather", inputSchema={}),
                Tool(name=TIME_TOOL, description="time", inputSchema={}),
                Tool(
                    name="WeatherTimeMock___unknown",
                    description="must be filtered",
                    inputSchema={},
                ),
            ]
        )

    monkeypatch.setattr(MCPServerStreamableHttp, "_list_tools_page", list_page)
    server = _server()
    server.session = object()  # type: ignore[assignment]

    assert [tool.name for tool in _run(server.list_tools())] == list(EXPECTED_TOOLS)
    assert [tool.name for tool in _run(server.list_tools())] == list(EXPECTED_TOOLS)
    assert calls == 1


@pytest.mark.parametrize(
    "names",
    [
        [WEATHER_TOOL],
        [WEATHER_TOOL, WEATHER_TOOL],
        [WEATHER_TOOL, "WeatherTimeMock___unknown"],
    ],
)
def test_list_tools_rejects_missing_duplicate_or_extra_tools(
    monkeypatch: pytest.MonkeyPatch,
    names: list[str],
) -> None:
    async def list_page(*_: Any, **__: Any) -> ListToolsResult:
        return ListToolsResult(
            tools=[Tool(name=name, description="tool", inputSchema={}) for name in names]
        )

    monkeypatch.setattr(MCPServerStreamableHttp, "_list_tools_page", list_page)
    server = _server()
    server.session = object()  # type: ignore[assignment]

    with pytest.raises(GatewayToolsUnavailableError) as error:
        _run(server.list_tools())
    assert str(error.value) == "Gateway Toolを利用できません。"


@pytest.mark.parametrize("representation", ["structured", "text", "both"])
def test_call_tool_accepts_unambiguous_mock_result_forms(
    monkeypatch: pytest.MonkeyPatch,
    representation: str,
) -> None:
    payload = {
        "location": "Tokyo",
        "weather": "Sunny, 25°C",
        "data_type": "mock",
    }
    content = (
        [TextContent(type="text", text=json.dumps(payload))]
        if representation in {"text", "both"}
        else []
    )
    structured = payload if representation in {"structured", "both"} else None

    async def call_tool(*_: Any, **__: Any) -> CallToolResult:
        return _result(content=content, structured=structured)

    monkeypatch.setattr(MCPServerStreamableHttp, "call_tool", call_tool)
    result = _run(_server().call_tool(WEATHER_TOOL, {"location": "Tokyo"}))

    assert _decoded(result) == payload
    assert result.content[0].text == json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )


def test_call_tool_accepts_time_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "timezone": "Asia/Tokyo",
        "local_time": "2025-01-15 12:00:00",
        "data_type": "mock",
    }

    async def call_tool(*_: Any, **__: Any) -> CallToolResult:
        return _result(structured=payload)

    monkeypatch.setattr(MCPServerStreamableHttp, "call_tool", call_tool)
    assert _decoded(_run(_server().call_tool(TIME_TOOL, {}))) == payload


INVALID_RESULTS = [
    pytest.param(
        _result(
            content=[TextContent(type="text", text='{"data_type":"mock"}')],
            structured={
                "location": "Tokyo",
                "weather": "Sunny, 25°C",
                "data_type": "mock",
            },
        ),
        id="structured-text-mismatch",
    ),
    pytest.param(
        _result(
            content=[
                TextContent(type="text", text="{}"),
                TextContent(type="text", text="{}"),
            ]
        ),
        id="multiple-content",
    ),
    pytest.param(
        _result(content=[ImageContent(type="image", data="AA==", mimeType="image/png")]),
        id="non-text-content",
    ),
    pytest.param(
        _result(content=[TextContent(type="text", text="not-json")]),
        id="invalid-json",
    ),
    pytest.param(
        _result(
            structured={
                "location": "Tokyo",
                "weather": "Sunny, 25°C",
                "data_type": "mock",
            },
            is_error=True,
        ),
        id="mcp-is-error",
    ),
    pytest.param(_result(structured={"error": "internal"}), id="lambda-error"),
    pytest.param(
        _result(
            structured={
                "location": "Tokyo",
                "weather": "Sunny, 25°C",
                "data_type": "real",
            }
        ),
        id="non-mock",
    ),
    pytest.param(
        _result(structured={"location": "Tokyo", "data_type": "mock"}),
        id="missing-normal-field",
    ),
    pytest.param(
        _result(
            structured={"location": "Tokyo", "weather": 25, "data_type": "mock"}
        ),
        id="invalid-normal-field",
    ),
]


@pytest.mark.parametrize("invalid_result", INVALID_RESULTS)
def test_call_tool_fails_closed_for_ambiguous_or_invalid_results(
    monkeypatch: pytest.MonkeyPatch,
    invalid_result: CallToolResult,
) -> None:
    async def call_tool(*_: Any, **__: Any) -> CallToolResult:
        return invalid_result

    monkeypatch.setattr(MCPServerStreamableHttp, "call_tool", call_tool)
    assert _decoded(_run(_server().call_tool(WEATHER_TOOL, {}))) == {
        "error": TOOL_UNAVAILABLE_MESSAGE
    }


def test_unknown_tool_does_not_reach_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    async def call_tool(*_: Any, **__: Any) -> CallToolResult:
        nonlocal called
        called = True
        return _result()

    monkeypatch.setattr(MCPServerStreamableHttp, "call_tool", call_tool)
    assert _decoded(_run(_server().call_tool("Other___get_weather", {}))) == {
        "error": TOOL_UNAVAILABLE_MESSAGE
    }
    assert called is False


def test_transport_failure_is_safe_and_does_not_log_internal_values(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_input = "sentinel-location"
    secret_exception = "sentinel-credential"

    async def call_tool(*_: Any, **__: Any) -> CallToolResult:
        raise RuntimeError(f"{secret_exception} {ENDPOINT}")

    monkeypatch.setattr(MCPServerStreamableHttp, "call_tool", call_tool)
    caplog.set_level(logging.DEBUG)
    result = _run(_server().call_tool(WEATHER_TOOL, {"location": secret_input}))

    assert _decoded(result) == {"error": TOOL_UNAVAILABLE_MESSAGE}
    log_text = caplog.text
    assert ENDPOINT not in log_text
    assert secret_input not in log_text
    assert secret_exception not in log_text
    assert "arn:" not in log_text
    assert "credential" not in log_text.lower()


def test_call_tool_timeout_converts_indefinite_base_call_to_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def call_tool(*_: Any, **__: Any) -> CallToolResult:
        # adapter側の明示timeoutがなければ永久に完了しないbase callを再現する。
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(MCPServerStreamableHttp, "call_tool", call_tool)
    monkeypatch.setattr(
        gateway_tools_module,
        "MCP_CLIENT_SESSION_TIMEOUT_SECONDS",
        0.01,
    )

    result = _run(_server().call_tool(WEATHER_TOOL, {"location": "Tokyo"}))

    assert _decoded(result) == {"error": TOOL_UNAVAILABLE_MESSAGE}


def test_cancellation_is_not_converted_to_tool_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def call_tool(*_: Any, **__: Any) -> CallToolResult:
        raise asyncio.CancelledError()

    monkeypatch.setattr(MCPServerStreamableHttp, "call_tool", call_tool)
    with pytest.raises(asyncio.CancelledError):
        _run(_server().call_tool(WEATHER_TOOL, {}))
