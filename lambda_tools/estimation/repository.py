"""許可したDynamoDBキー操作だけを公開するEstimation Repository。"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable, Mapping

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

from .errors import DependencyUnavailableError, ValidationError


TABLE_NAME = "OpenAiEstimationData"
INDEX_NAME = "EstimationProjectVectorIndexV1"
SEARCH_SCOPE = "ORG_SAMPLE#INTERNAL"
ALLOWED_FILTERS = {"project_type", "architecture_family", "outcome_quality"}


class EstimationRepository:
    """Scanや任意キー生成を持たず、業務Item別の操作だけを提供する。"""

    def __init__(self, client: Any, *, table_name: str = TABLE_NAME, index_name: str = INDEX_NAME) -> None:
        self.client = client
        self.table_name = table_name
        self.index_name = index_name
        self._serializer = TypeSerializer()
        self._deserializer = TypeDeserializer()

    def _serialize_item(self, item: Mapping[str, Any]) -> dict[str, Any]:
        return {key: self._serializer.serialize(value) for key, value in item.items()}

    def _deserialize_item(self, item: Mapping[str, Any]) -> dict[str, Any]:
        return {key: self._deserializer.deserialize(value) for key, value in item.items()}

    def get_item(self, pk: str, sk: str) -> dict[str, Any] | None:
        response = self.client.get_item(
            TableName=self.table_name,
            Key=self._serialize_item({"PK": pk, "SK": sk}),
            ConsistentRead=True,
        )
        item = response.get("Item")
        return self._deserialize_item(item) if item else None

    def query_partition(self, pk: str) -> list[dict[str, Any]]:
        # マスター参照を既知Partition Keyへ限定し、テーブル全体のScanや
        # 利用者が組み立てる任意式をRepository APIとして提供しない。
        response = self.client.query(
            TableName=self.table_name,
            KeyConditionExpression="#pk = :pk",
            ExpressionAttributeNames={"#pk": "PK"},
            ExpressionAttributeValues={":pk": self._serializer.serialize(pk)},
            ConsistentRead=True,
        )
        return [self._deserialize_item(item) for item in response.get("Items", [])]

    def put_item(self, item: Mapping[str, Any], *, condition: str = "attribute_not_exists(PK)") -> None:
        self.client.put_item(
            TableName=self.table_name,
            Item=self._serialize_item(item),
            ConditionExpression=condition,
        )

    def search_vectors(self, vector: list[float], filters: Mapping[str, str]) -> list[dict[str, Any]]:
        if len(vector) != 1024:
            raise ValidationError("検索Vectorは1024次元で指定してください")
        if set(filters) - ALLOWED_FILTERS:
            raise ValidationError("許可されていないVector検索filterです")
        names = {"#scope": "search_scope", "#entity": "entity_type"}
        values = {
            ":scope": self._serializer.serialize(SEARCH_SCOPE),
            ":entity": self._serializer.serialize("HISTORICAL_PROJECT"),
        }
        conditions = ["#scope = :scope", "#entity = :entity"]
        for index, (key, value) in enumerate(sorted(filters.items())):
            name_key = f"#f{index}"
            value_key = f":f{index}"
            names[name_key] = key
            values[value_key] = self._serializer.serialize(value)
            conditions.append(f"{name_key} = {value_key}")
        response = self.client.search_vectors(
            TableName=self.table_name,
            IndexName=self.index_name,
            # SearchVectorsは通常のPython数値Listではなく、低レベルDynamoDB
            # APIのAttributeValue配列を要求する。保存ItemのL属性と同じ数値でも、
            # 検索API境界では各要素をNへ明示変換する。
            SearchVector=[{"N": str(value)} for value in vector],
            SearchConditionExpression=" AND ".join(conditions),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ProjectionExpression="project_id,project_name,search_summary,entity_type,search_scope,project_type,architecture_family,outcome_quality",
            TopK=3,
        )
        results = []
        for rank, result in enumerate(response.get("SearchResults", []), start=1):
            item = self._deserialize_item(result.get("Item", {}))
            if (
                item.get("entity_type") != "HISTORICAL_PROJECT"
                or item.get("search_scope") != SEARCH_SCOPE
                or not str(item.get("project_id", "")).startswith("HIST-")
            ):
                # Index projectionは正式データではないため、scopeと種別を検証後、
                # 正式な実績値は別の完全キーGetItemで再取得する。
                continue
            item["rank"] = rank
            item["distance"] = Decimal(str(result.get("Score", 0)))
            results.append(item)
        return results

    def get_project_actual(self, project_id: str) -> dict[str, Any] | None:
        if not project_id.startswith("HIST-"):
            raise ValidationError("過去案件IDの形式が不正です")
        return self.get_item(f"PROJECT#{project_id}", "ACTUAL#FINAL")

    def save_search_context(self, item: Mapping[str, Any]) -> None:
        if not str(item.get("PK", "")).startswith("SEARCH_CONTEXT#") or item.get("SK") != "CONTEXT":
            raise ValidationError("検索コンテキストのキーが不正です")
        self.put_item(item)

    def get_search_context(self, context_id: str) -> dict[str, Any] | None:
        return self.get_item(f"SEARCH_CONTEXT#{context_id}", "CONTEXT")

    def get_draft(self, project_id: str, estimate_id: str, version: int) -> dict[str, Any] | None:
        return self.get_item(
            f"ESTIMATE_PROJECT#{project_id}",
            f"ESTIMATE#{estimate_id}#V{version:04d}",
        )

    def transact_save_draft(
        self,
        *,
        idempotency_item: Mapping[str, Any],
        draft_item: Mapping[str, Any],
    ) -> None:
        if not str(idempotency_item.get("PK", "")).startswith("IDEMPOTENCY#"):
            raise ValidationError("冪等性Itemのキーが不正です")
        if not str(draft_item.get("PK", "")).startswith("ESTIMATE_PROJECT#"):
            raise ValidationError("Draft Itemのキーが不正です")
        self.client.transact_write_items(
            TransactItems=[
                {
                    "Put": {
                        "TableName": self.table_name,
                        "Item": self._serialize_item(idempotency_item),
                        "ConditionExpression": "attribute_not_exists(PK)",
                    }
                },
                {
                    "Put": {
                        "TableName": self.table_name,
                        "Item": self._serialize_item(draft_item),
                        "ConditionExpression": "attribute_not_exists(PK)",
                    }
                },
            ]
        )

    def batch_seed(self, items: Iterable[Mapping[str, Any]]) -> None:
        for item in items:
            self.client.put_item(TableName=self.table_name, Item=self._serialize_item(item))

    def delete_saved_draft(
        self,
        *,
        project_id: str,
        estimate_id: str,
        version: int,
        actor_id: str,
        idempotency_key: str,
    ) -> None:
        """運用CLIが特定済みのDraftと対応markerだけを同時削除する。"""

        if version < 1 or not all(
            isinstance(value, str) and value
            for value in (project_id, estimate_id, actor_id, idempotency_key)
        ):
            raise ValidationError("Draft後片付けの完全キーが不正です")
        # Scanやprefix削除をRepositoryへ追加せず、保存Itemから復元できる二つの
        # 完全キーだけを同じtransactionで削除する。
        self.client.transact_write_items(
            TransactItems=[
                {
                    "Delete": {
                        "TableName": self.table_name,
                        "Key": self._serialize_item(
                            {
                                "PK": f"ESTIMATE_PROJECT#{project_id}",
                                "SK": f"ESTIMATE#{estimate_id}#V{version:04d}",
                            }
                        ),
                    }
                },
                {
                    "Delete": {
                        "TableName": self.table_name,
                        "Key": self._serialize_item(
                            {
                                "PK": f"IDEMPOTENCY#{actor_id}",
                                "SK": f"CREATE_ESTIMATE#{idempotency_key}",
                            }
                        ),
                    }
                },
            ]
        )
