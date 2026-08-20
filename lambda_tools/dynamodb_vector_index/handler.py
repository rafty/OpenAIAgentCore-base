"""CloudFormation Custom ResourceからDynamoDB Vector Indexを管理する。"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Mapping

import boto3


LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)


def _client() -> Any:
    return boto3.client("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def _properties(event: Mapping[str, Any]) -> dict[str, Any]:
    value = event.get("ResourceProperties")
    if not isinstance(value, Mapping):
        raise ValueError("ResourcePropertiesがありません")
    required = {
        "TableName",
        "IndexName",
        "VectorAttribute",
        "Dimensions",
        "DistanceFunction",
        "SearchSchema",
        "Projection",
    }
    if not required.issubset(value):
        raise ValueError("Vector Index設定が不足しています")
    dimensions = int(value["Dimensions"])
    if dimensions != 1024 or value["DistanceFunction"] != "COSINE":
        raise ValueError("Vector Indexの次元数または距離関数が不正です")
    return {
        "TableName": str(value["TableName"]),
        "IndexName": str(value["IndexName"]),
        "VectorAttribute": str(value["VectorAttribute"]),
        "Dimensions": dimensions,
        "DistanceFunction": str(value["DistanceFunction"]),
        "SearchSchema": list(value["SearchSchema"]),
        "Projection": dict(value["Projection"]),
    }


def _indexes(client: Any, table_name: str) -> list[dict[str, Any]]:
    response = client.describe_table(TableName=table_name)
    return list(response.get("Table", {}).get("VectorIndexes", []))


def _find(client: Any, table_name: str, index_name: str) -> dict[str, Any] | None:
    return next((item for item in _indexes(client, table_name) if item.get("IndexName") == index_name), None)


def _create_action(properties: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "IndexName": properties["IndexName"],
        "VectorAttribute": {"AttributeName": properties["VectorAttribute"]},
        "SearchSchema": properties["SearchSchema"],
        "Projection": properties["Projection"],
        "Dimensions": properties["Dimensions"],
        "DistanceFunction": properties["DistanceFunction"],
    }


def _attribute_definitions(properties: Mapping[str, Any]) -> list[dict[str, str]]:
    """固定SearchSchemaの属性をVector Index作成と同じUpdateTableへ渡す。"""

    return [
        {"AttributeName": str(element["AttributeName"]), "AttributeType": "S"}
        for element in properties["SearchSchema"]
    ]


def _same_configuration(index: Mapping[str, Any], properties: Mapping[str, Any]) -> bool:
    current = {
        "VectorAttribute": index.get("VectorAttribute"),
        "SearchSchema": index.get("SearchSchema"),
        "Projection": index.get("Projection"),
        "Dimensions": int(index.get("Dimensions", 0)),
        "DistanceFunction": index.get("DistanceFunction"),
    }
    desired = _create_action(properties)
    desired.pop("IndexName")
    return current == desired


def on_event(event: Mapping[str, Any], _context: Any, *, client: Any | None = None) -> dict[str, Any]:
    """Create／Update／Deleteを開始し、安定状態の確認はis_completeへ委ねる。"""

    dynamodb = client or _client()
    properties = _properties(event)
    table_name = properties["TableName"]
    index_name = properties["IndexName"]
    request_type = event.get("RequestType")
    physical_id = f"{table_name}/{index_name}"
    existing = _find(dynamodb, table_name, index_name)
    if request_type in {"Create", "Update"}:
        if existing is None:
            dynamodb.update_table(
                TableName=table_name,
                # CreateTableでは主キー以外の定義が拒否される一方、Vector Indexの
                # SearchSchema属性はIndex作成時のUpdateTableで同時定義する必要がある。
                AttributeDefinitions=_attribute_definitions(properties),
                VectorIndexUpdates=[{"Create": _create_action(properties)}],
            )
        elif not _same_configuration(existing, properties):
            # Vector Indexの不変設定を同名で上書きせず、version付きIndex名を
            # propertiesへ渡すCloudFormation replacementを要求する。
            raise ValueError("同名Vector Indexの設定が一致しません。新しいIndex名で置換してください")
    elif request_type == "Delete":
        if existing is not None:
            dynamodb.update_table(
                TableName=table_name,
                VectorIndexUpdates=[{"Delete": {"IndexName": index_name}}],
            )
    else:
        raise ValueError("未対応のCloudFormation RequestTypeです")
    LOGGER.info(json.dumps({"request_type": request_type, "table_name": table_name, "index_name": index_name, "state": "STARTED"}, separators=(",", ":")))
    return {"PhysicalResourceId": physical_id, "Data": {"IndexName": index_name}}


def is_complete(event: Mapping[str, Any], _context: Any, *, client: Any | None = None) -> dict[str, Any]:
    """非同期IndexがACTIVEまたは削除済みになるまでProviderへ再確認させる。"""

    dynamodb = client or _client()
    properties = _properties(event)
    index = _find(dynamodb, properties["TableName"], properties["IndexName"])
    if event.get("RequestType") == "Delete":
        return {"IsComplete": index is None}
    if index is None:
        return {"IsComplete": False}
    status = index.get("IndexStatus")
    if status in {"FAILED", "DELETING"}:
        raise RuntimeError(f"Vector Indexが利用可能になりません: status={status}")
    return {"IsComplete": status == "ACTIVE"}
