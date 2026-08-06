"""stream消費とSessionのcommit／rollback順序を確認するテスト。"""

import asyncio
from types import SimpleNamespace

import pytest
from agents.stream_events import RawResponsesStreamEvent
from openai.types.responses import ResponseTextDeltaEvent

from agent_app.service import stream_agent_response


def _delta(value: str, sequence: int) -> RawResponsesStreamEvent:
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


class FakeSession:
    """確定・破棄回数とMemory確定失敗を観測するSession代替。"""

    def __init__(self, *, commit_error: Exception | None = None) -> None:
        self.commit_error = commit_error
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1
        if self.commit_error:
            raise self.commit_error

    async def rollback(self) -> None:
        self.rollbacks += 1


class FakeResult:
    """任意のstream event列と末尾例外を生成する実行結果。"""

    def __init__(self, events, error: Exception | None = None) -> None:
        self.events = events
        self.error = error

    async def stream_events(self):
        for event in self.events:
            yield event
        if self.error:
            raise self.error


class FakeRunner:
    """stream serviceへ指定済みFakeResultを返すRunner代替。"""

    result: FakeResult

    @classmethod
    def run_streamed(cls, *args, **kwargs):
        return cls.result


def _collect(session: FakeSession, result: FakeResult) -> list[dict]:
    FakeRunner.result = result

    async def run() -> list[dict]:
        return [
            event
            async for event in stream_agent_response(
                manager_agent=None,
                prompt="質問",
                session=session,
                runner=FakeRunner,
            )
        ]

    return asyncio.run(run())


def test_stream_consumes_all_events_then_commits_and_completes() -> None:
    session = FakeSession()
    events = _collect(
        session,
        FakeResult([_delta("A", 1), SimpleNamespace(type="run_item_stream_event"), _delta("B", 2)]),
    )
    assert events == [
        {"type": "text_delta", "delta": "A"},
        {"type": "text_delta", "delta": "B"},
        {"type": "completed"},
    ]
    assert (session.commits, session.rollbacks) == (1, 0)


@pytest.mark.parametrize("failure", [RuntimeError("model-secret"), ValueError("session-secret")])
def test_failure_rolls_back_and_emits_only_safe_error(failure: Exception) -> None:
    session = FakeSession()
    events = _collect(session, FakeResult([_delta("partial", 1)], failure))
    assert events[-1] == {"type": "error", "message": "処理中にエラーが発生しました。"}
    assert {event["type"] for event in events}.isdisjoint({"completed"})
    assert "secret" not in str(events)
    assert (session.commits, session.rollbacks) == (0, 1)


def test_commit_failure_is_not_completed() -> None:
    session = FakeSession(commit_error=RuntimeError("memory-secret"))
    events = _collect(session, FakeResult([_delta("partial", 1)]))
    assert events[-1]["type"] == "error"
    assert all(event["type"] != "completed" for event in events)
    assert (session.commits, session.rollbacks) == (1, 1)


def test_cancellation_rolls_back_without_additional_event() -> None:
    session = FakeSession()

    class CancelledResult:
        async def stream_events(self):
            yield _delta("partial", 1)
            raise asyncio.CancelledError()

    FakeRunner.result = CancelledResult()

    async def run() -> list[dict]:
        events = []
        with pytest.raises(asyncio.CancelledError):
            async for event in stream_agent_response(
                manager_agent=None,
                prompt="質問",
                session=session,
                runner=FakeRunner,
            ):
                events.append(event)
        return events

    assert asyncio.run(run()) == [{"type": "text_delta", "delta": "partial"}]
    assert (session.commits, session.rollbacks) == (0, 1)
