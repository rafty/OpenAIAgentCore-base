"""HTTP/SSE境界とAgentCore Memory Session連携を通す結合テスト。"""

import json
from datetime import datetime, timezone
from functools import partial

from agents.stream_events import RawResponsesStreamEvent
from openai.types.responses import ResponseTextDeltaEvent
from starlette.testclient import TestClient

from agent_app.config import AppConfig
from agent_app.runtime import create_runtime_app
from agent_app.service import stream_agent_response


SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"
CONFIG = AppConfig("us-east-2", "openai.gpt-5.5", "memory", "1")


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
        self.events: dict[tuple[str, str, str], list[dict]] = {}
        self.create_failure = False
        self.calls: list[tuple[str, dict]] = []

    def list_events(self, **kwargs):
        self.calls.append(("list", kwargs))
        key = (kwargs["memoryId"], kwargs["actorId"], kwargs["sessionId"])
        return {"events": list(self.events.get(key, []))}

    def create_event(self, **kwargs):
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


class FakeRunResult:
    """履歴読込、item追加、複数delta、任意失敗の順序を再現する実行結果。"""

    def __init__(self, session, *, fail: bool, observed_history: list[list[dict]]) -> None:
        self.session = session
        self.fail = fail
        self.observed_history = observed_history

    async def stream_events(self):
        self.observed_history.append(await self.session.get_items())
        await self.session.add_items(
            [
                {"role": "user", "content": "質問"},
                {"role": "assistant", "content": "回答"},
            ]
        )
        yield _delta("回", 1)
        yield _delta("答", 2)
        if self.fail:
            raise RuntimeError("model-internal-secret")


class FakeRunner:
    """本番serviceへFakeRunResultを返すRunner代替。"""

    fail = False
    observed_history: list[list[dict]] = []

    @classmethod
    def run_streamed(cls, starting_agent, **kwargs):
        return FakeRunResult(
            kwargs["session"],
            fail=cls.fail,
            observed_history=cls.observed_history,
        )


def _events(response) -> list[dict]:
    """SSE本文を契約検証しやすいevent配列へ変換する。"""

    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def _app(memory: FakeMemoryDataClient):
    return create_runtime_app(
        config=CONFIG,
        manager_agent=object(),
        memory_client_factory=lambda region: memory,
        stream_service=partial(stream_agent_response, runner=FakeRunner),
    )


def test_http_sse_and_session_history_restore_and_separation() -> None:
    memory = FakeMemoryDataClient()
    FakeRunner.fail = False
    FakeRunner.observed_history = []

    with TestClient(_app(memory)) as client:
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
        separate = client.post(
            "/invocations",
            json={"prompt": "separate", "actor_id": "actor-b"},
            headers={SESSION_HEADER: "session-a"},
        )

    assert _events(first) == [
        {"type": "text_delta", "delta": "回"},
        {"type": "text_delta", "delta": "答"},
        {"type": "completed"},
    ]
    assert len(FakeRunner.observed_history[1]) == 2
    assert FakeRunner.observed_history[2] == []
    assert all(event["type"] != "error" for event in _events(second))
    assert all(event["type"] != "error" for event in _events(separate))


def test_stream_and_memory_failures_are_safe_and_not_committed() -> None:
    memory = FakeMemoryDataClient()
    FakeRunner.observed_history = []
    FakeRunner.fail = True

    with TestClient(_app(memory)) as client:
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
        assert events[-1] == {"type": "error", "message": "処理中にエラーが発生しました。"}
        assert all(event["type"] != "completed" for event in events)
        assert "secret" not in response.text
    assert memory.events.get(("memory", "actor", "session"), []) == []
