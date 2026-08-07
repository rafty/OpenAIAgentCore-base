"""MCP、Runner、Memoryの確定順序と失敗境界を確認するテスト。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any

import pytest
from agents.stream_events import RawResponsesStreamEvent
from openai.types.responses import ResponseTextDeltaEvent

import agent_app.service as service_module
from agent_app.config import AppConfig
from agent_app.service import stream_agent_response


CONFIG = AppConfig(
    aws_region="us-east-2",
    model_id="openai.gpt-5.5",
    memory_id="memory-id",
    tracing_disabled="1",
    gateway_url=(
        "https://gateway-id.gateway.bedrock-agentcore.us-east-2.amazonaws.com/mcp"
    ),
    gateway_target_name="WeatherTimeMock",
)


def _delta(value: str, sequence: int = 1) -> RawResponsesStreamEvent:
    return RawResponsesStreamEvent(
        data=ResponseTextDeltaEvent(
            content_index=0,
            delta=value,
            item_id="message",
            logprobs=[],
            output_index=0,
            sequence_number=sequence,
            type="response.output_text.delta",
        )
    )


async def _hang_forever() -> None:
    """timeoutがなければテストも完了しないoperationを再現する。"""

    await asyncio.Event().wait()


class FakeMCP:
    """各MCP operationの順序、回数、失敗と無期限待機を記録する。"""

    def __init__(
        self,
        events: list[str],
        *,
        fail: str | None = None,
        hang: str | None = None,
    ) -> None:
        self.events = events
        self.fail = fail
        self.hang = hang
        self.counts = {name: 0 for name in ("connect", "list", "call", "cleanup")}

    async def _operation(self, name: str) -> None:
        self.events.append(name)
        self.counts[name] += 1
        if self.hang == name:
            await _hang_forever()
        if self.fail == name:
            raise RuntimeError(f"sentinel-{name}-failure")

    async def connect(self) -> None:
        await self._operation("connect")

    async def list_tools(self) -> list[object]:
        await self._operation("list")
        return [object(), object()]

    async def call_tool(self) -> dict[str, str]:
        # adapterがtransport／Lambda失敗をモデル可視の固定結果へ変換した状態を再現する。
        await self._operation("call")
        return {"error": "現在、天気・時刻情報を取得できません。"}

    async def cleanup(self) -> None:
        await self._operation("cleanup")


class FakeSession:
    """Memory確定・破棄の順序と障害を観測するSession代替。"""

    def __init__(
        self,
        events: list[str],
        *,
        commit_error: BaseException | None = None,
        rollback_error: BaseException | None = None,
    ) -> None:
        self.events = events
        self.commit_error = commit_error
        self.rollback_error = rollback_error
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.events.append("commit")
        self.commits += 1
        if self.commit_error:
            raise self.commit_error

    async def rollback(self) -> None:
        self.events.append("rollback")
        self.rollbacks += 1
        if self.rollback_error:
            raise self.rollback_error


class FakeResult:
    """任意のstream列、実行前処理、末尾障害またはキャンセルを再現する。"""

    def __init__(
        self,
        events: list[Any] = (),
        *,
        before_stream: Callable[[], Awaitable[Any]] | None = None,
        error: BaseException | None = None,
        hang: bool = False,
    ) -> None:
        self.output_events = list(events)
        self.before_stream = before_stream
        self.error = error
        self.hang = hang

    async def stream_events(self):
        if self.before_stream is not None:
            await self.before_stream()
        for event in self.output_events:
            yield event
        if self.hang:
            await _hang_forever()
        if self.error:
            raise self.error


class FakeRunner:
    """Agent実行開始とstream内障害を独立して注入できるRunner代替。"""

    def __init__(
        self,
        events: list[str],
        result: FakeResult,
        *,
        run_error: BaseException | None = None,
    ) -> None:
        self.events = events
        self.result = result
        self.run_error = run_error

    def run_streamed(self, starting_agent: object, **kwargs: Any) -> FakeResult:
        self.events.append("run")
        assert kwargs["input"] == "sentinel-prompt"
        assert kwargs["session"] is not None
        if self.run_error:
            raise self.run_error
        return self.result


class FakeAgentFactory:
    """tools/list後に確定したGateway利用可否とserver所有境界を記録する。"""

    def __init__(self, events: list[str], *, error: BaseException | None = None) -> None:
        self.events = events
        self.error = error
        self.calls: list[tuple[object, list[object], bool]] = []
        self.manager = object()

    def __call__(
        self,
        model: object,
        servers: list[object],
        gateway_available: bool,
    ) -> SimpleNamespace:
        self.events.append("agent")
        self.calls.append((model, list(servers), gateway_available))
        if self.error:
            raise self.error
        return SimpleNamespace(manager=self.manager, weather=object())


def _collect(
    *,
    events: list[str],
    session: FakeSession,
    mcp: FakeMCP | None,
    result: FakeResult | None = None,
    mcp_factory_error: BaseException | None = None,
    agent_error: BaseException | None = None,
    run_error: BaseException | None = None,
) -> tuple[list[dict[str, Any]], FakeAgentFactory]:
    agent_factory = FakeAgentFactory(events, error=agent_error)
    runner = FakeRunner(events, result or FakeResult(), run_error=run_error)

    def mcp_factory(config: AppConfig) -> FakeMCP:
        events.append("mcp_factory")
        assert config is CONFIG
        if mcp_factory_error:
            raise mcp_factory_error
        assert mcp is not None
        return mcp

    async def run() -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        async for event in stream_agent_response(
            config=CONFIG,
            model="shared-model",  # type: ignore[arg-type]
            prompt="sentinel-prompt",
            session=session,  # type: ignore[arg-type]
            mcp_server_factory=mcp_factory,
            agent_factory=agent_factory,  # type: ignore[arg-type]
            runner=runner,
        ):
            output.append(event)
            if event["type"] in {"completed", "error"}:
                events.append(event["type"])
        return output

    return asyncio.run(run()), agent_factory


def test_success_orders_connect_list_agent_run_cleanup_commit_completed() -> None:
    events: list[str] = []
    mcp = FakeMCP(events)
    session = FakeSession(events)
    output, agent_factory = _collect(
        events=events,
        session=session,
        mcp=mcp,
        result=FakeResult(
            [_delta("A", 1), SimpleNamespace(type="run_item_stream_event"), _delta("B", 2)]
        ),
    )

    assert output == [
        {"type": "text_delta", "delta": "A"},
        {"type": "text_delta", "delta": "B"},
        {"type": "completed"},
    ]
    assert events == [
        "mcp_factory",
        "connect",
        "list",
        "agent",
        "run",
        "cleanup",
        "commit",
        "completed",
    ]
    assert agent_factory.calls == [("shared-model", [mcp], True)]
    assert mcp.counts == {"connect": 1, "list": 1, "call": 0, "cleanup": 1}
    assert (session.commits, session.rollbacks) == (1, 0)


def test_factory_failure_uses_unavailable_agents_and_commits() -> None:
    events: list[str] = []
    session = FakeSession(events)
    output, agent_factory = _collect(
        events=events,
        session=session,
        mcp=None,
        mcp_factory_error=RuntimeError("sentinel-factory"),
        result=FakeResult([_delta("取得できません。")]),
    )

    assert output[-1] == {"type": "completed"}
    assert agent_factory.calls == [("shared-model", [], False)]
    assert events == [
        "mcp_factory",
        "agent",
        "run",
        "commit",
        "completed",
    ]
    assert (session.commits, session.rollbacks) == (1, 0)


@pytest.mark.parametrize("stage", ["connect", "list"])
def test_connect_or_list_failure_cleans_up_then_commits_unavailable_answer(
    stage: str,
) -> None:
    events: list[str] = []
    mcp = FakeMCP(events, fail=stage)
    session = FakeSession(events)
    output, agent_factory = _collect(
        events=events,
        session=session,
        mcp=mcp,
        result=FakeResult([_delta("取得できません。")]),
    )

    assert output == [
        {"type": "text_delta", "delta": "取得できません。"},
        {"type": "completed"},
    ]
    assert agent_factory.calls == [("shared-model", [], False)]
    assert events.index("cleanup") < events.index("agent") < events.index("commit")
    assert mcp.counts["cleanup"] == 1
    assert (session.commits, session.rollbacks) == (1, 0)


@pytest.mark.parametrize("stage", ["connect", "list"])
def test_connect_or_list_indefinite_wait_times_out_and_falls_back(
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    monkeypatch.setattr(service_module, "MCP_TRANSPORT_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(service_module, "MCP_CLIENT_SESSION_TIMEOUT_SECONDS", 0.01)
    events: list[str] = []
    mcp = FakeMCP(events, hang=stage)
    session = FakeSession(events)

    output, agent_factory = _collect(
        events=events,
        session=session,
        mcp=mcp,
        result=FakeResult([_delta("取得できません。")]),
    )

    assert output[-1] == {"type": "completed"}
    assert agent_factory.calls == [("shared-model", [], False)]
    assert events.index("cleanup") < events.index("commit") < events.index("completed")
    assert (session.commits, session.rollbacks) == (1, 0)


def test_normalized_tool_failure_is_a_committed_unavailable_turn() -> None:
    events: list[str] = []
    mcp = FakeMCP(events)
    session = FakeSession(events)
    output, _ = _collect(
        events=events,
        session=session,
        mcp=mcp,
        result=FakeResult(
            [_delta("現在、天気・時刻情報を取得できません。")],
            before_stream=mcp.call_tool,
        ),
    )

    assert output[-1] == {"type": "completed"}
    assert events.index("call") < events.index("cleanup") < events.index("commit")
    assert mcp.counts["call"] == 1
    assert (session.commits, session.rollbacks) == (1, 0)


@pytest.mark.parametrize("cleanup_mode", ["failure", "timeout"])
def test_cleanup_failure_or_timeout_rolls_back_without_completed(
    monkeypatch: pytest.MonkeyPatch,
    cleanup_mode: str,
) -> None:
    monkeypatch.setattr(service_module, "MCP_CLEANUP_TIMEOUT_SECONDS", 0.01)
    events: list[str] = []
    mcp = FakeMCP(
        events,
        fail="cleanup" if cleanup_mode == "failure" else None,
        hang="cleanup" if cleanup_mode == "timeout" else None,
    )
    session = FakeSession(events)
    output, _ = _collect(
        events=events,
        session=session,
        mcp=mcp,
        result=FakeResult([_delta("partial")]),
    )

    assert output[-1] == {"type": "error", "message": "処理中にエラーが発生しました。"}
    assert all(event["type"] != "completed" for event in output)
    assert events.index("cleanup") < events.index("rollback") < events.index("error")
    assert mcp.counts["cleanup"] == 1
    assert (session.commits, session.rollbacks) == (0, 1)


@pytest.mark.parametrize("stage", ["agent", "runner", "stream", "commit"])
def test_all_post_connect_fatal_failures_cleanup_then_rollback(stage: str) -> None:
    events: list[str] = []
    mcp = FakeMCP(events)
    session = FakeSession(
        events,
        commit_error=RuntimeError("sentinel-memory") if stage == "commit" else None,
    )
    output, _ = _collect(
        events=events,
        session=session,
        mcp=mcp,
        agent_error=RuntimeError("sentinel-agent") if stage == "agent" else None,
        run_error=RuntimeError("sentinel-runner") if stage == "runner" else None,
        result=FakeResult(
            [_delta("partial")],
            error=RuntimeError("sentinel-stream") if stage == "stream" else None,
        ),
    )

    assert output[-1]["type"] == "error"
    assert all(event["type"] != "completed" for event in output)
    assert events.index("cleanup") < events.index("rollback") < events.index("error")
    assert mcp.counts["cleanup"] == 1
    assert (session.commits, session.rollbacks) == (
        (1, 1) if stage == "commit" else (0, 1)
    )


def test_cleanup_failure_after_connection_fallback_is_not_recoverable() -> None:
    events: list[str] = []
    mcp = FakeMCP(events, fail="connect")
    original_cleanup = mcp.cleanup

    async def failing_cleanup() -> None:
        await original_cleanup()
        raise RuntimeError("sentinel-cleanup")

    mcp.cleanup = failing_cleanup  # type: ignore[method-assign]
    session = FakeSession(events)
    output, agent_factory = _collect(events=events, session=session, mcp=mcp)

    assert output == [{"type": "error", "message": "処理中にエラーが発生しました。"}]
    assert agent_factory.calls == []
    assert events.index("cleanup") < events.index("rollback")
    assert (session.commits, session.rollbacks) == (0, 1)


def test_fatal_error_and_rollback_failure_emit_only_safe_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    events: list[str] = []
    mcp = FakeMCP(events)
    session = FakeSession(
        events,
        rollback_error=RuntimeError("sentinel-rollback-secret"),
    )
    caplog.set_level(logging.DEBUG)
    output, _ = _collect(
        events=events,
        session=session,
        mcp=mcp,
        run_error=RuntimeError(
            f"sentinel-run-secret {CONFIG.gateway_url} arn:aws:bedrock-agentcore:secret"
        ),
    )

    assert output == [{"type": "error", "message": "処理中にエラーが発生しました。"}]
    combined = f"{output} {caplog.text}"
    assert "sentinel" not in combined
    assert CONFIG.gateway_url not in combined
    assert "arn:" not in combined
    assert (session.commits, session.rollbacks) == (0, 1)


def test_cancellation_preserves_original_error_after_cleanup_and_rollback_failures() -> None:
    events: list[str] = []
    mcp = FakeMCP(events, fail="cleanup")
    session = FakeSession(
        events,
        rollback_error=RuntimeError("sentinel-rollback"),
    )
    agent_factory = FakeAgentFactory(events)
    runner = FakeRunner(
        events,
        FakeResult([_delta("partial")], error=asyncio.CancelledError()),
    )

    async def run() -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        with pytest.raises(asyncio.CancelledError):
            async for event in stream_agent_response(
                config=CONFIG,
                model="shared-model",  # type: ignore[arg-type]
                prompt="sentinel-prompt",
                session=session,  # type: ignore[arg-type]
                mcp_server_factory=lambda _: mcp,
                agent_factory=agent_factory,  # type: ignore[arg-type]
                runner=runner,
            ):
                output.append(event)
        return output

    assert asyncio.run(run()) == [{"type": "text_delta", "delta": "partial"}]
    assert events.index("cleanup") < events.index("rollback")
    assert mcp.counts["cleanup"] == 1
    assert (session.commits, session.rollbacks) == (0, 1)


def test_cancellation_during_cleanup_retries_in_same_task_then_rolls_back() -> None:
    events: list[str] = []
    first_cleanup_started = asyncio.Event()
    cleanup_tasks: list[asyncio.Task[Any] | None] = []

    class CancelDuringCleanupMCP(FakeMCP):
        async def cleanup(self) -> None:
            self.events.append("cleanup")
            self.counts["cleanup"] += 1
            cleanup_tasks.append(asyncio.current_task())
            if self.counts["cleanup"] == 1:
                first_cleanup_started.set()
                try:
                    await _hang_forever()
                except asyncio.CancelledError:
                    self.events.append("cleanup_cancelled")
                    raise
            self.events.append("cleanup_completed")

    mcp = CancelDuringCleanupMCP(events)
    session = FakeSession(events)
    agent_factory = FakeAgentFactory(events)
    runner = FakeRunner(events, FakeResult([_delta("partial")]))
    output: list[dict[str, Any]] = []

    async def collect() -> None:
        async for event in stream_agent_response(
            config=CONFIG,
            model="shared-model",  # type: ignore[arg-type]
            prompt="sentinel-prompt",
            session=session,  # type: ignore[arg-type]
            mcp_server_factory=lambda _: mcp,
            agent_factory=agent_factory,  # type: ignore[arg-type]
            runner=runner,
        ):
            output.append(event)

    async def run() -> None:
        service_task = asyncio.create_task(collect())
        await asyncio.wait_for(first_cleanup_started.wait(), timeout=1)
        service_task.cancel("sentinel-cleanup-cancel")
        with pytest.raises(asyncio.CancelledError, match="sentinel-cleanup-cancel"):
            await service_task

        # MCPのanyio cancel scopeを別taskで閉じないよう、再試行も元の実行taskで行う。
        assert cleanup_tasks == [service_task, service_task]

    asyncio.run(run())

    assert output == [{"type": "text_delta", "delta": "partial"}]
    assert events.index("cleanup_cancelled") < events.index("cleanup_completed")
    assert events.index("cleanup_completed") < events.index("rollback")
    assert mcp.counts["cleanup"] == 2
    assert (session.commits, session.rollbacks) == (0, 1)
