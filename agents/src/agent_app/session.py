"""OpenAI Agents SDK SessionをAgentCore Memory短期記憶へ接続する。"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, Protocol, cast

from agents import SessionABC, TResponseInputItem
from bedrock_agentcore.memory import MemoryClient


SCHEMA_VERSION = 1
_OPERATIONS = frozenset({"append", "pop", "clear"})


class SessionDataError(RuntimeError):
    """Memory上の履歴を安全に復元できない場合のfail-closedエラー。"""

    def __init__(self) -> None:
        super().__init__("会話履歴を安全に復元できませんでした。")


class MemoryDataPlaneClient(Protocol):
    def list_events(self, **kwargs: Any) -> dict[str, Any]: ...

    def create_event(self, **kwargs: Any) -> dict[str, Any]: ...


MemoryClientFactory = Callable[[str], MemoryDataPlaneClient]


def create_memory_data_client(region: str) -> MemoryDataPlaneClient:
    """標準AWS認証情報チェーンを使用するMemory data-plane clientを生成する。"""

    return cast(MemoryDataPlaneClient, MemoryClient(region_name=region).gmdp_client)


def encode_envelope(operation: str, items: Sequence[TResponseInputItem] = ()) -> dict[str, Any]:
    """Session操作をUTF-8 JSONへ変換可能なdocumentとして正規化する。"""

    if operation not in _OPERATIONS:
        raise SessionDataError()
    if operation != "append" and items:
        raise SessionDataError()

    envelope = {
        "schema_version": SCHEMA_VERSION,
        "operation": operation,
        "items": list(items),
    }
    try:
        encoded = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        decoded = json.loads(encoded.decode("utf-8"))
    except (TypeError, ValueError, UnicodeError) as exc:
        raise SessionDataError() from exc

    return cast(dict[str, Any], decoded)


def decode_envelope(blob: Any) -> dict[str, Any]:
    """MemoryのJSON document/UTF-8 JSONを検証してSession操作へ戻す。"""

    try:
        if isinstance(blob, bytes):
            value = json.loads(blob.decode("utf-8"))
        elif isinstance(blob, str):
            value = json.loads(blob)
        else:
            # AWS document型をJSON往復し、SDK固有objectを受け入れない。
            value = json.loads(json.dumps(blob, ensure_ascii=False))
    except (TypeError, ValueError, UnicodeError) as exc:
        raise SessionDataError() from exc

    if not isinstance(value, dict):
        raise SessionDataError()
    if value.get("schema_version") != SCHEMA_VERSION:
        raise SessionDataError()

    operation = value.get("operation")
    items = value.get("items")
    if operation not in _OPERATIONS or not isinstance(items, list):
        raise SessionDataError()
    if operation != "append" and items:
        raise SessionDataError()
    if any(not isinstance(item, dict) for item in items):
        raise SessionDataError()

    return cast(dict[str, Any], value)


def fold_envelopes(envelopes: Sequence[Mapping[str, Any]]) -> list[TResponseInputItem]:
    """append-only操作列をOpenAI Agents SDKの論理履歴へfoldする。"""

    history: list[TResponseInputItem] = []
    for raw_envelope in envelopes:
        envelope = decode_envelope(raw_envelope)
        operation = envelope["operation"]
        if operation == "append":
            history.extend(cast(list[TResponseInputItem], envelope["items"]))
        elif operation == "pop":
            if history:
                history.pop()
        elif operation == "clear":
            history.clear()
        else:  # decode_envelopeで除外済み。型checker向けのfail-closed分岐。
            raise SessionDataError()
    return history


class AgentCoreMemorySession(SessionABC):
    """正常完了したターンだけをAgentCore Memoryへ確定するSession。"""

    def __init__(
        self,
        *,
        memory_id: str,
        actor_id: str,
        session_id: str,
        region: str,
        client: MemoryDataPlaneClient | None = None,
        client_factory: MemoryClientFactory = create_memory_data_client,
    ) -> None:
        self.memory_id = memory_id
        self.actor_id = actor_id
        self.session_id = session_id
        self.region = region
        self._client = client if client is not None else client_factory(region)
        # Runnerが追加したitemは実行完了までMemoryへ書き込まず、このバッファで保持する。
        self._pending_items: list[TResponseInputItem] = []
        # commit再試行では同じtokenを使い、CreateEventの重複登録を防ぐ。
        self._commit_client_token: str | None = None
        # 同じSessionインスタンス内の更新操作を直列化し、バッファ競合を避ける。
        self._mutation_lock = asyncio.Lock()

    async def get_items(self, limit: int | None = None) -> list[TResponseInputItem]:
        """永続eventをfoldし、未確定bufferを末尾へ加えた現在履歴を返す。"""

        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")

        events = await self._list_all_events()
        envelopes = [self._envelope_from_event(event) for event in events]
        history = fold_envelopes(envelopes)
        history.extend(self._clone_items(self._pending_items))
        if limit is None:
            return history
        if limit == 0:
            return []
        return history[-limit:]

    async def add_items(self, items: list[TResponseInputItem]) -> None:
        """Runnerから渡されたitemを検証して未確定bufferへ追加する。"""

        if not items:
            return
        # 直列化できないitemはMemory書き込み時まで持ち越さず、ここで拒否する。
        normalized = encode_envelope("append", items)["items"]
        async with self._mutation_lock:
            self._pending_items.extend(cast(list[TResponseInputItem], normalized))

    async def pop_item(self) -> TResponseInputItem | None:
        """末尾itemを論理削除し、永続済みの場合はpop eventを記録する。"""

        async with self._mutation_lock:
            if self._pending_items:
                return self._pending_items.pop()

            history = await self.get_items()
            if not history:
                return None
            await self._create_operation_event("pop", client_token=str(uuid.uuid4()))
            return history[-1]

    async def clear_session(self) -> None:
        """未確定bufferを破棄し、永続履歴にはclear eventを追加する。"""

        async with self._mutation_lock:
            self._pending_items.clear()
            self._commit_client_token = None
            await self._create_operation_event("clear", client_token=str(uuid.uuid4()))

    async def commit(self) -> None:
        """未確定item群を一つのappend eventとして冪等に確定する。"""

        async with self._mutation_lock:
            if not self._pending_items:
                self._commit_client_token = None
                return
            if self._commit_client_token is None:
                self._commit_client_token = str(uuid.uuid4())

            items = self._clone_items(self._pending_items)
            await self._create_operation_event(
                "append",
                items=items,
                client_token=self._commit_client_token,
            )
            self._pending_items.clear()
            self._commit_client_token = None

    async def rollback(self) -> None:
        """Memoryへ触れず、この実行で追加された未確定itemだけを破棄する。"""

        async with self._mutation_lock:
            self._pending_items.clear()
            self._commit_client_token = None

    async def _list_all_events(self) -> list[dict[str, Any]]:
        """対象scopeの全pageを取得し、fold可能な安定順序へ並べる。"""

        events: list[dict[str, Any]] = []
        next_token: str | None = None
        while True:
            params: dict[str, Any] = {
                "memoryId": self.memory_id,
                "actorId": self.actor_id,
                "sessionId": self.session_id,
                "includePayloads": True,
                "maxResults": 100,
            }
            if next_token is not None:
                params["nextToken"] = next_token

            # boto3互換の同期APIをworker threadへ逃がし、SSEのevent loopを塞がない。
            response = await asyncio.to_thread(self._client.list_events, **params)
            if not isinstance(response, dict) or not isinstance(response.get("events", []), list):
                raise SessionDataError()
            page = response.get("events", [])
            for event in page:
                self._validate_event_scope(event)
                events.append(event)

            token = response.get("nextToken")
            if token is None:
                break
            if not isinstance(token, str) or not token:
                raise SessionDataError()
            next_token = token

        return sorted(events, key=self._event_sort_key)

    async def _create_operation_event(
        self,
        operation: str,
        *,
        items: Sequence[TResponseInputItem] = (),
        client_token: str,
    ) -> None:
        """Session操作を一つのimmutable Memory eventとして追記する。"""

        envelope = encode_envelope(operation, items)
        # blobへmappingを直接渡すと、実サービスから`{key=value}`形式の文字列で返り、
        # JSONとして復元できない。schemaを保って往復できるようJSON文字列を明示する。
        serialized_envelope = json.dumps(
            envelope,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        await asyncio.to_thread(
            self._client.create_event,
            memoryId=self.memory_id,
            actorId=self.actor_id,
            sessionId=self.session_id,
            eventTimestamp=datetime.now(timezone.utc),
            payload=[{"blob": serialized_envelope}],
            clientToken=client_token,
        )

    def _validate_event_scope(self, event: Any) -> None:
        """別actor/sessionのevent混入を正常履歴として扱わない。"""

        if not isinstance(event, dict):
            raise SessionDataError()
        if (
            event.get("memoryId") != self.memory_id
            or event.get("actorId") != self.actor_id
            or event.get("sessionId") != self.session_id
        ):
            raise SessionDataError()

    @staticmethod
    def _event_sort_key(event: Mapping[str, Any]) -> tuple[float, str]:
        """同一時刻でもevent IDで順序を固定できるsort keyを返す。"""

        event_id = event.get("eventId")
        timestamp = event.get("eventTimestamp")
        if not isinstance(event_id, str) or not event_id:
            raise SessionDataError()
        if isinstance(timestamp, datetime):
            parsed = timestamp
        elif isinstance(timestamp, str):
            try:
                parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError as exc:
                raise SessionDataError() from exc
        else:
            raise SessionDataError()
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (parsed.timestamp(), event_id)

    @staticmethod
    def _envelope_from_event(event: Mapping[str, Any]) -> dict[str, Any]:
        """Memory eventから仕様どおり単一blobのenvelopeだけを取り出す。"""

        payload = event.get("payload")
        if not isinstance(payload, list) or len(payload) != 1:
            raise SessionDataError()
        entry = payload[0]
        if not isinstance(entry, dict) or set(entry) != {"blob"}:
            raise SessionDataError()
        return decode_envelope(entry["blob"])

    @staticmethod
    def _clone_items(items: Sequence[TResponseInputItem]) -> list[TResponseInputItem]:
        """JSON往復でSDK itemを永続形式と同じ独立objectへ複製する。"""

        return cast(list[TResponseInputItem], encode_envelope("append", items)["items"])
