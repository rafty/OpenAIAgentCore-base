"""Runtime entrypointの依存ライフサイクルとHTTP／SSE境界を確認するテスト。"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from agents import Model
from openai.types.responses import ResponseTextDeltaEvent
from starlette.testclient import TestClient

from agent_app.config import AppConfig, GatewayConfig
from agent_app.contracts import (
    BAD_REQUEST_MESSAGE,
    SERVER_ERROR_MESSAGE,
    STREAM_ERROR_MESSAGE,
    InvocationInput,
)
from agent_app.runtime import create_runtime_app
from agent_app.service import stream_agent_response


SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"
CONFIG = AppConfig(
    aws_region="us-east-1",
    model_id="openai.gpt-5.5",
    memory_id="memory-id",
    tracing_disabled="1",
    weather_gateway=GatewayConfig(
        url=(
            "https://gateway-id.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
        ),
        region="us-east-1",
        target_name="WeatherTimeMock",
    ),
    knowledge_gateway=GatewayConfig(
        url=(
            "https://knowledge-id.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
        ),
        region="us-east-1",
        target_name="KnowledgeRetrieve",
    ),
)


def _sse_events(response: Any) -> list[dict[str, Any]]:
    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


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


class AsyncRendezvous:
    """2つのrequestが同時にtools/listへ到達するまで双方を待機させる。"""

    def __init__(self) -> None:
        self.arrivals = 0
        self._release: asyncio.Event | None = None

    async def wait(self) -> None:
        if self._release is None:
            self._release = asyncio.Event()
        self.arrivals += 1
        if self.arrivals == 2:
            self._release.set()
        await asyncio.wait_for(self._release.wait(), timeout=2)


class FakeMCP:
    """requestごとのMCP接続とtools/list／cleanupを記録する。"""

    def __init__(
        self,
        request_id: str,
        kind: str,
        events: list[tuple[str, str]],
        *,
        fail_list: bool = False,
        rendezvous: AsyncRendezvous | None = None,
    ) -> None:
        self.request_id = request_id
        self.kind = kind
        self.events = events
        self.fail_list = fail_list
        self.rendezvous = rendezvous
        self.connects = 0
        self.lists = 0
        self.cleanups = 0

    async def connect(self) -> None:
        self.connects += 1
        self.events.append((f"{self.kind}.connect", self.request_id))

    async def list_tools(self) -> list[object]:
        self.lists += 1
        self.events.append((f"{self.kind}.list", self.request_id))
        if self.rendezvous is not None:
            await self.rendezvous.wait()
        if self.fail_list:
            raise RuntimeError("sentinel-private-list-failure")
        return [object(), object()]

    async def cleanup(self) -> None:
        self.cleanups += 1
        self.events.append((f"{self.kind}.cleanup", self.request_id))


class FakeSession:
    """HTTP入力から生成されたrequest固有Sessionの確定状態を保持する。"""

    def __init__(
        self,
        invocation: InvocationInput,
        events: list[tuple[str, str]],
    ) -> None:
        self.invocation = invocation
        self.events = events
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1
        self.events.append(("commit", self.invocation.session_id))

    async def rollback(self) -> None:
        self.rollbacks += 1
        self.events.append(("rollback", self.invocation.session_id))


class FakeResult:
    def __init__(self, delta: str) -> None:
        self.delta = delta

    async def stream_events(self):
        yield _delta(self.delta)


class FakeRunner:
    """実Modelを呼ばず、requestとAgentの対応を記録して固定deltaを返す。"""

    def __init__(
        self,
        events: list[tuple[str, str]],
        *,
        response_text: str | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.events = events
        self.response_text = response_text
        self.error = error
        self.calls: list[tuple[object, str, FakeSession]] = []

    def run_streamed(
        self,
        starting_agent: object,
        **kwargs: Any,
    ) -> FakeResult:
        prompt = kwargs["input"]
        session = kwargs["session"]
        self.calls.append((starting_agent, prompt, session))
        self.events.append(("run", starting_agent.request_id))
        if self.error is not None:
            raise self.error
        return FakeResult(self.response_text or f"応答:{prompt}")


class RuntimeHarness:
    """Runtimeへ全factoryを注入し、request単位の生成物を観測する。"""

    def __init__(
        self,
        *,
        fail_list: bool = False,
        rendezvous: AsyncRendezvous | None = None,
        response_text: str | None = None,
        runner_error: BaseException | None = None,
    ) -> None:
        self.fail_list = fail_list
        self.rendezvous = rendezvous
        self.events: list[tuple[str, str]] = []
        self.model = cast(Model, object())
        self.model_calls: list[AppConfig] = []
        self.stream_models: list[Model] = []
        self.sessions: list[FakeSession] = []
        self.weather_servers: list[FakeMCP] = []
        self.knowledge_servers: list[FakeMCP] = []
        self.agent_calls: list[
            tuple[
                Model,
                list[FakeMCP],
                bool,
                list[FakeMCP],
                bool,
                object,
            ]
        ] = []
        self.runner = FakeRunner(
            self.events,
            response_text=response_text,
            error=runner_error,
        )

    def model_factory(self, config: AppConfig) -> Model:
        self.events.append(("model", "process"))
        self.model_calls.append(config)
        return self.model

    def session_factory(
        self,
        config: AppConfig,
        invocation: InvocationInput,
    ) -> FakeSession:
        assert config is CONFIG
        self.events.append(("session", invocation.session_id))
        session = FakeSession(invocation, self.events)
        self.sessions.append(session)
        return session

    def weather_mcp_server_factory(self, config: AppConfig) -> FakeMCP:
        assert config is CONFIG
        request_id = f"request-{len(self.weather_servers) + 1}"
        self.events.append(("weather.factory", request_id))
        server = FakeMCP(
            request_id,
            "weather",
            self.events,
            fail_list=self.fail_list,
            rendezvous=self.rendezvous,
        )
        self.weather_servers.append(server)
        return server

    def knowledge_mcp_server_factory(self, config: AppConfig) -> FakeMCP:
        assert config is CONFIG
        request_id = f"request-{len(self.knowledge_servers) + 1}"
        self.events.append(("knowledge.factory", request_id))
        server = FakeMCP(request_id, "knowledge", self.events)
        self.knowledge_servers.append(server)
        return server

    def agent_factory(
        self,
        model: Model,
        weather_servers: list[FakeMCP],
        weather_available: bool,
        knowledge_servers: list[FakeMCP],
        knowledge_available: bool,
    ) -> SimpleNamespace:
        request_id = (
            weather_servers[0].request_id
            if weather_servers
            else knowledge_servers[0].request_id
        )
        self.events.append(("agent", request_id))
        manager = SimpleNamespace(request_id=request_id)
        self.agent_calls.append(
            (
                model,
                list(weather_servers),
                weather_available,
                list(knowledge_servers),
                knowledge_available,
                manager,
            )
        )
        return SimpleNamespace(manager=manager, weather=object(), knowledge=object())

    async def stream_service(self, **kwargs: Any):
        # async generator本体はHTTP層がiteratorを消費した時点で初めて実行される。
        session = kwargs["session"]
        self.events.append(("stream", session.invocation.session_id))
        self.stream_models.append(kwargs["model"])
        async for event in stream_agent_response(**kwargs, runner=self.runner):
            yield event

    def create_app(self):
        return create_runtime_app(
            config=CONFIG,
            model_factory=self.model_factory,
            session_factory=self.session_factory,
            weather_mcp_server_factory=self.weather_mcp_server_factory,
            knowledge_mcp_server_factory=self.knowledge_mcp_server_factory,
            agent_factory=self.agent_factory,
            stream_service=self.stream_service,
        )


def test_invalid_payload_returns_safe_4xx_before_any_dependency() -> None:
    calls: list[str] = []

    def should_not_run(*args: Any, **kwargs: Any) -> Any:
        # body検証より後段の依存へ到達した場合、stream開始前境界の回帰として失敗させる。
        calls.append("dependency")
        raise AssertionError("sentinel-private-dependency")

    async def should_not_stream(**kwargs: Any):
        calls.append("stream")
        yield {"type": "completed"}

    app = create_runtime_app(
        config_loader=should_not_run,
        model_factory=should_not_run,
        session_factory=should_not_run,
        weather_mcp_server_factory=should_not_run,
        knowledge_mcp_server_factory=should_not_run,
        agent_factory=should_not_run,
        stream_service=should_not_stream,
    )
    with TestClient(app) as client:
        response = client.post(
            "/invocations",
            json={"prompt": "", "actor_id": "actor"},
            headers={SESSION_HEADER: "session"},
        )

    assert response.status_code == 400
    assert response.json() == {"error": BAD_REQUEST_MESSAGE}
    assert "sentinel-private" not in response.text
    assert calls == []


@pytest.mark.parametrize(
    "failure_stage",
    ["runtime-session", "config", "model", "session"],
)
def test_pre_stream_dependency_failure_returns_only_safe_5xx(
    failure_stage: str,
) -> None:
    calls: list[str] = []
    private_value = f"sentinel-private-{failure_stage}"
    model = cast(Model, object())

    def config_loader() -> AppConfig:
        calls.append("config")
        if failure_stage == "config":
            raise RuntimeError(private_value)
        return CONFIG

    def model_factory(config: AppConfig) -> Model:
        calls.append("model")
        if failure_stage == "model":
            raise RuntimeError(private_value)
        return model

    def session_factory(config: AppConfig, invocation: InvocationInput) -> object:
        calls.append("session")
        if failure_stage == "session":
            raise RuntimeError(private_value)
        return object()

    async def should_not_stream(**kwargs: Any):
        calls.append("stream")
        yield {"type": "completed"}

    app = create_runtime_app(
        config=None if failure_stage == "config" else CONFIG,
        config_loader=config_loader,
        model_factory=model_factory,
        session_factory=session_factory,
        stream_service=should_not_stream,
    )
    headers = {} if failure_stage == "runtime-session" else {SESSION_HEADER: "session"}
    with TestClient(app) as client:
        response = client.post(
            "/invocations",
            json={"prompt": "質問", "actor_id": "actor"},
            headers=headers,
        )

    expected_calls = {
        "runtime-session": [],
        "config": ["config"],
        "model": ["model"],
        "session": ["model", "session"],
    }
    assert response.status_code == 500
    assert response.json() == {"error": SERVER_ERROR_MESSAGE}
    assert private_value not in response.text
    assert calls == expected_calls[failure_stage]


def test_valid_requests_reuse_model_and_create_mcp_agents_per_request() -> None:
    harness = RuntimeHarness()
    app = harness.create_app()

    with TestClient(app) as client:
        first = client.post(
            "/invocations",
            json={
                "prompt": "天気",
                "actor_id": "actor-1",
                "runtimeSessionId": "payload-session-must-not-be-used",
            },
            headers={SESSION_HEADER: "session-1"},
        )
        second = client.post(
            "/invocations",
            json={"prompt": "時刻", "actor_id": "actor-2"},
            headers={SESSION_HEADER: "session-2"},
        )

    assert first.status_code == second.status_code == 200
    assert first.headers["content-type"].startswith("text/event-stream")
    assert _sse_events(first) == [
        {"type": "text_delta", "delta": "応答:天気"},
        {"type": "completed"},
    ]
    assert _sse_events(second) == [
        {"type": "text_delta", "delta": "応答:時刻"},
        {"type": "completed"},
    ]

    assert harness.model_calls == [CONFIG]
    assert harness.stream_models == [harness.model, harness.model]
    assert len(harness.weather_servers) == 2
    assert len(harness.knowledge_servers) == 2
    assert harness.weather_servers[0] is not harness.weather_servers[1]
    assert harness.knowledge_servers[0] is not harness.knowledge_servers[1]
    assert len(harness.agent_calls) == 2
    assert harness.agent_calls[0][:5] == (
        harness.model,
        [harness.weather_servers[0]],
        True,
        [harness.knowledge_servers[0]],
        True,
    )
    assert harness.agent_calls[1][:5] == (
        harness.model,
        [harness.weather_servers[1]],
        True,
        [harness.knowledge_servers[1]],
        True,
    )
    assert harness.agent_calls[0][5] is not harness.agent_calls[1][5]
    assert [session.invocation for session in harness.sessions] == [
        InvocationInput(prompt="天気", actor_id="actor-1", session_id="session-1"),
        InvocationInput(prompt="時刻", actor_id="actor-2", session_id="session-2"),
    ]
    assert [(session.commits, session.rollbacks) for session in harness.sessions] == [
        (1, 0),
        (1, 0),
    ]

    for index, session_id in enumerate(("session-1", "session-2"), start=1):
        request_id = f"request-{index}"
        # request前処理でSessionを作り、iterator消費後にMCP→list→Agentの順で生成する。
        assert harness.events.index(("session", session_id)) < harness.events.index(
            ("stream", session_id)
        )
        assert harness.events.index(("weather.list", request_id)) < harness.events.index(
            ("knowledge.list", request_id)
        ) < harness.events.index(
            ("agent", request_id)
        )
    assert all(
        (server.connects, server.lists, server.cleanups) == (1, 1, 1)
        for server in harness.weather_servers + harness.knowledge_servers
    )


def test_list_failure_calls_agent_factory_with_unavailable_state_after_cleanup() -> None:
    harness = RuntimeHarness(fail_list=True, response_text="取得できません。")
    app = harness.create_app()

    with TestClient(app) as client:
        response = client.post(
            "/invocations",
            json={"prompt": "天気", "actor_id": "actor"},
            headers={SESSION_HEADER: "session"},
        )

    assert response.status_code == 200
    assert _sse_events(response) == [
        {"type": "text_delta", "delta": "取得できません。"},
        {"type": "completed"},
    ]
    assert harness.agent_calls[0][:5] == (
        harness.model,
        [],
        False,
        [harness.knowledge_servers[0]],
        True,
    )
    assert harness.events.index(("weather.list", "request-1")) < harness.events.index(
        ("weather.cleanup", "request-1")
    ) < harness.events.index(("agent", "request-1"))
    assert harness.sessions[0].commits == 1
    assert harness.sessions[0].rollbacks == 0
    assert "sentinel-private-list-failure" not in response.text


def test_stream_failure_returns_safe_sse_and_rolls_back() -> None:
    private_value = "sentinel-private-runner-failure"
    harness = RuntimeHarness(runner_error=RuntimeError(private_value))
    app = harness.create_app()

    with TestClient(app) as client:
        response = client.post(
            "/invocations",
            json={"prompt": "天気", "actor_id": "actor"},
            headers={SESSION_HEADER: "session"},
        )

    assert response.status_code == 200
    assert _sse_events(response) == [
        {"type": "error", "message": STREAM_ERROR_MESSAGE}
    ]
    assert private_value not in response.text
    assert harness.weather_servers[0].cleanups == 1
    assert harness.knowledge_servers[0].cleanups == 1
    assert (harness.sessions[0].commits, harness.sessions[0].rollbacks) == (0, 1)


def test_concurrent_requests_share_only_cached_model() -> None:
    rendezvous = AsyncRendezvous()
    harness = RuntimeHarness(rendezvous=rendezvous)
    app = harness.create_app()

    async def invoke_concurrently() -> list[httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return list(
                await asyncio.gather(
                    client.post(
                        "/invocations",
                        json={"prompt": "天気", "actor_id": "actor-1"},
                        headers={SESSION_HEADER: "parallel-1"},
                    ),
                    client.post(
                        "/invocations",
                        json={"prompt": "時刻", "actor_id": "actor-2"},
                        headers={SESSION_HEADER: "parallel-2"},
                    ),
                )
            )

    responses = asyncio.run(invoke_concurrently())

    assert rendezvous.arrivals == 2
    assert [response.status_code for response in responses] == [200, 200]
    assert [_sse_events(response) for response in responses] == [
        [
            {"type": "text_delta", "delta": "応答:天気"},
            {"type": "completed"},
        ],
        [
            {"type": "text_delta", "delta": "応答:時刻"},
            {"type": "completed"},
        ],
    ]
    assert harness.model_calls == [CONFIG]
    assert harness.stream_models == [harness.model, harness.model]
    assert len({id(server) for server in harness.weather_servers}) == 2
    assert len({id(server) for server in harness.knowledge_servers}) == 2
    assert len({id(call[5]) for call in harness.agent_calls}) == 2
    assert len({id(session) for session in harness.sessions}) == 2
    assert {session.invocation.session_id for session in harness.sessions} == {
        "parallel-1",
        "parallel-2",
    }
    assert all(
        call[0] is harness.model and call[2] and call[4]
        for call in harness.agent_calls
    )
    assert all(len(call[1]) == len(call[3]) == 1 for call in harness.agent_calls)
    assert all(
        server.cleanups == 1
        for server in harness.weather_servers + harness.knowledge_servers
    )
    assert all(session.commits == 1 for session in harness.sessions)
