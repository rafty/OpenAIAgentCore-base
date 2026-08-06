"""AgentCore Memory Sessionのevent fold、分離、確定制御を確認するテスト。"""

import asyncio
import threading
import time
from datetime import datetime, timezone

import pytest

from agent_app.session import (
    AgentCoreMemorySession,
    SessionDataError,
    decode_envelope,
    encode_envelope,
    fold_envelopes,
)


class FakeMemoryClient:
    """ページング、失敗、遅延、scope別eventを再現する同期Memory代替。"""

    def __init__(self, *, page_size: int = 100, create_failures: int = 0, delay: float = 0) -> None:
        self.page_size = page_size
        self.create_failures = create_failures
        self.delay = delay
        self.events: dict[tuple[str, str, str], list[dict]] = {}
        self.list_calls: list[dict] = []
        self.create_calls: list[dict] = []
        self.worker_threads: list[int] = []

    def list_events(self, **kwargs):
        self.worker_threads.append(threading.get_ident())
        self.list_calls.append(kwargs)
        if self.delay:
            time.sleep(self.delay)
        key = (kwargs["memoryId"], kwargs["actorId"], kwargs["sessionId"])
        values = self.events.get(key, [])
        start = int(kwargs.get("nextToken", "0"))
        end = min(start + self.page_size, len(values))
        response = {"events": values[start:end]}
        if end < len(values):
            response["nextToken"] = str(end)
        return response

    def create_event(self, **kwargs):
        self.worker_threads.append(threading.get_ident())
        self.create_calls.append(kwargs)
        if self.create_failures:
            self.create_failures -= 1
            raise RuntimeError("fake memory failure")
        key = (kwargs["memoryId"], kwargs["actorId"], kwargs["sessionId"])
        event = {
            "memoryId": kwargs["memoryId"],
            "actorId": kwargs["actorId"],
            "sessionId": kwargs["sessionId"],
            "eventId": f"event-{len(self.events.setdefault(key, [])):04d}",
            "eventTimestamp": kwargs["eventTimestamp"],
            "payload": kwargs["payload"],
        }
        self.events[key].append(event)
        return {"event": event}


def _session(client: FakeMemoryClient, *, actor: str = "actor", session: str = "session"):
    return AgentCoreMemorySession(
        memory_id="memory",
        actor_id=actor,
        session_id=session,
        region="us-east-2",
        client=client,
    )


def _run(coro):
    return asyncio.run(coro)


def test_envelope_round_trip_and_logical_operations() -> None:
    items = [
        {"role": "user", "content": "質問"},
        {"role": "assistant", "content": [{"type": "output_text", "text": "回答"}]},
    ]
    append = encode_envelope("append", items)
    assert decode_envelope(append) == append
    assert decode_envelope(str.encode(__import__("json").dumps(append))) == append
    assert fold_envelopes(
        [append, encode_envelope("pop"), encode_envelope("append", [items[1]])]
    ) == items
    assert fold_envelopes([append, encode_envelope("clear")]) == []


@pytest.mark.parametrize(
    "blob",
    [
        {"schema_version": 999, "operation": "append", "items": []},
        {"schema_version": 1, "operation": "unknown", "items": []},
        {"schema_version": 1, "operation": "append", "items": "invalid"},
        b"not-json",
    ],
)
def test_corrupt_or_unknown_envelope_fails_closed(blob) -> None:
    with pytest.raises(SessionDataError):
        decode_envelope(blob)


def test_paging_stable_order_limit_pop_and_clear() -> None:
    client = FakeMemoryClient(page_size=1)
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    key = ("memory", "actor", "session")
    # 同一時刻のeventを逆順で返し、event IDによる安定sortを検証する。
    client.events[key] = [
        {
            "memoryId": "memory",
            "actorId": "actor",
            "sessionId": "session",
            "eventId": "b",
            "eventTimestamp": timestamp,
            "payload": [{"blob": encode_envelope("append", [{"id": "second"}])}],
        },
        {
            "memoryId": "memory",
            "actorId": "actor",
            "sessionId": "session",
            "eventId": "a",
            "eventTimestamp": timestamp,
            "payload": [{"blob": encode_envelope("append", [{"id": "first"}])}],
        },
    ]
    session = _session(client)

    assert _run(session.get_items(limit=1)) == [{"id": "second"}]
    assert len(client.list_calls) == 2
    assert _run(session.pop_item()) == {"id": "second"}
    assert _run(session.get_items()) == [{"id": "first"}]
    _run(session.clear_session())
    assert _run(session.get_items()) == []


def test_commit_rollback_and_client_token_retry() -> None:
    client = FakeMemoryClient(create_failures=1)
    session = _session(client)
    _run(session.add_items([{"role": "user", "content": "one"}]))

    # 最初の書込みだけ失敗させ、再試行時もclientTokenが変わらないことを確認する。
    with pytest.raises(RuntimeError):
        _run(session.commit())
    first_token = client.create_calls[0]["clientToken"]
    _run(session.commit())
    assert client.create_calls[1]["clientToken"] == first_token
    # 実AgentCore MemoryでもJSONとして往復できるよう、blobはJSON文字列で渡す。
    stored_blob = client.create_calls[1]["payload"][0]["blob"]
    assert isinstance(stored_blob, str)
    assert decode_envelope(stored_blob)["items"] == [
        {"role": "user", "content": "one"}
    ]
    assert _run(session.get_items()) == [{"role": "user", "content": "one"}]

    _run(session.add_items([{"role": "assistant", "content": "incomplete"}]))
    _run(session.rollback())
    assert _run(session.get_items()) == [{"role": "user", "content": "one"}]


def test_actor_and_session_histories_are_isolated() -> None:
    client = FakeMemoryClient()
    first = _session(client, actor="actor-a", session="session-a")
    other_actor = _session(client, actor="actor-b", session="session-a")
    other_session = _session(client, actor="actor-a", session="session-b")

    _run(first.add_items([{"id": "only-first"}]))
    _run(first.commit())

    assert _run(first.get_items()) == [{"id": "only-first"}]
    assert _run(other_actor.get_items()) == []
    assert _run(other_session.get_items()) == []
    assert {
        (call["actorId"], call["sessionId"]) for call in client.list_calls
    } >= {
        ("actor-a", "session-a"),
        ("actor-b", "session-a"),
        ("actor-a", "session-b"),
    }


def test_out_of_scope_event_fails_closed() -> None:
    client = FakeMemoryClient()
    key = ("memory", "actor", "session")
    client.events[key] = [
        {
            "memoryId": "memory",
            "actorId": "other",
            "sessionId": "session",
            "eventId": "event",
            "eventTimestamp": datetime.now(timezone.utc),
            "payload": [{"blob": encode_envelope("append", [{"id": "leak"}])}],
        }
    ]
    with pytest.raises(SessionDataError):
        _run(_session(client).get_items())


def test_sync_memory_io_runs_outside_event_loop_thread() -> None:
    client = FakeMemoryClient(delay=0.01)
    session = _session(client)
    loop_thread = threading.get_ident()
    _run(session.get_items())
    _run(session.add_items([{"id": "value"}]))
    _run(session.commit())
    assert client.worker_threads
    assert all(worker != loop_thread for worker in client.worker_threads)
