"""DynamoDBの限定操作、opaque context、Draft冪等性を検証する。"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from lambda_tools.estimation.context import create_search_context, resolve_search_context, save_draft
from lambda_tools.estimation.errors import ContextExpiredError, ContextInvalidError, SaveFailedError, ValidationError
from lambda_tools.estimation.repository import EstimationRepository


class FakeDynamo:
    def __init__(self) -> None:
        self.search_calls: list[dict[str, object]] = []

    def search_vectors(self, **kwargs: object) -> dict[str, object]:
        self.search_calls.append(kwargs)
        serializer = EstimationRepository(self)._serializer
        item = {
            "project_id": "HIST-001",
            "project_name": "Alpha",
            "search_summary": "summary",
            "entity_type": "HISTORICAL_PROJECT",
            "search_scope": "ORG_SAMPLE#INTERNAL",
            "project_type": "NEW_BUILD",
            "architecture_family": "EC2_RDS_WEB",
            "outcome_quality": "ACCEPTED",
        }
        return {"SearchResults": [{"Item": {k: serializer.serialize(v) for k, v in item.items()}, "Score": 0.1}]}


def test_vector_search_is_fixed_to_scope_filter_projection_and_top3() -> None:
    client = FakeDynamo()
    repository = EstimationRepository(client)
    result = repository.search_vectors([0.0] * 1024, {"project_type": "NEW_BUILD"})
    assert result[0]["project_id"] == "HIST-001"
    call = client.search_calls[0]
    assert call["TopK"] == 3
    assert call["IndexName"] == "EstimationProjectVectorIndexV1"
    assert call["SearchVector"] == [{"N": "0.0"}] * 1024
    assert "search_scope" in str(call["ExpressionAttributeNames"])
    assert not hasattr(repository, "scan")
    with pytest.raises(ValidationError):
        repository.search_vectors([0.0], {})
    with pytest.raises(ValidationError):
        repository.search_vectors([0.0] * 1024, {"arbitrary": "x"})


class MemoryRepository:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, object]] = {}

    def save_search_context(self, item: dict[str, object]) -> None:
        self.items[(str(item["PK"]), str(item["SK"]))] = dict(item)

    def get_search_context(self, context_id: str):
        return self.items.get((f"SEARCH_CONTEXT#{context_id}", "CONTEXT"))

    def get_item(self, pk: str, sk: str):
        return self.items.get((pk, sk))

    def get_draft(self, project_id: str, estimate_id: str, version: int):
        return self.items.get((f"ESTIMATE_PROJECT#{project_id}", f"ESTIMATE#{estimate_id}#V{version:04d}"))

    def transact_save_draft(self, *, idempotency_item, draft_item) -> None:
        self.items[(idempotency_item["PK"], idempotency_item["SK"])] = dict(idempotency_item)
        self.items[(draft_item["PK"], draft_item["SK"])] = dict(draft_item)


def test_context_is_bound_to_actor_session_ref_and_logical_expiry() -> None:
    repository = MemoryRepository()
    now = datetime(2026, 8, 20, tzinfo=timezone.utc)
    context_id, candidates = create_search_context(
        repository,  # type: ignore[arg-type]
        candidates=[{"project_id": "HIST-001", "project_name": "A", "search_summary": "S", "rank": 1, "distance": Decimal("0.1")}],
        filters={},
        actor_id="actor",
        session_id="session",
        now=now,
    )
    _, ids = resolve_search_context(
        repository,  # type: ignore[arg-type]
        context_id=context_id,
        result_refs=[candidates[0]["result_ref"]],
        actor_id="actor",
        session_id="session",
        now=now,
    )
    assert ids == ["HIST-001"]
    with pytest.raises(ContextInvalidError):
        resolve_search_context(repository, context_id=context_id, result_refs=[candidates[0]["result_ref"]], actor_id="other", session_id="session", now=now)  # type: ignore[arg-type]
    with pytest.raises(ContextInvalidError):
        resolve_search_context(repository, context_id=context_id, result_refs=["tampered"], actor_id="actor", session_id="session", now=now)  # type: ignore[arg-type]
    with pytest.raises(ContextExpiredError):
        resolve_search_context(repository, context_id=context_id, result_refs=[], actor_id="actor", session_id="session", now=now + timedelta(minutes=30))  # type: ignore[arg-type]


def test_draft_save_is_idempotent_and_conflict_is_rejected() -> None:
    repository = MemoryRepository()
    fixed_uuid = UUID("00000000-0000-4000-8000-000000000001")
    first = save_draft(
        repository,  # type: ignore[arg-type]
        actor_id="actor",
        idempotency_key="key",
        request_hash="hash-a",
        draft_data={"warnings": []},
        uuid_factory=lambda: fixed_uuid,
    )
    second = save_draft(repository, actor_id="actor", idempotency_key="key", request_hash="hash-a", draft_data={"warnings": []})  # type: ignore[arg-type]
    assert second["estimate_id"] == first["estimate_id"]
    with pytest.raises(SaveFailedError):
        save_draft(repository, actor_id="actor", idempotency_key="key", request_hash="hash-b", draft_data={"warnings": []})  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        save_draft(repository, actor_id="actor", idempotency_key="large", request_hash="hash", draft_data={"value": "x" * (351 * 1024)})  # type: ignore[arg-type]
