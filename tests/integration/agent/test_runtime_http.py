"""HTTP/SSE境界とAgentCore Memory Session連携を通す結合テスト。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import partial
from types import SimpleNamespace
from typing import Any

import pytest
from agents.stream_events import RawResponsesStreamEvent
from openai.types.responses import ResponseTextDeltaEvent
from starlette.testclient import TestClient

from agent_app.config import AppConfig
from agent_app.contracts import InvocationInput
from agent_app.runtime import create_runtime_app
from agent_app.service import stream_agent_response
from agent_app.session import AgentCoreMemorySession


SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"
MODEL = object()
CONFIG = AppConfig(
    aws_region="us-east-2",
    model_id="openai.gpt-5.5",
    memory_id="memory",
    tracing_disabled="1",
    gateway_url=(
        "https://gateway-id.gateway.bedrock-agentcore.us-east-2.amazonaws.com/mcp"
    ),
    gateway_target_name="WeatherTimeMock",
)


def _delta(text: str, sequence: int) -> RawResponsesStreamEvent:
    return RawResponsesStreamEvent(
        data=ResponseTextDeltaEvent(
            content_index=0,
            delta=text,
            item_id="message",
            logprobs=[],
            output_index=0,
            sequence_number=sequence,
            type="response.output_text.delta",
        )
    )


class FakeMemoryDataClient:
    """actor/session単位のイベント保存と失敗注入を再現するMemory代替。"""

    def __init__(self) -> None:
        self.events: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        self.create_failure = False
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def list_events(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("list", kwargs))
        key = (kwargs["memoryId"], kwargs["actorId"], kwargs["sessionId"])
        return {"events": list(self.events.get(key, []))}

    def create_event(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("create", kwargs))
        if self.create_failure:
            raise RuntimeError("memory-internal-secret")
        key = (kwargs["memoryId"], kwargs["actorId"], kwargs["sessionId"])
        event = {
            "memoryId": kwargs["memoryId"],
            "actorId": kwargs["actorId"],
            "sessionId": kwargs["sessionId"],
            "eventId": f"event-{len(self.events.setdefault(key, []))}",
            "eventTimestamp": datetime.now(timezone.utc),
            "payload": kwargs["payload"],
        }
        self.events[key].append(event)
        return {"event": event}


class RecordingMemorySession(AgentCoreMemorySession):
    """本番Sessionを使いながらcommit／rollbackの確定順だけを記録する。"""

    def __init__(self, *, lifecycle: list[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.lifecycle = lifecycle

    async def commit(self) -> None:
        self.lifecycle.append("commit_attempt")
        await super().commit()
        self.lifecycle.append("commit")

    async def rollback(self) -> None:
        await super().rollback()
        self.lifecycle.append("rollback")


class RecordingSessionFactory:
    """Runtime入力を本番Memory Sessionの分離キーへ渡した結果を保持する。"""

    def __init__(self, memory: FakeMemoryDataClient) -> None:
        self.memory = memory
        self.sessions: list[RecordingMemorySession] = []

    def __call__(
        self,
        config: AppConfig,
        invocation: InvocationInput,
    ) -> RecordingMemorySession:
        lifecycle: list[str] = []
        session = RecordingMemorySession(
            memory_id=config.memory_id,
            actor_id=invocation.actor_id,
            session_id=invocation.session_id,
            region=config.aws_region,
            client=self.memory,
            lifecycle=lifecycle,
        )
        self.sessions.append(session)
        return session


class FakeMCPServer:
    """実Gatewayへ接続せず本番serviceの接続・終了経路を通すMCP代替。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def connect(self) -> None:
        self.calls.append("connect")

    async def list_tools(self) -> list[object]:
        self.calls.append("list")
        return [object(), object()]

    async def cleanup(self) -> None:
        self.calls.append("cleanup")


class FakeMCPServerFactory:
    """Runtime invocationごとに独立したMCP serverを返すfactory代替。"""

    def __init__(self) -> None:
        self.servers: list[FakeMCPServer] = []

    def __call__(self, config: AppConfig) -> FakeMCPServer:
        assert config is CONFIG
        server = FakeMCPServer()
        self.servers.append(server)
        return server


