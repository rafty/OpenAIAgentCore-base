"""実Model／AWSなしでAgent-as-ToolとMCPの全経路を確認する結合テスト。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast

import pytest
from agents import Agent, Model, Runner, set_tracing_disabled
from agents.items import ModelResponse
from agents.mcp import MCPServer
from agents.usage import Usage
from mcp.types import CallToolResult, GetPromptResult, ListPromptsResult, TextContent, Tool
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseTextDeltaEvent,
)

from agent_app.agent_factory import AgentBundle, create_agents
from agent_app.config import AppConfig
from agent_app.gateway_tools import TOOL_UNAVAILABLE_MESSAGE
from agent_app.service import stream_agent_response


set_tracing_disabled(True)

TARGET_NAME = "WeatherTimeMock"
WEATHER_TOOL = f"{TARGET_NAME}___get_weather"
TIME_TOOL = f"{TARGET_NAME}___get_time"
MANAGER_CALL_ID = "manager-weather-call"
MCP_CALL_ID = "weather-mcp-call"
PRIVATE_MARKER = "sentinel-private-gateway-detail"
CONFIG = AppConfig(
    aws_region="us-east-2",
    model_id="openai.gpt-5.5",
    memory_id="memory-id",
    tracing_disabled="1",
    gateway_url=(
        "https://gateway-id.gateway.bedrock-agentcore.us-east-2.amazonaws.com/mcp"
    ),
    gateway_target_name=TARGET_NAME,
)


@dataclass(frozen=True, slots=True)
class ToolScenario:
    kind: str
    user_prompt: str
    delegated_prompt: str
    tool_name: str
    arguments: dict[str, str]
    payload: dict[str, str]
    fixed_value: str
    real_data_label: str

    @property
    def specialist_output(self) -> str:
        return (
            f"専門結果: {self.fixed_value}。data_type=mockのテスト用固定モックであり、"
            f"現在の実{self.real_data_label}ではありません。"
        )

    @property
    def final_output(self) -> str:
        return (
            f"{self.fixed_value}。これはdata_type=mockのテスト用固定モックであり、"
            f"現在の実{self.real_data_label}ではありません。"
        )


SCENARIOS = (
    ToolScenario(
        kind="weather",
        user_prompt="東京の天気を教えてください。",
        delegated_prompt="東京の天気をget_weatherで確認してください。",
        tool_name=WEATHER_TOOL,
        arguments={"location": "東京"},
        payload={
            "location": "東京",
            "weather": "72 degrees Fahrenheit, Sunny",
            "data_type": "mock",
        },
        fixed_value="東京の天気は72 degrees Fahrenheit, Sunnyです",
        real_data_label="天気",
    ),
    ToolScenario(
        kind="time",
        user_prompt="Asia/Tokyoの時刻を教えてください。",
        delegated_prompt="Asia/Tokyoの時刻をget_timeで確認してください。",
        tool_name=TIME_TOOL,
        arguments={"timezone": "Asia/Tokyo"},
        payload={
            "timezone": "Asia/Tokyo",
            "local_time": "2:30 PM",
            "data_type": "mock",
        },
        fixed_value="Asia/Tokyoの時刻は2:30 PMです",
        real_data_label="時刻",
    ),
)

FAILURE_MODES = (
    "connect",
    "list",
    "transport_exception",
    "tool_exception",
    "lambda_error",
    "malformed_result",
)
SAFE_SPECIALIST_OUTPUT = "専門結果: 現在、天気・時刻情報を取得できません。"
SAFE_FINAL_OUTPUT = (
    "現在、天気・時刻情報を取得できません。固定値、システム時計、推測値では"
    "代替していません。"
)


def _tool_result(payload: Mapping[str, Any]) -> CallToolResult:
    normalized = dict(payload)
    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=json.dumps(
                    normalized,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            )
        ],
        structuredContent=normalized,
        isError=False,
    )


def _unavailable_result() -> CallToolResult:
    return _tool_result({"error": TOOL_UNAVAILABLE_MESSAGE})


class FakeGatewayMCP(MCPServer):
    """Gateway公開Toolと、adapterが安全に正規化する障害を再現する。"""

    def __init__(
        self,
        scenario: ToolScenario,
        failure_mode: str | None,
        route: list[str],
    ) -> None:
        super().__init__(use_structured_content=False, failure_error_function=None)
        self.scenario = scenario
        self.failure_mode = failure_mode
        self.route = route
        self.connects = 0
        self.list_calls = 0
        self.cleanups = 0
        self.tool_calls: list[tuple[str, dict[str, Any] | None]] = []
        self.failure_exercised = False

    @property
    def name(self) -> str:
        return "FakeAgentCoreWeatherGateway"

    async def connect(self) -> None:
        self.connects += 1
        self.route.append("connect")
        if self.failure_mode == "connect":
            self.failure_exercised = True
            raise RuntimeError(f"{PRIVATE_MARKER}: connect")

    async def cleanup(self) -> None:
        self.cleanups += 1
        self.route.append("cleanup")

    async def list_tools(
        self,
        run_context: Any | None = None,
        agent: Any | None = None,
    ) -> list[Tool]:
        self.list_calls += 1
        self.route.append("list")
        if self.failure_mode == "list":
            self.failure_exercised = True
            raise RuntimeError(f"{PRIVATE_MARKER}: list")
        return [
            Tool(
                name=WEATHER_TOOL,
                description="Return fixed mock weather data; no real service is called.",
                inputSchema={
                    "type": "object",
                    "properties": {"location": {"type": "string"}},
                    "required": ["location"],
                },
            ),
            Tool(
                name=TIME_TOOL,
                description="Return fixed mock time data; no real service is called.",
                inputSchema={
                    "type": "object",
                    "properties": {"timezone": {"type": "string"}},
                    "required": ["timezone"],
                },
            ),
        ]

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None,
        meta: dict[str, Any] | None = None,
    ) -> CallToolResult:
        self.route.append("mcp_tool")
        self.tool_calls.append((tool_name, arguments))
        assert tool_name == self.scenario.tool_name
        assert arguments == self.scenario.arguments

        # 本番adapterと同じく、transport／Tool例外や不正なLambda結果を
        # モデル可視の固定取得不能結果へ正規化してからSDKへ返す。
        try:
            if self.failure_mode in {"transport_exception", "tool_exception"}:
                self.failure_exercised = True
                raise RuntimeError(f"{PRIVATE_MARKER}: {self.failure_mode}")
            if self.failure_mode == "lambda_error":
                self.failure_exercised = True
                raw_payload: Mapping[str, Any] = {
                    "error": f"{PRIVATE_MARKER}: lambda"
                }
            elif self.failure_mode == "malformed_result":
                self.failure_exercised = True
                raw_payload = {"unexpected": PRIVATE_MARKER, "data_type": "real"}
            else:
                raw_payload = self.scenario.payload
        except Exception:
            return _unavailable_result()

        if "error" in raw_payload or raw_payload.get("data_type") != "mock":
            return _unavailable_result()
        return _tool_result(raw_payload)

    async def list_prompts(self) -> ListPromptsResult:
        return ListPromptsResult(prompts=[])

    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> GetPromptResult:
        raise NotImplementedError


def _json_default(value: Any) -> Any:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    return str(value)


def _function_outputs(input_items: Any) -> dict[str, str]:
    outputs: dict[str, str] = {}
    if not isinstance(input_items, list):
        return outputs
    for item in input_items:
        if isinstance(item, Mapping):
            item_type = item.get("type")
            call_id = item.get("call_id")
            output = item.get("output")
        else:
            item_type = getattr(item, "type", None)
            call_id = getattr(item, "call_id", None)
            output = getattr(item, "output", None)
        if item_type == "function_call_output" and isinstance(call_id, str):
            outputs[call_id] = json.dumps(
                output,
                ensure_ascii=False,
                default=_json_default,
            )
    return outputs


def _message(text: str, item_id: str) -> ModelResponse:
    return ModelResponse(
        output=[
            ResponseOutputMessage(
                id=item_id,
                content=[
                    ResponseOutputText(
                        annotations=[],
                        text=text,
                        type="output_text",
                    )
                ],
                role="assistant",
                status="completed",
                type="message",
            )
        ],
        usage=Usage(),
        response_id=None,
    )


def _function_call(
    *,
    name: str,
    arguments: Mapping[str, Any],
    call_id: str,
) -> ModelResponse:
    return ModelResponse(
        output=[
            ResponseFunctionToolCall(
                arguments=json.dumps(arguments, ensure_ascii=False),
                call_id=call_id,
                name=name,
                type="function_call",
                status="completed",
            )
        ],
        usage=Usage(),
        response_id=None,
    )


@dataclass(frozen=True, slots=True)
class ModelCall:
    agent: str
    tool_names: tuple[str, ...]
    function_outputs: dict[str, str]


class ScriptedMultiAgentModel(Model):
    """各Agent段階をTool call IDで識別して決定的な応答を返す。"""

    def __init__(
        self,
        scenario: ToolScenario,
        failure_mode: str | None,
        route: list[str],
    ) -> None:
        self.scenario = scenario
        self.failure_mode = failure_mode
        self.route = route
        self.calls: list[ModelCall] = []
        self.stages: list[str] = []

    async def get_response(
        self,
        system_instructions: str | None,
        input: str | list[Any],
        model_settings: Any,
        tools: Sequence[Any],
        output_schema: Any,
        handoffs: Sequence[Any],
        tracing: Any,
        **kwargs: Any,
    ) -> ModelResponse:
        instructions = system_instructions or ""
        agent = "weather" if "Weather Agentです" in instructions else "manager"
        tool_names = tuple(tool.name for tool in tools)
        outputs = _function_outputs(input)
        self.calls.append(ModelCall(agent, tool_names, outputs))
        assert list(handoffs) == []

        if agent == "manager" and MANAGER_CALL_ID not in outputs:
            self.stages.append("manager_routes_to_weather")
            self.route.append("manager_routes_to_weather")
            assert tool_names == ("weather_agent",)
            return _function_call(
                name="weather_agent",
                arguments={"input": self.scenario.delegated_prompt},
                call_id=MANAGER_CALL_ID,
            )

        if agent == "weather" and MCP_CALL_ID not in outputs:
            if self.scenario.tool_name in tool_names:
                self.stages.append("weather_routes_to_mcp")
                self.route.append("weather_routes_to_mcp")
                assert set(tool_names) == {WEATHER_TOOL, TIME_TOOL}
                return _function_call(
                    name=self.scenario.tool_name,
                    arguments=self.scenario.arguments,
                    call_id=MCP_CALL_ID,
                )

            # connect／list失敗ではMCPを持たないunavailable Weather Agentが回答する。
            self.stages.append("weather_returns_unavailable")
            self.route.append("weather_returns_unavailable")
            assert self.failure_mode in {"connect", "list"}
            assert "Toolを利用できません" in instructions
            return _message(SAFE_SPECIALIST_OUTPUT, "weather-unavailable")

        if agent == "weather":
            self.stages.append("weather_uses_mcp_result")
            self.route.append("weather_uses_mcp_result")
            mcp_output = outputs[MCP_CALL_ID]
            if self.failure_mode is None:
                # SDKはMCP TextContentをinput_text配列へ包むため、JSONのescape表現ではなく
                # 契約上のkey/valueを個別に確認して特定のserialize形式へ依存しない。
                assert "data_type" in mcp_output
                assert "mock" in mcp_output
                for value in self.scenario.payload.values():
                    assert value in mcp_output
                return _message(self.scenario.specialist_output, "weather-result")

            assert TOOL_UNAVAILABLE_MESSAGE in mcp_output
            assert PRIVATE_MARKER not in mcp_output
            return _message(SAFE_SPECIALIST_OUTPUT, "weather-unavailable")

        self.stages.append("manager_returns_final")
        self.route.append("manager_returns_final")
        agent_output = outputs[MANAGER_CALL_ID]
        expected_specialist = (
            self.scenario.specialist_output
            if self.failure_mode is None
            else SAFE_SPECIALIST_OUTPUT
        )
        assert expected_specialist in agent_output
        return _message(
            self.scenario.final_output
            if self.failure_mode is None
            else SAFE_FINAL_OUTPUT,
            "manager-final",
        )

    async def stream_response(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        if False:
            yield None


class FakeSession:
    """SDK履歴をメモリ内に保持し、serviceのcommit／rollbackを記録する。"""

    def __init__(self, route: list[str]) -> None:
        self.route = route
        self.items: list[Any] = []
        self.commits = 0
        self.rollbacks = 0

    async def get_items(self, limit: int | None = None) -> list[Any]:
        if limit is None:
            return list(self.items)
        return list(self.items[-limit:]) if limit else []

    async def add_items(self, items: list[Any]) -> None:
        self.items.extend(items)

    async def pop_item(self) -> Any | None:
        return self.items.pop() if self.items else None

    async def clear_session(self) -> None:
        self.items.clear()

    async def commit(self) -> None:
        self.commits += 1
        self.route.append("commit")

    async def rollback(self) -> None:
        self.rollbacks += 1
        self.route.append("rollback")


def _delta(value: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="raw_response_event",
        data=ResponseTextDeltaEvent(
            content_index=0,
            delta=value,
            item_id="manager-final",
            logprobs=[],
            output_index=0,
            sequence_number=1,
            type="response.output_text.delta",
        ),
    )


class SDKRunnerAdapter:
    """Runner.runの実SDK結果をserviceが扱うstream eventへ変換する。"""

    def __init__(self, route: list[str]) -> None:
        self.route = route
        self.results: list[Any] = []

    def run_streamed(self, starting_agent: Agent, **kwargs: Any) -> Any:
        adapter = self

        class AdaptedResult:
            async def stream_events(self) -> AsyncIterator[Any]:
                # scripted Modelは非stream応答を返すため、SDKのRunner.runでAgent／Tool
                # 往復を完了し、その最終Manager出力だけを本番service形式へ変換する。
                result = await Runner.run(
                    starting_agent,
                    kwargs["input"],
                    session=kwargs["session"],
                )
                adapter.results.append(result)
                adapter.route.append("runner_result")
                yield _delta(cast(str, result.final_output))

        return AdaptedResult()


@dataclass(slots=True)
class FlowResult:
    events: list[dict[str, Any]]
    model: ScriptedMultiAgentModel
    server: FakeGatewayMCP
    session: FakeSession
    runner: SDKRunnerAdapter
    bundles: list[AgentBundle]
    factory_calls: list[tuple[list[FakeGatewayMCP], bool]]
    route: list[str]


def _run_flow(
    scenario: ToolScenario,
    failure_mode: str | None = None,
) -> FlowResult:
    route: list[str] = []
    model = ScriptedMultiAgentModel(scenario, failure_mode, route)
    server = FakeGatewayMCP(scenario, failure_mode, route)
    session = FakeSession(route)
    runner = SDKRunnerAdapter(route)
    bundles: list[AgentBundle] = []
    factory_calls: list[tuple[list[FakeGatewayMCP], bool]] = []

    def mcp_server_factory(config: AppConfig) -> FakeGatewayMCP:
        assert config is CONFIG
        return server

    def agent_factory(
        active_model: Model,
        servers: Sequence[FakeGatewayMCP],
        gateway_available: bool,
    ) -> AgentBundle:
        assert active_model is model
        route.append("agent_factory")
        active_servers = list(servers)
        factory_calls.append((active_servers, gateway_available))
        bundle = create_agents(active_model, active_servers, gateway_available)
        bundles.append(bundle)
        return bundle

    async def collect() -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        async for event in stream_agent_response(
            config=CONFIG,
            model=model,
            prompt=scenario.user_prompt,
            session=session,  # type: ignore[arg-type]
            mcp_server_factory=mcp_server_factory,
            agent_factory=agent_factory,  # type: ignore[arg-type]
            runner=runner,
        ):
            output.append(event)
            if event["type"] == "completed":
                route.append("completed")
        return output

    return FlowResult(
        events=asyncio.run(collect()),
        model=model,
        server=server,
        session=session,
        runner=runner,
        bundles=bundles,
        factory_calls=factory_calls,
        route=route,
    )


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.kind)
def test_manager_weather_mcp_manager_path_returns_fixed_mock(
    scenario: ToolScenario,
) -> None:
    result = _run_flow(scenario)

    assert result.events == [
        {"type": "text_delta", "delta": scenario.final_output},
        {"type": "completed"},
    ]
    assert result.model.stages == [
        "manager_routes_to_weather",
        "weather_routes_to_mcp",
        "weather_uses_mcp_result",
        "manager_returns_final",
    ]
    assert [call.agent for call in result.model.calls] == [
        "manager",
        "weather",
        "weather",
        "manager",
    ]
    assert result.server.tool_calls == [(scenario.tool_name, scenario.arguments)]
    assert result.factory_calls == [([result.server], True)]
    assert result.runner.results[0].last_agent is result.bundles[0].manager
    assert result.session.commits == 1
    assert result.session.rollbacks == 0
    assert result.server.cleanups == 1
    assert scenario.fixed_value in scenario.final_output
    assert "data_type=mock" in scenario.final_output
    assert "テスト用固定モック" in scenario.final_output
    assert f"現在の実{scenario.real_data_label}ではありません" in scenario.final_output

    # serviceの事前list後にAgentを構成し、Weatherだけが完全修飾MCP Toolを呼ぶ。
    assert result.route.index("list") < result.route.index("agent_factory")
    assert result.route.index("manager_routes_to_weather") < result.route.index(
        "weather_routes_to_mcp"
    ) < result.route.index("mcp_tool") < result.route.index("weather_uses_mcp_result")
    assert result.route.index("manager_returns_final") < result.route.index(
        "cleanup"
    ) < result.route.index("commit") < result.route.index("completed")


@pytest.mark.parametrize("failure_mode", FAILURE_MODES)
def test_gateway_or_tool_failure_returns_safe_committed_answer(
    failure_mode: str,
) -> None:
    scenario = SCENARIOS[0]
    result = _run_flow(scenario, failure_mode)

    assert result.events == [
        {"type": "text_delta", "delta": SAFE_FINAL_OUTPUT},
        {"type": "completed"},
    ]
    assert all(event["type"] != "error" for event in result.events)
    assert result.runner.results[0].last_agent is result.bundles[0].manager
    assert result.session.commits == 1
    assert result.session.rollbacks == 0
    assert result.server.cleanups == 1
    assert result.server.failure_exercised is True
    assert "取得できません" in SAFE_FINAL_OUTPUT

    # 取得していないFR-003値や内部情報を、障害時の最終回答へ混入させない。
    for forbidden in (
        "72 degrees Fahrenheit, Sunny",
        "2:30 PM",
        "data_type=mock",
        PRIVATE_MARKER,
        "gateway-id",
        "arn:aws",
        "Traceback",
    ):
        assert forbidden not in SAFE_FINAL_OUTPUT

    if failure_mode in {"connect", "list"}:
        assert result.factory_calls == [([], False)]
        assert result.server.tool_calls == []
        assert result.model.stages == [
            "manager_routes_to_weather",
            "weather_returns_unavailable",
            "manager_returns_final",
        ]
    else:
        assert result.factory_calls == [([result.server], True)]
        assert result.server.tool_calls == [(scenario.tool_name, scenario.arguments)]
        assert result.model.stages == [
            "manager_routes_to_weather",
            "weather_routes_to_mcp",
            "weather_uses_mcp_result",
            "manager_returns_final",
        ]

    assert result.route.index("cleanup") < result.route.index("commit")
    assert result.route.index("commit") < result.route.index("completed")
