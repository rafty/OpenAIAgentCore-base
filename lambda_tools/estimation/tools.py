"""4つのEstimation業務Toolを決定的なサービスとして実装する。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Iterable

from .calculation import calculate_estimate
from .context import create_search_context, resolve_search_context, save_draft
from .contracts import (
    make_result,
    validate_create_arguments,
    validate_get_arguments,
    validate_reference_arguments,
    validate_search_arguments,
)
from .embedding import BedrockEmbeddingAdapter
from .errors import NotFoundError, ValidationError
from .repository import EstimationRepository


EFFORT_TASKS = {
    "EC2": ("BASIC_DESIGN", "DETAIL_DESIGN", "BUILD", "UNIT_TEST"),
    "RDS": ("BASIC_DESIGN", "DETAIL_DESIGN", "BUILD"),
    "CLOUDWATCH": ("MONITORING_DESIGN", "ALARM_CONFIG"),
}
DEFAULT_ROLES = ("AWS_ARCHITECT", "INFRA_ENGINEER")


def _active_unique(items: Iterable[dict[str, Any]], as_of: str, label: str) -> dict[str, Any]:
    target = date.fromisoformat(as_of)
    active = [
        item
        for item in items
        if item.get("approval_status") == "APPROVED"
        and date.fromisoformat(str(item["valid_from"])) <= target <= date.fromisoformat(str(item["valid_to"]))
    ]
    if len(active) != 1:
        raise ValidationError(f"有効な承認済み{label}が一意ではありません")
    return active[0]


class EstimationToolService:
    """ハンドラーやAWS SDKから分離した4業務Toolのcomposition root。"""

    def __init__(self, repository: EstimationRepository, embedding: BedrockEmbeddingAdapter) -> None:
        self.repository = repository
        self.embedding = embedding

    def search_similar_projects(self, arguments: Any, *, correlation_id: str) -> dict[str, Any]:
        value = validate_search_arguments(arguments)
        # 1 Tool呼び出しにつきEmbeddingとSearchVectorsを各1回に限定し、
        # 検索Vectorを通常Itemとして保存しない。
        embedded = self.embedding.embed(value["query"], input_type="search_query")
        candidates = self.repository.search_vectors(embedded.vector, value["filters"])
        for candidate in candidates:
            actual = self.repository.get_project_actual(candidate["project_id"])
            candidate["actual_summary"] = self._actual_summary(actual) if actual else None
        context_id, public_candidates = create_search_context(
            self.repository,
            candidates=candidates,
            filters=value["filters"],
            actor_id=value["actor_id"],
            session_id=value["session_id"],
        )
        no_results = not public_candidates
        return make_result(
            "NO_RESULTS" if no_results else "OK",
            {
                "search_context_id": context_id,
                "similar_projects": public_candidates,
                "no_similar_projects": no_results,
                "distance_function": "COSINE",
            },
            warnings=("類似案件がないため標準マスターだけで見積を継続します。",) if no_results else (),
            correlation_id=correlation_id,
        )

    def get_estimation_reference_data(self, arguments: Any, *, correlation_id: str) -> dict[str, Any]:
        value = validate_reference_arguments(arguments)
        context, project_ids = resolve_search_context(
            self.repository,
            context_id=value["search_context_id"],
            result_refs=value["result_refs"],
            actor_id=value["actor_id"],
            session_id=value["session_id"],
        )
        references = self._load_reference_data(
            services=value["services"],
            task_types=value["task_types"],
            roles=value["roles"],
            estimate_as_of=value["estimate_as_of"],
            project_ids=project_ids,
        )
        references["search_context_id"] = value["search_context_id"]
        references["similar_project_search_status"] = "NO_RESULTS" if not context.get("references") else "OK"
        return make_result("OK", references, correlation_id=correlation_id)

    def create_estimate_draft(self, arguments: Any, *, correlation_id: str) -> dict[str, Any]:
        value = validate_create_arguments(arguments)
        context, project_ids = resolve_search_context(
            self.repository,
            context_id=value["search_context_id"],
            result_refs=value["result_refs"],
            actor_id=value["actor_id"],
            session_id=value["session_id"],
        )
        services = sorted({component["service"] for component in value["project"]["components"] if component["service"] in EFFORT_TASKS})
        references = self._load_reference_data(
            services=services,
            task_types=[],
            roles=list(DEFAULT_ROLES),
            estimate_as_of=value["project"]["estimate_as_of"],
            project_ids=project_ids,
        )
        calculation = calculate_estimate(
            value["project"],
            references["effort_standards"],
            references["rate_cards"],
            references["pricing_policies"],
        )
        no_results = not context.get("references")
        warnings = list(calculation["warnings"])
        if no_results:
            warnings.append("類似案件がなく標準工数・単価・価格マスターだけを根拠にした見積です。")
        draft_data = {
            "input_snapshot": value["project"],
            "search_context_id": value["search_context_id"],
            "result_refs": value["result_refs"],
            "similar_project_ids": project_ids,
            "similar_project_search_status": "NO_RESULTS" if no_results else "OK",
            "calculation_basis": "STANDARD_MASTERS_ONLY" if no_results else "STANDARD_MASTERS_WITH_SIMILAR_PROJECT_REFERENCE",
            "calculation": calculation,
            "warnings": warnings,
            "request_hash": value.get("request_hash", "PREVIEW"),
        }
        if value["operation"] == "PREVIEW":
            # PREVIEWではDraftも冪等性Itemも書かず、同じ検証・再計算結果だけを返す。
            return make_result("OK", {"saved": False, "operation": "PREVIEW", **draft_data}, warnings=warnings, correlation_id=correlation_id)
        # 書き込み後に64 KiB応答制限だけで失敗すると、保存済みなのに呼び出し元が
        # 成功を確認できない。最大長相当の公開IDを含む応答を先に組み立て、
        # サイズ超過はDynamoDBへ触れる前に拒否する。
        make_result(
            "OK",
            {
                "saved": True,
                "operation": "SAVE",
                "project_id": "0" * 36,
                "estimate_id": "0" * 36,
                "version": 1,
                "status": "DRAFT",
                "created_by": value["actor_id"],
                "created_at": "0000-00-00T00:00:00.000000+00:00",
                **draft_data,
            },
            warnings=warnings,
            correlation_id=correlation_id,
        )
        saved = save_draft(
            self.repository,
            actor_id=value["actor_id"],
            idempotency_key=value["idempotency_key"],
            request_hash=value["request_hash"],
            draft_data=draft_data,
        )
        return make_result("OK", {"saved": True, "operation": "SAVE", **self._public_draft(saved)}, warnings=warnings, correlation_id=correlation_id)

    def get_estimate_draft(self, arguments: Any, *, correlation_id: str) -> dict[str, Any]:
        value = validate_get_arguments(arguments)
        draft = self.repository.get_draft(value["project_id"], value["estimate_id"], value["version"])
        if draft is None:
            raise NotFoundError("指定された見積Draftがありません")
        if draft.get("created_by") != value["actor_id"]:
            raise NotFoundError("指定された見積Draftがありません")
        # 保存Itemをそのまま返さず、物理キーと冪等性の内部値を表示用DTOから除く。
        return make_result("OK", self._public_draft(draft), warnings=draft.get("warnings", []), correlation_id=correlation_id)

    def _load_reference_data(
        self,
        *,
        services: list[str],
        task_types: list[str],
        roles: list[str],
        estimate_as_of: str,
        project_ids: list[str],
    ) -> dict[str, Any]:
        efforts = []
        for service in services:
            if service not in EFFORT_TASKS:
                raise ValidationError(f"標準工数の対象外サービスです: {service}")
            selected_tasks = task_types or list(EFFORT_TASKS[service])
            for task_type in selected_tasks:
                if task_type not in EFFORT_TASKS[service]:
                    continue
                items = self.repository.query_partition(f"MASTER#EFFORT#{service}#{task_type}")
                efforts.append(_active_unique(items, estimate_as_of, f"標準工数({service}/{task_type})"))
        rates = [
            _active_unique(self.repository.query_partition(f"MASTER#RATE#{role}"), estimate_as_of, f"単価({role})")
            for role in roles
        ]
        pricing = _active_unique(
            self.repository.query_partition("MASTER#PRICING#PRICING-STANDARD"),
            estimate_as_of,
            "価格ポリシー",
        )
        actuals = []
        for project_id in project_ids:
            item = self.repository.get_project_actual(project_id)
            if item is None:
                raise ValidationError(f"類似案件の正式実績がありません: {project_id}")
            actuals.append(item)
        return {
            "project_actuals": [self._actual_summary(item) for item in actuals],
            "effort_standards": [self._public_master(item) for item in efforts],
            "rate_cards": [self._public_master(item) for item in rates],
            "pricing_policies": [self._public_master(pricing)],
            "master_references": [
                {"id": item.get("master_id", item.get("policy_id")), "version": self._integer_version(item["version"]), "valid_from": item["valid_from"], "source_type": "DYNAMODB_MASTER"}
                for item in [*efforts, *rates, pricing]
            ],
        }

    @staticmethod
    def _actual_summary(item: dict[str, Any] | None) -> dict[str, Any] | None:
        if item is None:
            return None
        return {
            "project_id": item["project_id"],
            "estimated_person_days": item["estimated_person_days"],
            "actual_person_days": item["actual_person_days"],
            "duration_business_days": item["duration_business_days"],
            "role_actuals": item["role_actuals"],
            "variance_reason": item["variance_reason"],
            "outcome_quality": item["outcome_quality"],
        }

    @staticmethod
    def _public_draft(item: dict[str, Any]) -> dict[str, Any]:
        result = {
            key: value
            for key, value in item.items()
            if key not in {"PK", "SK", "idempotency_key", "request_hash", "schema_version", "entity_type"}
        }
        if "version" in result:
            result["version"] = EstimationToolService._integer_version(
                result["version"]
            )
        return result

    @staticmethod
    def _public_master(item: dict[str, Any]) -> dict[str, Any]:
        """正式値とversionを維持しつつ、DynamoDB物理キーを公開結果から除く。"""

        result = {
            key: value
            for key, value in item.items()
            if key not in {"PK", "SK", "entity_type", "schema_version"}
        }
        if "version" in result:
            result["version"] = EstimationToolService._integer_version(
                result["version"]
            )
        return result

    @staticmethod
    def _integer_version(value: Any) -> int:
        """DynamoDB Numberの版番号だけを公開契約のintegerへ戻す。"""

        if isinstance(value, bool):
            raise ValidationError("versionの形式が不正です")
        if isinstance(value, int):
            return value
        if isinstance(value, Decimal) and value == value.to_integral_value():
            return int(value)
        raise ValidationError("versionの形式が不正です")