class FakeAgentFactory:
    """接続確認済みMCPを受け取る新しいAgent factory境界を記録する。"""

    def __init__(self) -> None:
        self.calls: list[tuple[object, list[object], bool]] = []

    def __call__(
        self,
        model: object,
        servers: list[object],
        gateway_available: bool,
    ) -> SimpleNamespace:
        self.calls.append((model, list(servers), gateway_available))
        return SimpleNamespace(manager=object(), weather=object())


class FakeRunResult:
    """履歴読込、item追加、複数delta、任意失敗の順序を再現する実行結果。"""

    def __init__(
        self,
        session: RecordingMemorySession,
        *,
        prompt: str,
        fail: bool,
        observed_history: list[list[dict[str, Any]]],
    ) -> None:
        self.session = session
        self.prompt = prompt
        self.fail = fail
        self.observed_history = observed_history

    async def stream_events(self):
        self.observed_history.append(await self.session.get_items())
        await self.session.add_items(
            [
                {"role": "user", "content": self.prompt},
                {"role": "assistant", "content": "回答"},
            ]
        )
        yield _delta("回", 1)
        yield _delta("答", 2)
        if self.fail:
            raise RuntimeError("model-internal-secret")


class FakeRunner:
    """本番serviceへFakeRunResultを返し、実model呼び出しを遮断する。"""

    fail = False
    observed_history: list[list[dict[str, Any]]] = []

    @classmethod
    def run_streamed(cls, starting_agent: object, **kwargs: Any) -> FakeRunResult:
        return FakeRunResult(
            kwargs["session"],
            prompt=kwargs["input"],
            fail=cls.fail,
            observed_history=cls.observed_history,
        )


def _events(response: Any) -> list[dict[str, Any]]:
    """SSE本文を契約検証しやすいevent配列へ変換する。"""

    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def _app(
    memory: FakeMemoryDataClient,
) -> tuple[
    Any,
    RecordingSessionFactory,
    FakeMCPServerFactory,
    FakeAgentFactory,
]:
    session_factory = RecordingSessionFactory(memory)
    mcp_server_factory = FakeMCPServerFactory()
    agent_factory = FakeAgentFactory()
    app = create_runtime_app(
        config=CONFIG,
        model=MODEL,  # type: ignore[arg-type]
        agent_factory=agent_factory,  # type: ignore[arg-type]
        mcp_server_factory=mcp_server_factory,
        session_factory=session_factory,
        stream_service=partial(stream_agent_response, runner=FakeRunner),
    )
    return app, session_factory, mcp_server_factory, agent_factory


def test_ping_uses_production_runtime_health_contract() -> None:
    app, session_factory, mcp_factory, agent_factory = _app(FakeMemoryDataClient())

    with TestClient(app) as client:
        response = client.get("/ping")

    assert response.status_code == 200
    assert response.json()["status"] in {"Healthy", "HealthyBusy"}
    assert session_factory.sessions == []
    assert mcp_factory.servers == []
    assert agent_factory.calls == []


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({}, id="missing-fields"),
        pytest.param({"prompt": "", "actor_id": "actor"}, id="empty-prompt"),
        pytest.param({"prompt": "question", "actor_id": ""}, id="empty-actor"),
        pytest.param([], id="non-object"),
    ],
)
def test_invalid_input_returns_4xx_before_dependency_initialization(payload: Any) -> None:
    app, session_factory, mcp_factory, agent_factory = _app(FakeMemoryDataClient())

    with TestClient(app) as client:
        response = client.post("/invocations", json=payload)

    assert response.status_code == 400
    assert response.json() == {"error": "入力内容が不正です。"}
    assert session_factory.sessions == []
    assert mcp_factory.servers == []
    assert agent_factory.calls == []


def test_context_or_config_failure_returns_safe_5xx() -> None:
    valid_app, session_factory, _, _ = _app(FakeMemoryDataClient())

    def invalid_config_loader() -> AppConfig:
        raise RuntimeError("config-internal-secret")

    invalid_config_app = create_runtime_app(
        config_loader=invalid_config_loader,
        model=MODEL,  # type: ignore[arg-type]
    )
    with TestClient(valid_app) as client:
        missing_session = client.post(
            "/invocations",
            json={"prompt": "question", "actor_id": "actor"},
        )
    with TestClient(invalid_config_app) as client:
        invalid_config = client.post(
            "/invocations",
            json={"prompt": "question", "actor_id": "actor"},
            headers={SESSION_HEADER: "session"},
        )

    for response in (missing_session, invalid_config):
        assert response.status_code == 500
        assert response.json() == {"error": "処理を開始できませんでした。"}
        assert "secret" not in response.text
    assert session_factory.sessions == []


