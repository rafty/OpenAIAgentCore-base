"""Estimation MCP Adapter、Agent境界、Runtime部分障害を検証する。"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from agents.mcp import MCPServerStreamableHttp
from mcp.types import CallToolResult, TextContent, Tool
from openai.types.responses import ResponseTextDeltaEvent

from agent_app.agent_factory import create_agents
from agent_app.config import AppConfig, GatewayConfig
from agent_app.gateway_tools import (
    ESTIMATION_MCP_TRANSPORT_TIMEOUT_SECONDS,
    ESTIMATION_TOOL_TIMEOUT_SECONDS,
    AgentCoreGatewayMCPServer,
    _public_estimation_tool,
    create_estimation_gateway_mcp_server,
)
from agent_app.service import stream_agent_response


CONFIG = AppConfig(
    aws_region="us-east-1",
    model_id="openai.gpt-5.5",
    memory_id="memory",
    tracing_disabled="1",
    weather_gateway=GatewayConfig("https://w.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp", "us-east-1", "WeatherTimeMock"),
    knowledge_gateway=GatewayConfig("https://k.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp", "us-east-1", "KnowledgeRetrieve"),
    estimation_gateway=GatewayConfig("https://e.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp", "us-east-1", "EstimationTools"),
    estimation_gateway_state="ENABLED",
)


def _result(data: dict[str, Any]) -> CallToolResult:
    payload = {"status": "OK", "data": data, "warnings": [], "correlation_id": "request"}
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload))],
        structuredContent=payload,
        isError=False,
    )


def test_estimation_factory_fixes_transport_tools_and_execution_scope() -> None:
    server = create_estimation_gateway_mcp_server(CONFIG, "actor", "session", transport_factory=lambda **_: object())
    assert server.required_tool_names == (
        "EstimationTools___search_similar_projects",
        "EstimationTools___get_estimation_reference_data",
        "EstimationTools___create_estimate_draft",
        "EstimationTools___get_estimate_draft",
    )
    assert server.params["timeout"] == ESTIMATION_MCP_TRANSPORT_TIMEOUT_SECONDS
    assert server.client_session_timeout_seconds == ESTIMATION_TOOL_TIMEOUT_SECONDS
    arguments = server._estimation_arguments(
        "EstimationTools___create_estimate_draft",
        {"operation": "SAVE", "project": {"project_name": "Delta"}, "_actor_id": "forged", "_idempotency_key": "forged"},
    )
    assert arguments["_actor_id"] == "actor"
    assert arguments["_session_id"] == "session"
    assert arguments["_idempotency_key"] != "forged"
    assert len(arguments["_request_hash"]) == 64


def test_estimation_tool_schema_hides_runtime_reserved_arguments() -> None:
    original = Tool(
        name="EstimationTools___create_estimate_draft",
        description="draft",
        inputSchema={
            "type": "object",
            "properties": {
                "operation": {"type": "string"},
                "_actor_id": {"type": "string"},
                "_session_id": {"type": "string"},
                "_idempotency_key": {"type": "string"},
                "_request_hash": {"type": "string"},
            },
            "required": ["operation", "_actor_id", "_session_id"],
        },
    )

    public = _public_estimation_tool(original)

    assert public.inputSchema["properties"] == {
        "operation": {"type": "string"}
    }
    assert public.inputSchema["required"] == ["operation"]
    # Gatewayから受け取ったSchemaを変更するとcache経由で内部契約まで壊れるため、
    # モデル向けコピーだけを編集する。
    assert "_actor_id" in original.inputSchema["properties"]


def test_estimation_call_validates_result_and_limits_search(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    async def base_call(_self, _name, arguments, meta=None):
        calls.append(arguments)
        return _result({"search_context_id": "ctx", "similar_projects": [], "no_similar_projects": True})

    monkeypatch.setattr(MCPServerStreamableHttp, "call_tool", base_call)
    server = create_estimation_gateway_mcp_server(CONFIG, "actor", "session")
    name = "EstimationTools___search_similar_projects"
    for _ in range(3):
        result = asyncio.run(server.call_tool(name, {"query": "x", "_actor_id": "forged"}))
        assert result.structuredContent["status"] == "OK"
    fourth = asyncio.run(server.call_tool(name, {"query": "x"}))
    assert fourth.structuredContent["status"] == "DEPENDENCY_UNAVAILABLE"
    assert len(calls) == 3 and all(call["_actor_id"] == "actor" for call in calls)

    async def forbidden(_self, _name, _arguments, meta=None):
        return _result({"search_context_id": "ctx", "similar_projects": [], "no_similar_projects": True, "embedding": [0.1]})

    monkeypatch.setattr(MCPServerStreamableHttp, "call_tool", forbidden)
    other = create_estimation_gateway_mcp_server(CONFIG, "actor", "session")
    rejected = asyncio.run(other.call_tool(name, {"query": "x"}))
    assert rejected.structuredContent["status"] == "DEPENDENCY_UNAVAILABLE"


def test_estimation_agent_is_only_manager_tool_and_has_no_handoff() -> None:
    server = SimpleNamespace()
    bundle = create_agents(
        "model",  # type: ignore[arg-type]
        (),
        False,
        (),
        False,
        (server,),  # type: ignore[arg-type]
        True,
    )
    assert [tool.name for tool in bundle.manager.tools] == [
        "weather_agent",
        "aws_knowledge_agent",
        "estimation_agent",
    ]
    assert bundle.manager.mcp_servers == []
    assert bundle.estimation.mcp_servers == [server]
    assert bundle.estimation.handoffs == [] and bundle.manager.handoffs == []
    assert "EXPLICIT_SAVE" in bundle.estimation.instructions
    assert "AMBIGUOUS" in bundle.estimation.instructions
    assert "追加確認を求めません" in bundle.estimation.instructions


class FakeMCP:
    def __init__(self, *, cleanup_error: bool = False) -> None:
        self.cleanup_error = cleanup_error
        self.cleaned = 0

    async def connect(self):
        return None

    async def list_tools(self):
        return [object()]

    async def cleanup(self):
        self.cleaned += 1
        if self.cleanup_error:
            raise RuntimeError("private")


class FakeSession:
    actor_id = "actor"
    session_id = "session"

    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    async def commit(self): self.commits += 1
    async def rollback(self): self.rollbacks += 1


class FakeResult:
    async def stream_events(self):
        yield SimpleNamespace(type="raw_response_event", data=ResponseTextDeltaEvent(content_index=0, delta="継続", item_id="i", logprobs=[], output_index=0, sequence_number=0, type="response.output_text.delta"))


class FakeRunner:
    @staticmethod
    def run_streamed(_agent, **_kwargs): return FakeResult()


def test_estimation_cleanup_failure_does_not_rollback_existing_turn() -> None:
    weather = FakeMCP()
    knowledge = FakeMCP()
    estimation = FakeMCP(cleanup_error=True)
    session = FakeSession()
    availability: list[tuple[bool, bool, bool]] = []

    def agents(*args):
        availability.append((args[2], args[4], args[6]))
        return SimpleNamespace(manager=object())

    async def collect():
        return [
            event
            async for event in stream_agent_response(
                config=CONFIG,
                model="model",  # type: ignore[arg-type]
                prompt="hello",
                session=session,  # type: ignore[arg-type]
                weather_mcp_server_factory=lambda _: weather,
                knowledge_mcp_server_factory=lambda _: knowledge,
                estimation_mcp_server_factory=lambda *_: estimation,
                agent_factory=agents,  # type: ignore[arg-type]
                runner=FakeRunner(),
            )
        ]

    output = asyncio.run(collect())
    assert output[-1] == {"type": "completed"}
    assert availability == [(True, True, True)]
    assert session.commits == 1 and session.rollbacks == 0
    assert weather.cleaned == knowledge.cleaned == estimation.cleaned == 1
