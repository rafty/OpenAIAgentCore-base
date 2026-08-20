"""検索候補のopaque参照と冪等なDraft保存境界。"""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Mapping

from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

from .errors import ContextExpiredError, ContextInvalidError, SaveFailedError, ValidationError
from .repository import EstimationRepository, SEARCH_SCOPE


CONTEXT_TTL_MINUTES = 30
MAX_DRAFT_BYTES = 350 * 1024


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def create_search_context(
    repository: EstimationRepository,
    *,
    candidates: list[dict[str, Any]],
    filters: Mapping[str, str],
    actor_id: str,
    session_id: str,
    now: datetime | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    current = now or _utc_now()
    context_id = secrets.token_urlsafe(32)
    references: dict[str, dict[str, Any]] = {}
    public_candidates: list[dict[str, Any]] = []
    for candidate in candidates[:3]:
        ref = secrets.token_urlsafe(32)
        references[ref] = {"project_id": candidate["project_id"], "rank": candidate["rank"]}
        public_candidates.append(
            {
                "result_ref": ref,
                "project_id": candidate["project_id"],
                "project_name": candidate["project_name"],
                "search_summary": candidate["search_summary"],
                "rank": candidate["rank"],
                "distance": candidate["distance"],
                "distance_function": "COSINE",
                "actual_summary": candidate.get("actual_summary"),
            }
        )
    expires = current + timedelta(minutes=CONTEXT_TTL_MINUTES)
    repository.save_search_context(
        {
            "PK": f"SEARCH_CONTEXT#{context_id}",
            "SK": "CONTEXT",
            "entity_type": "SEARCH_CONTEXT",
            "schema_version": 1,
            "search_scope": SEARCH_SCOPE,
            "actor_id": actor_id,
            "session_id": session_id,
            "filters": dict(filters),
            "references": references,
            "created_at": current.isoformat(),
            "expires_at": expires.isoformat(),
            "expires_at_epoch": int(expires.timestamp()),
        }
    )
    return context_id, public_candidates


def resolve_search_context(
    repository: EstimationRepository,
    *,
    context_id: str,
    result_refs: list[str],
    actor_id: str,
    session_id: str,
    now: datetime | None = None,
) -> tuple[dict[str, Any], list[str]]:
    context = repository.get_search_context(context_id)
    if context is None or context.get("search_scope") != SEARCH_SCOPE:
        raise ContextInvalidError("検索コンテキストが不正です。再検索してください")
    if context.get("actor_id") != actor_id or context.get("session_id") != session_id:
        raise ContextInvalidError("検索コンテキストの実行主体が一致しません")
    # DynamoDB TTLは物理削除が遅延するため、Itemが残っていても現在時刻で
    # 論理期限を必ず評価し、期限切れ参照を認可しない。
    current = now or _utc_now()
    if current >= datetime.fromisoformat(str(context["expires_at"])):
        raise ContextExpiredError("検索コンテキストの期限が切れています。再検索してください")
    references = context.get("references", {})
    project_ids = []
    for ref in result_refs:
        resolved = references.get(ref)
        if not isinstance(resolved, Mapping):
            raise ContextInvalidError("検索結果に含まれないresult_refです")
        project_ids.append(str(resolved["project_id"]))
    return context, project_ids


def canonical_request_hash(value: Mapping[str, Any]) -> str:
    def default(item: Any) -> str:
        if isinstance(item, Decimal):
            return format(item, "f")
        raise TypeError

    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=default)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _typed_size(item: Mapping[str, Any]) -> int:
    serializer = TypeSerializer()
    typed = {key: serializer.serialize(value) for key, value in item.items()}
    return len(json.dumps(typed, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8"))


def save_draft(
    repository: EstimationRepository,
    *,
    actor_id: str,
    idempotency_key: str,
    request_hash: str,
    draft_data: Mapping[str, Any],
    now: datetime | None = None,
    uuid_factory: Callable[[], uuid.UUID] = uuid.uuid4,
) -> dict[str, Any]:
    marker_pk = f"IDEMPOTENCY#{actor_id}"
    marker_sk = f"CREATE_ESTIMATE#{idempotency_key}"
    existing = repository.get_item(marker_pk, marker_sk)
    if existing is not None:
        if existing.get("request_hash") != request_hash:
            raise SaveFailedError("同じ冪等性キーが異なる保存要求に使用されています")
        draft = repository.get_draft(existing["project_id"], existing["estimate_id"], int(existing["version"]))
        if draft is None:
            raise SaveFailedError("既存の保存結果を再取得できません")
        return draft

    current = now or _utc_now()
    project_id = str(uuid_factory())
    estimate_id = str(uuid_factory())
    version = 1
    draft = {
        "PK": f"ESTIMATE_PROJECT#{project_id}",
        "SK": f"ESTIMATE#{estimate_id}#V{version:04d}",
        "entity_type": "ESTIMATE_DRAFT",
        "schema_version": 1,
        "project_id": project_id,
        "estimate_id": estimate_id,
        "version": version,
        "status": "DRAFT",
        "created_by": actor_id,
        "created_at": current.isoformat(),
        "idempotency_key": idempotency_key,
        **dict(draft_data),
    }
    if _typed_size(draft) > MAX_DRAFT_BYTES:
        raise ValidationError("Draft Itemが350 KiBを超えています")
    marker = {
        "PK": marker_pk,
        "SK": marker_sk,
        "entity_type": "IDEMPOTENCY",
        "schema_version": 1,
        "request_hash": request_hash,
        "project_id": project_id,
        "estimate_id": estimate_id,
        "version": version,
        "created_at": current.isoformat(),
    }
    try:
        # markerとDraftを一つのtransactionへ置き、MCPやMemoryの再試行で
        # 片方だけが作成される状態とDraftの重複作成を防ぐ。
        repository.transact_save_draft(idempotency_item=marker, draft_item=draft)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "TransactionCanceledException":
            concurrent = repository.get_item(marker_pk, marker_sk)
            if concurrent and concurrent.get("request_hash") == request_hash:
                result = repository.get_draft(concurrent["project_id"], concurrent["estimate_id"], int(concurrent["version"]))
                if result is not None:
                    return result
        raise SaveFailedError("Draftを保存できません") from exc
    saved = repository.get_draft(project_id, estimate_id, version)
    if saved is None or saved.get("status") != "DRAFT" or saved.get("request_hash", request_hash) != request_hash:
        raise SaveFailedError("保存後のDraftを確認できません")
    return saved
