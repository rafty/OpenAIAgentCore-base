"""DynamoDB Vector Index Custom Resourceの状態遷移を検証する。"""

import pytest

from lambda_tools.dynamodb_vector_index.handler import is_complete, on_event


PROPERTIES = {
    "TableName": "OpenAiEstimationData",
    "IndexName": "EstimationProjectVectorIndexV1",
    "VectorAttribute": "embedding",
    "Dimensions": 1024,
    "DistanceFunction": "COSINE",
    "SearchSchema": [
        {"AttributeName": "search_scope", "SearchSchemaElementType": "HASH"},
        {"AttributeName": "entity_type", "SearchSchemaElementType": "INLINE_FILTER"},
        {"AttributeName": "project_type", "SearchSchemaElementType": "INLINE_FILTER"},
        {"AttributeName": "architecture_family", "SearchSchemaElementType": "INLINE_FILTER"},
        {"AttributeName": "outcome_quality", "SearchSchemaElementType": "INLINE_FILTER"},
    ],
    "Projection": {"ProjectionType": "INCLUDE", "NonKeyAttributes": ["project_id"]},
}


class FakeDynamo:
    def __init__(self) -> None:
        self.indexes: list[dict[str, object]] = []
        self.updates: list[dict[str, object]] = []

    def describe_table(self, **_kwargs):
        return {"Table": {"VectorIndexes": self.indexes}}

    def update_table(self, **kwargs):
        self.updates.append(kwargs)
        update = kwargs["VectorIndexUpdates"][0]
        if "Create" in update:
            self.indexes = [{**update["Create"], "IndexStatus": "CREATING"}]
        else:
            self.indexes = []


def _event(request_type: str, properties=PROPERTIES):
    return {"RequestType": request_type, "ResourceProperties": properties}


def test_create_wait_active_idempotent_and_delete() -> None:
    client = FakeDynamo()
    created = on_event(_event("Create"), None, client=client)
    assert created["PhysicalResourceId"] == "OpenAiEstimationData/EstimationProjectVectorIndexV1"
    assert client.updates[0]["TableName"] == "OpenAiEstimationData"
    assert client.updates[0]["AttributeDefinitions"] == [
        {"AttributeName": "search_scope", "AttributeType": "S"},
        {"AttributeName": "entity_type", "AttributeType": "S"},
        {"AttributeName": "project_type", "AttributeType": "S"},
        {"AttributeName": "architecture_family", "AttributeType": "S"},
        {"AttributeName": "outcome_quality", "AttributeType": "S"},
    ]
    assert is_complete(_event("Create"), None, client=client) == {"IsComplete": False}
    client.indexes[0]["IndexStatus"] = "ACTIVE"
    assert is_complete(_event("Create"), None, client=client) == {"IsComplete": True}
    on_event(_event("Create"), None, client=client)
    assert len(client.updates) == 1
    on_event(_event("Delete"), None, client=client)
    assert client.updates[-1]["VectorIndexUpdates"] == [
        {"Delete": {"IndexName": "EstimationProjectVectorIndexV1"}}
    ]
    assert is_complete(_event("Delete"), None, client=client) == {"IsComplete": True}
    on_event(_event("Delete"), None, client=client)
    assert len(client.updates) == 2


def test_failed_or_mismatched_index_is_not_silently_adopted() -> None:
    client = FakeDynamo()
    on_event(_event("Create"), None, client=client)
    client.indexes[0]["IndexStatus"] = "FAILED"
    with pytest.raises(RuntimeError, match="FAILED"):
        is_complete(_event("Create"), None, client=client)
    changed = {**PROPERTIES, "Projection": {"ProjectionType": "ALL"}}
    with pytest.raises(ValueError, match="置換"):
        on_event(_event("Update", changed), None, client=client)


def test_fixed_dimensions_and_request_type_are_enforced() -> None:
    client = FakeDynamo()
    with pytest.raises(ValueError):
        on_event(_event("Create", {**PROPERTIES, "Dimensions": 1536}), None, client=client)
    with pytest.raises(ValueError):
        on_event(_event("Import"), None, client=client)
    assert client.updates == []
