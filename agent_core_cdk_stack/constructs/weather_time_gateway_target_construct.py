"""Weather／Time Lambdaをinline schemaのGatewayTargetとして登録する。"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_lambda as lambda_
from constructs import Construct


WEATHER_TIME_GATEWAY_TARGET_NAME = "WeatherTimeMock"
_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "lambda_tools" / "weather" / "tools.json"
_SCHEMA_TYPES = {
    "array": agentcore.SchemaDefinitionType.ARRAY,
    "boolean": agentcore.SchemaDefinitionType.BOOLEAN,
    "integer": agentcore.SchemaDefinitionType.INTEGER,
    "number": agentcore.SchemaDefinitionType.NUMBER,
    "object": agentcore.SchemaDefinitionType.OBJECT,
    "string": agentcore.SchemaDefinitionType.STRING,
}
_SCHEMA_KEYS = frozenset({"type", "description", "items", "properties", "required"})


class WeatherTimeGatewayTargetConstruct(Construct):
    """正本schema、Lambda TargetおよびGateway Role権限をまとめる。"""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        gateway: agentcore.IGateway,
        lambda_function: lambda_.IFunction,
    ) -> None:
        super().__init__(scope, construct_id)

        # schema正本を複製せずjsii L2型へ限定変換し、未知shapeはCloudFormationへ
        # 曖昧なpayloadを渡す前にfail-fastにする。
        tool_definitions = _load_tool_definitions(_SCHEMA_PATH)
        tool_schema = agentcore.ToolSchema.from_inline(tool_definitions)

        # L2内部grantだけではTarget作成順がpolicyへ固定されないため、先にGrantを
        # 取得し、Targetへ明示適用する。inline schemaなのでGatewayにS3権限は不要。
        invoke_grant = lambda_function.grant_invoke(gateway.role)
        self.target_name = WEATHER_TIME_GATEWAY_TARGET_NAME
        self.target = agentcore.GatewayTarget.for_lambda(
            self,
            "Target",
            gateway=gateway,
            lambda_function=lambda_function,
            tool_schema=tool_schema,
            gateway_target_name=self.target_name,
            credential_provider_configurations=[
                agentcore.GatewayCredentialProvider.from_iam_role()
            ],
        )
        invoke_grant.apply_before(self.target)


def _load_tool_definitions(path: Path) -> list[agentcore.ToolDefinition]:
    """UTF-8 JSONのTool配列を検証してCDK L2型へ変換する。"""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Weather Tool schemaを読み込めません。") from exc
    if not isinstance(raw, list) or not raw:
        raise ValueError("Weather Tool schemaは空でない配列である必要があります。")
    return [_tool_definition_from_json(item) for item in raw]


def _tool_definition_from_json(value: Any) -> agentcore.ToolDefinition:
    """現在の正本で許可したTool definitionだけをL2型へ変換する。"""

    if not isinstance(value, Mapping) or set(value) != {
        "name",
        "description",
        "inputSchema",
    }:
        raise ValueError("未対応のWeather Tool definitionです。")
    name = value["name"]
    description = value["description"]
    if not isinstance(name, str) or not name or not isinstance(description, str) or not description:
        raise ValueError("Weather Toolの名前または説明が不正です。")
    return agentcore.ToolDefinition(
        name=name,
        description=description,
        input_schema=_schema_definition_from_json(value["inputSchema"]),
    )


def _schema_definition_from_json(value: Any) -> agentcore.SchemaDefinition:
    """限定したJSON Schema shapeを再帰的にCDK型へ変換する。"""

    if not isinstance(value, Mapping) or not set(value).issubset(_SCHEMA_KEYS):
        raise ValueError("未対応のWeather Tool input schemaです。")
    schema_type = value.get("type")
    if not isinstance(schema_type, str) or schema_type not in _SCHEMA_TYPES:
        raise ValueError("未対応のWeather Tool schema typeです。")

    description = value.get("description")
    if description is not None and not isinstance(description, str):
        raise ValueError("Weather Tool schemaの説明が不正です。")

    properties: dict[str, agentcore.SchemaDefinition] | None = None
    raw_properties = value.get("properties")
    if raw_properties is not None:
        if schema_type != "object" or not isinstance(raw_properties, Mapping):
            raise ValueError("Weather Tool schemaのpropertiesが不正です。")
        properties = {}
        for property_name, property_schema in raw_properties.items():
            if not isinstance(property_name, str) or not property_name:
                raise ValueError("Weather Tool schemaのproperty名が不正です。")
            properties[property_name] = _schema_definition_from_json(property_schema)

    required: list[str] | None = None
    raw_required = value.get("required")
    if raw_required is not None:
        if (
            schema_type != "object"
            or isinstance(raw_required, (str, bytes))
            or not isinstance(raw_required, Sequence)
            or any(not isinstance(item, str) or not item for item in raw_required)
        ):
            raise ValueError("Weather Tool schemaのrequiredが不正です。")
        required = list(raw_required)
        if len(required) != len(set(required)) or not set(required).issubset(properties or {}):
            raise ValueError("Weather Tool schemaのrequiredがpropertiesと一致しません。")

    items: agentcore.SchemaDefinition | None = None
    if "items" in value:
        if schema_type != "array":
            raise ValueError("Weather Tool schemaのitemsが不正です。")
        items = _schema_definition_from_json(value["items"])
    elif schema_type == "array":
        raise ValueError("Weather Toolのarray schemaにはitemsが必要です。")

    return agentcore.SchemaDefinition(
        type=_SCHEMA_TYPES[schema_type],
        description=description,
        properties=properties,
        required=required,
        items=items,
    )
