"""2 MCP、Runner、Memoryの確定順序と失敗境界を検証する。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from openai.types.responses import ResponseTextDeltaEvent

import agent_app.service as service_module
from agent_app.config import AppConfig, GatewayConfig
from agent_app.service import stream_agent_response


CONFIG = AppConfig(
    aws_region="us-east-1",
    model_id="openai.gpt-5.5",
    memory_id="memory-id",
    tracing_disabled="1",
    weather_gateway=GatewayConfig(
        url="https://weather.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp",
        region="us-east-1",
        target_name="WeatherTimeMock",
    ),
    knowledge_gateway=GatewayConfig(
        url="https://knowledge.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp",
        region="us-east-1",
        target_name="KnowledgeRetrieve",
    ),
)


async def _hang_forever() -> None:
    await asyncio.Event().wait()


def _delta(value: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="raw_response_event",
        data=ResponseTextDeltaEvent(
            content_index=0,
            delta=value,
            item_id="message",
            logprobs=[],
            output_index=0,
            sequence_number=1,
            type="response.output_text.delta",
        ),
    )


class FakeMCP:
    def __init__(
        self,
        kind: str,
        events: list[str],
        *,
        fail: str | None = None,
        hang: str | None = None,
    ) -> None:
        self.kind = kind
        self.events = events
        self.fail = fail
        self.hang = hang
        self.counts = {name: 0 for name in ("connect", "list", "cleanup")}

    async def _operate(self, operation: str) -> None:
        self.events.append(f"{self.kind}.{operation}")
        self.counts[operation] += 1
        if self.hang == operation:
            await _hang_forever()
        if self.fail == operation:
            raise RuntimeError(f"private-{self.kind}-{operation}")

    async def connect(self) -> None:
        await self._operate("connect")

    async def list_tools(self) -> list[object]:
        await self._operate("list")
        return [object()]

    async def cleanup(self) -> None:
        await self._operate("cleanup")


class FakeSession:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.events.append("commit")
        self.commits += 1

    async def rollback(self) -> None:
        self.events.append("rollback")
        self.rollbacks += 1


class FakeResult:
    def __init__(
        self,
        output_events: list[Any] | None = None,
        *,
        error: BaseException | None = None,
    ) -> None:
        self.output_events = output_events or []
        self.error = error

    async def stream_events(self):
        for event in self.output_events:
            yield event
        if self.error is not None:
            raise self.error


class FakeRunner:
    def __init__(
        self,
        events: list[str],
        result: FakeResult,
        *,
        error: BaseException | None = None,
    ) -> None:
        self.events = events
        self.result = result
        self.error = error

    def run_streamed(self, starting_agent: object, **kwargs: Any) -> FakeResult:
        self.events.append("run")
        assert kwargs["input"] == "question"
        assert kwargs["session"] is not None
        if self.error is not None:
            raise self.error
        return self.result


class FakeAgentFactory:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.calls: list[tuple[Any, list[Any], bool, list[Any], bool]] = []

    def __call__(
        self,
        model: Any,
        weather_servers: list[Any],
        weather_available: bool,
        knowledge_servers: list[Any],
        knowledge_available: bool,
    ) -> SimpleNamespace:
        self.events.append("agent")
        self.calls.append(
            (
                model,
                list(weather_servers),
                weather_available,
                list(knowledge_servers),
                knowledge_available,
            )
        )
        return SimpleNamespace(manager=object(), weather=object(), knowledge=object())


def _collect(
    *,
    weather: FakeMCP | None,
    knowledge: FakeMCP | None,
    events: list[str],
    session: FakeSession,
    result: FakeResult | None = None,
    weather_factory_error: bool = False,
    knowledge_factory_error: bool = False,
    runner_error: BaseException | None = None,
) -> tuple[list[dict[str, Any]], FakeAgentFactory]:
    agent_factory = FakeAgentFactory(events)

    def weather_factory(config: AppConfig) -> FakeMCP:
        events.append("weather.factory")
        assert config is CONFIG
        if weather_factory_error:
            raise RuntimeError("private-weather-factory")
        assert weather is not None
        return weather

    def knowledge_factory(config: AppConfig) -> FakeMCP:
        events.append("knowledge.factory")
        assert config is CONFIG
        if knowledge_factory_error:
            raise RuntimeError("private-knowledge-factory")
        assert knowledge is not None
        return knowledge

    async def run() -> list[dict[str, Any]]:
        output = []
        async for event in stream_agent_response(
            config=CONFIG,
            model="shared-model",  # type: ignore[arg-type]
            prompt="question",
            session=session,  # type: ignore[arg-type]
            weather_mcp_server_factory=weather_factory,
            knowledge_mcp_server_factory=knowledge_factory,
            agent_factory=agent_factory,  # type: ignore[arg-type]
            runner=FakeRunner(
                events,
                result or FakeResult(),
                error=runner_error,
            ),
        ):
            output.append(event)
            if event["type"] in {"completed", "error"}:
                events.append(event["type"])
        return output

    return asyncio.run(run()), agent_factory


def test_success_connects_both_and_cleans_up_in_reverse_before_commit() -> None:
    events: list[str] = []
    weather = FakeMCP("weather", events)
    knowledge = FakeMCP("knowledge", events)
    session = FakeSession(events)

    output, agent_factory = _collect(
        weather=weather,
        knowledge=knowledge,
        events=events,
        session=session,
        result=FakeResult([_delta("A"), SimpleNamespace(type="internal"), _delta("B")]),
    )

    assert output == [
        {"type": "text_delta", "delta": "A"},
        {"type": "text_delta", "delta": "B"},
        {"type": "completed"},
    ]
    assert events == [
        "weather.factory",
        "weather.connect",
        "weather.list",
        "knowledge.factory",
        "knowledge.connect",
        "knowledge.list",
        "agent",
        "run",
        "knowledge.cleanup",
        "weather.cleanup",
        "commit",
        "completed",
    ]
    assert agent_factory.calls == [
        ("shared-model", [weather], True, [knowledge], True)
    ]
    assert (session.commits, session.rollbacks) == (1, 0)


@pytest.mark.parametrize(
    ("failed_kind", "stage"),
    [("weather", "connect"), ("weather", "list"), ("knowledge", "connect"), ("knowledge", "list")],
)
def test_one_gateway_failure_is_local_and_other_gateway_commits(
    failed_kind: str,
    stage: str,
) -> None:
    events: list[str] = []
    weather = FakeMCP(
        "weather", events, fail=stage if failed_kind == "weather" else None
    )
    knowledge = FakeMCP(
        "knowledge", events, fail=stage if failed_kind == "knowledge" else None
    )
    session = FakeSession(events)

    output, agent_factory = _collect(
        weather=weather,
        knowledge=knowledge,
        events=events,
        session=session,
        result=FakeResult([_delta("partial-service-answer")]),
    )

    expected_weather = [] if failed_kind == "weather" else [weather]
    expected_knowledge = [] if failed_kind == "knowledge" else [knowledge]
    assert agent_factory.calls == [
        (
            "shared-model",
            expected_weather,
            bool(expected_weather),
            expected_knowledge,
            bool(expected_knowledge),
        )
    ]
    assert output[-1] == {"type": "completed"}
    assert weather.counts["cleanup"] == 1
    assert knowledge.counts["cleanup"] == 1
    assert (session.commits, session.rollbacks) == (1, 0)


def test_both_factory_failures_use_safe_unavailable_agents_without_connections() -> None:
    events: list[str] = []
    session = FakeSession(events)

    output, agent_factory = _collect(
        weather=None,
        knowledge=None,
        events=events,
        session=session,
        weather_factory_error=True,
        knowledge_factory_error=True,
        result=FakeResult([_delta("両方の専門情報を取得できません。")]),
    )

    assert output[-1] == {"type": "completed"}
    assert agent_factory.calls == [("shared-model", [], False, [], False)]
    assert "cleanup" not in " ".join(events)
    assert (session.commits, session.rollbacks) == (1, 0)


@pytest.mark.parametrize(("kind", "stage"), [("weather", "connect"), ("knowledge", "list")])
def test_connect_or_list_timeout_is_localized(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    stage: str,
) -> None:
    monkeypatch.setattr(service_module, "MCP_TRANSPORT_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(service_module, "MCP_CLIENT_SESSION_TIMEOUT_SECONDS", 0.01)
    events: list[str] = []
    weather = FakeMCP(
        "weather", events, hang=stage if kind == "weather" else None
    )
    knowledge = FakeMCP(
        "knowledge", events, hang=stage if kind == "knowledge" else None
    )
    session = FakeSession(events)

    output, agent_factory = _collect(
        weather=weather,
        knowledge=knowledge,
        events=events,
        session=session,
        result=FakeResult([_delta("available-side-answer")]),
    )

    assert output[-1] == {"type": "completed"}
    assert agent_factory.calls[0][2] is (kind != "weather")
    assert agent_factory.calls[0][4] is (kind != "knowledge")
    assert weather.counts["cleanup"] == knowledge.counts["cleanup"] == 1
    assert (session.commits, session.rollbacks) == (1, 0)


@pytest.mark.parametrize("cleanup_mode", ["failure", "timeout"])
def test_cleanup_failure_attempts_both_then_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
    cleanup_mode: str,
) -> None:
    monkeypatch.setattr(service_module, "MCP_CLEANUP_TIMEOUT_SECONDS", 0.01)
    events: list[str] = []
    weather = FakeMCP("weather", events)
    knowledge = FakeMCP(
        "knowledge",
        events,
        fail="cleanup" if cleanup_mode == "failure" else None,
        hang="cleanup" if cleanup_mode == "timeout" else None,
    )
    session = FakeSession(events)

    output, _ = _collect(
        weather=weather,
        knowledge=knowledge,
        events=events,
        session=session,
        result=FakeResult([_delta("partial")]),
    )

    assert output[-1] == {"type": "error", "message": "処理中にエラーが発生しました。"}
    assert all(event["type"] != "completed" for event in output)
    assert events.index("knowledge.cleanup") < events.index("weather.cleanup")
    assert events.index("weather.cleanup") < events.index("rollback")
    assert weather.counts["cleanup"] == knowledge.counts["cleanup"] == 1
    assert (session.commits, session.rollbacks) == (0, 1)


def test_runner_failure_cleans_both_then_rolls_back() -> None:
    events: list[str] = []
    weather = FakeMCP("weather", events)
    knowledge = FakeMCP("knowledge", events)
    session = FakeSession(events)

    output, _ = _collect(
        weather=weather,
        knowledge=knowledge,
        events=events,
        session=session,
        runner_error=RuntimeError("private-runner"),
    )

    assert output == [{"type": "error", "message": "処理中にエラーが発生しました。"}]
    assert events.index("knowledge.cleanup") < events.index("weather.cleanup")
    assert events.index("weather.cleanup") < events.index("rollback")
    assert (session.commits, session.rollbacks) == (0, 1)


def test_cancellation_cleans_both_rolls_back_and_rethrows_original() -> None:
    events: list[str] = []
    weather = FakeMCP("weather", events)
    knowledge = FakeMCP("knowledge", events)
    session = FakeSession(events)
    agent_factory = FakeAgentFactory(events)

    async def run() -> list[dict[str, Any]]:
        output = []
        with pytest.raises(asyncio.CancelledError, match="client-disconnected"):
            async for event in stream_agent_response(
                config=CONFIG,
                model="shared-model",  # type: ignore[arg-type]
                prompt="question",
                session=session,  # type: ignore[arg-type]
                weather_mcp_server_factory=lambda _: weather,
                knowledge_mcp_server_factory=lambda _: knowledge,
                agent_factory=agent_factory,  # type: ignore[arg-type]
                runner=FakeRunner(
                    events,
                    FakeResult(
                        [_delta("partial")],
                        error=asyncio.CancelledError("client-disconnected"),
                    ),
                ),
            ):
                output.append(event)
        return output

    assert asyncio.run(run()) == [{"type": "text_delta", "delta": "partial"}]
    assert events.index("knowledge.cleanup") < events.index("weather.cleanup")
    assert events.index("weather.cleanup") < events.index("rollback")
    assert weather.counts["cleanup"] == knowledge.counts["cleanup"] == 1
    assert (session.commits, session.rollbacks) == (0, 1)