def test_http_sse_and_session_history_restore_and_separation() -> None:
    memory = FakeMemoryDataClient()
    app, session_factory, mcp_factory, agent_factory = _app(memory)
    FakeRunner.fail = False
    FakeRunner.observed_history = []

    with TestClient(app) as client:
        first = client.post(
            "/invocations",
            json={"prompt": "first", "actor_id": "actor-a"},
            headers={SESSION_HEADER: "session-a"},
        )
        second = client.post(
            "/invocations",
            json={"prompt": "second", "actor_id": "actor-a"},
            headers={SESSION_HEADER: "session-a"},
        )
        separate_actor = client.post(
            "/invocations",
            json={"prompt": "separate-actor", "actor_id": "actor-b"},
            headers={SESSION_HEADER: "session-a"},
        )
        separate_session = client.post(
            "/invocations",
            json={"prompt": "separate-session", "actor_id": "actor-a"},
            headers={SESSION_HEADER: "session-b"},
        )

    responses = [first, second, separate_actor, separate_session]
    for response in responses:
        events = _events(response)
        assert response.status_code == 200
        assert events == [
            {"type": "text_delta", "delta": "回"},
            {"type": "text_delta", "delta": "答"},
            {"type": "completed"},
        ]
        assert sum(event["type"] == "completed" for event in events) == 1
        assert all(event["type"] != "error" for event in events)

    assert FakeRunner.observed_history == [
        [],
        [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "回答"},
        ],
        [],
        [],
    ]
    assert set(memory.events) == {
        ("memory", "actor-a", "session-a"),
        ("memory", "actor-b", "session-a"),
        ("memory", "actor-a", "session-b"),
    }
    assert len(memory.events[("memory", "actor-a", "session-a")]) == 2
    assert len(memory.events[("memory", "actor-b", "session-a")]) == 1
    assert len(memory.events[("memory", "actor-a", "session-b")]) == 1

    # 本番serviceとMemory fakeを通し、commit完了後だけcompletedが終端になる対応を固定する。
    assert [session.lifecycle for session in session_factory.sessions] == [
        ["commit_attempt", "commit"],
        ["commit_attempt", "commit"],
        ["commit_attempt", "commit"],
        ["commit_attempt", "commit"],
    ]
    assert all(server.calls == ["connect", "list", "cleanup"] for server in mcp_factory.servers)
    assert len(agent_factory.calls) == 4
    assert all(
        model is MODEL and servers == [mcp_factory.servers[index]] and available
        for index, (model, servers, available) in enumerate(agent_factory.calls)
    )


def test_stream_and_memory_failures_emit_only_error_and_roll_back() -> None:
    memory = FakeMemoryDataClient()
    app, session_factory, mcp_factory, _ = _app(memory)
    FakeRunner.observed_history = []
    FakeRunner.fail = True

    with TestClient(app) as client:
        model_failure = client.post(
            "/invocations",
            json={"prompt": "fail", "actor_id": "actor"},
            headers={SESSION_HEADER: "session"},
        )
        FakeRunner.fail = False
        memory.create_failure = True
        memory_failure = client.post(
            "/invocations",
            json={"prompt": "fail-memory", "actor_id": "actor"},
            headers={SESSION_HEADER: "session"},
        )

    for response in (model_failure, memory_failure):
        events = _events(response)
        assert response.status_code == 200
        assert events[-1] == {"type": "error", "message": "処理中にエラーが発生しました。"}
        assert sum(event["type"] == "error" for event in events) == 1
        assert all(event["type"] != "completed" for event in events)
        assert "secret" not in response.text

    # stream失敗はcommitせずrollbackし、commit失敗もrollback後にだけerror終端へ到達する。
    assert session_factory.sessions[0].lifecycle == ["rollback"]
    assert session_factory.sessions[1].lifecycle == ["commit_attempt", "rollback"]
    assert memory.events.get(("memory", "actor", "session"), []) == []
    assert all(server.calls == ["connect", "list", "cleanup"] for server in mcp_factory.servers)
