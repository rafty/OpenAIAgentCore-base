"""Sample Project Deltaの検索・構造化参照・SAVE・再取得を決定的に通す。"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from lambda_tools.estimation.embedding import embedding_source_hash, normalize_text
from lambda_tools.estimation.sample_data import load_seed_bundle
from lambda_tools.estimation.tools import EstimationToolService


SOURCE = Path(__file__).resolve().parents[3] / "dynamodb-seed"


class FakeEmbedding:
    def embed(self, text: str, *, input_type: str):
        normalized = normalize_text(text)
        return SimpleNamespace(
            vector=[0.0] * 1024,
            source_hash=embedding_source_hash(normalized, input_type),
        )


class WorkflowRepository:
    def __init__(self, *, candidates: bool = True) -> None:
        bundle = load_seed_bundle(SOURCE)
        self.bundle = bundle
        self.candidates = candidates
        self.items: dict[tuple[str, str], dict] = {}
        for actual in bundle.project_actuals:
            self.items[(f"PROJECT#{actual['project_id']}", "ACTUAL#FINAL")] = dict(actual)
        for item in bundle.effort_standards:
            self.items[(f"MASTER#EFFORT#{item['service']}#{item['task_type']}", f"V#{item['master_id']}")] = dict(item)
        for item in bundle.rate_cards:
            self.items[(f"MASTER#RATE#{item['role']}", f"V#{item['master_id']}")] = dict(item)
        for item in bundle.pricing_policies:
            self.items[(f"MASTER#PRICING#{item['policy_id']}", f"V#{item['policy_id']}")] = dict(item)

    def search_vectors(self, vector, filters):
        assert len(vector) == 1024
        if not self.candidates:
            return []
        summary = dict(self.bundle.project_summaries[0])
        summary.update(rank=1, distance=Decimal("0.05"))
        return [summary]

    def get_project_actual(self, project_id):
        return self.items.get((f"PROJECT#{project_id}", "ACTUAL#FINAL"))

    def save_search_context(self, item):
        self.items[(item["PK"], item["SK"])] = dict(item)

    def get_search_context(self, context_id):
        return self.items.get((f"SEARCH_CONTEXT#{context_id}", "CONTEXT"))

    def query_partition(self, pk):
        return [value for (item_pk, _), value in self.items.items() if item_pk == pk]

    def get_item(self, pk, sk):
        return self.items.get((pk, sk))

    def get_draft(self, project_id, estimate_id, version):
        return self.items.get((f"ESTIMATE_PROJECT#{project_id}", f"ESTIMATE#{estimate_id}#V{version:04d}"))

    def transact_save_draft(self, *, idempotency_item, draft_item):
        assert idempotency_item["PK"].startswith("IDEMPOTENCY#")
        assert draft_item["PK"].startswith("ESTIMATE_PROJECT#")
        self.items[(idempotency_item["PK"], idempotency_item["SK"])] = dict(idempotency_item)
        self.items[(draft_item["PK"], draft_item["SK"])] = dict(draft_item)


def _search(service: EstimationToolService):
    return service.search_similar_projects(
        {
            "query": "ALB、EC2 5台、RDS 2DB、CloudWatchアラーム12個の新規Web構築",
            "filters": {"project_type": "NEW_BUILD", "architecture_family": "EC2_RDS_WEB"},
            "_actor_id": "actor",
            "_session_id": "session",
        },
        correlation_id="search",
    )


def _save(service: EstimationToolService, search_result, operation="SAVE"):
    bundle = load_seed_bundle(SOURCE)
    candidates = search_result["data"]["similar_projects"]
    project = dict(bundle.sample_project_delta["normalized_input"])
    # save_intentは利用者入力の分類結果であり、create Toolのproject DTOへは
    # operationとして反映してから渡す。
    project.pop("save_intent")
    return service.create_estimate_draft(
        {
            "operation": operation,
            "project": project,
            "search_context_id": search_result["data"]["search_context_id"],
            "result_refs": [item["result_ref"] for item in candidates],
            "_actor_id": "actor",
            "_session_id": "session",
            "_idempotency_key": "deterministic-key",
            "_request_hash": "deterministic-hash",
        },
        correlation_id="save",
    )


def test_delta_historical_reference_save_get_and_manager_facts() -> None:
    repository = WorkflowRepository()
    service = EstimationToolService(repository, FakeEmbedding())  # type: ignore[arg-type]
    search = _search(service)
    assert search["data"]["similar_projects"][0]["project_id"] == "HIST-001"
    ref = service.get_estimation_reference_data(
        {
            "search_context_id": search["data"]["search_context_id"],
            "result_refs": [search["data"]["similar_projects"][0]["result_ref"]],
            "project_type": "NEW_BUILD",
            "services": ["EC2", "RDS", "CLOUDWATCH"],
            "task_types": [],
            "roles": ["AWS_ARCHITECT", "INFRA_ENGINEER"],
            "estimate_as_of": "2026-08-19",
            "_actor_id": "actor",
            "_session_id": "session",
        },
        correlation_id="reference",
    )
    assert ref["data"]["project_actuals"][0]["actual_person_days"] == "26.0"
    assert all(item["version"] == 1 for item in ref["data"]["master_references"])

    saved = _save(service, search)
    calculation = saved["data"]["calculation"]
    assert saved["data"]["saved"] is True
    assert calculation["total_person_days"] == "15.7"
    assert calculation["role_person_days"] == {"AWS_ARCHITECT": "5.0", "INFRA_ENGINEER": "10.7"}
    assert calculation["cost_jpy"] == "1356000.0"
    assert calculation["proposed_price_jpy"] == "1695000"
    assert any("自動補正" in warning for warning in calculation["warnings"])
    assert any("Multi-AZ" in warning for warning in calculation["warnings"])

    fetched = service.get_estimate_draft(
        {
            "project_id": saved["data"]["project_id"],
            "estimate_id": saved["data"]["estimate_id"],
            "version": saved["data"]["version"],
            "_actor_id": "actor",
            "_session_id": "session",
        },
        correlation_id="get",
    )
    assert fetched["data"]["estimate_id"] == saved["data"]["estimate_id"]
    # Scripted Managerが最終回答へ利用すべき事実を固定し、保存IDを欠落させない。
    manager_answer = (
        f"類似案件HIST-001を参照し、合計{calculation['total_person_days']}人日"
        f"（AWS_ARCHITECT {calculation['role_person_days']['AWS_ARCHITECT']}、"
        f"INFRA_ENGINEER {calculation['role_person_days']['INFRA_ENGINEER']}）、"
        f"原価{int(Decimal(calculation['cost_jpy'])):,}円、提示価格"
        f"{int(Decimal(calculation['proposed_price_jpy'])):,}円です。"
        f"Draft {saved['data']['estimate_id']} V{saved['data']['version']:04d}を保存しました。"
    )
    for expected in ("HIST-001", "15.7", "5.0", "10.7", "1,356,000", "1,695,000", saved["data"]["estimate_id"]):
        assert expected in manager_answer


def test_zero_results_continues_with_standard_masters_only() -> None:
    repository = WorkflowRepository(candidates=False)
    service = EstimationToolService(repository, FakeEmbedding())  # type: ignore[arg-type]
    search = _search(service)
    assert search["status"] == "NO_RESULTS"
    saved = _save(service, search)
    assert saved["data"]["saved"] is True
    assert saved["data"]["similar_project_ids"] == []
    assert saved["data"]["calculation_basis"] == "STANDARD_MASTERS_ONLY"
    assert any("類似案件がなく" in warning for warning in saved["warnings"])
