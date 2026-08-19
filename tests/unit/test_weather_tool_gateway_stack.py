"""Weather／Time Tool用Gateway、Lambda、IAMおよびassetのCDK契約テスト。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

from agent_core_cdk_stack.constructs.agent_core_weather_gateway_construct import (
    AgentCoreWeatherGatewayConstruct,
)
from agent_core_cdk_stack.constructs.weather_time_gateway_target_construct import (
    WeatherTimeGatewayTargetConstruct,
    _load_tool_definitions,
)
from agent_core_cdk_stack.constructs.weather_time_mock_lambda_construct import (
    WeatherTimeMockLambdaConstruct,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_TOOLS_SCHEMA_PATH = _REPOSITORY_ROOT / "lambda_tools" / "weather" / "tools.json"
_TEST_ACCOUNT_ID = "123456789012"
_TEST_REGION = "us-east-1"


def _single_resource(
    resources: dict[str, dict[str, Any]], resource_type: str
) -> tuple[str, dict[str, Any]]:
    """logical IDを固定せず、resource typeから単一resourceを特定する。"""

    matches = [
        (logical_id, resource)
        for logical_id, resource in resources.items()
        if resource["Type"] == resource_type
    ]
    assert len(matches) == 1
    return matches[0]


def _logical_id_from_get_att(value: Any, attribute: str) -> str:
    """Fn::GetAtt参照から参照先logical IDを取り出す。"""

    assert isinstance(value, dict)
    get_att = value.get("Fn::GetAtt")
    assert isinstance(get_att, list)
    assert len(get_att) == 2
    assert get_att[1] == attribute
    assert isinstance(get_att[0], str)
    return get_att[0]


def _logical_id_from_ref(value: Any) -> str:
    """Refから参照先logical IDを取り出す。"""

    assert isinstance(value, dict)
    logical_id = value.get("Ref")
    assert isinstance(logical_id, str)
    return logical_id


def _policies_for_role(
    resources: dict[str, dict[str, Any]], role_logical_id: str
) -> list[tuple[str, dict[str, Any]]]:
    """Role名ではなくCloudFormation参照を辿ってinline policyを抽出する。"""

    matches: list[tuple[str, dict[str, Any]]] = []
    for logical_id, resource in resources.items():
        if resource["Type"] != "AWS::IAM::Policy":
            continue
        role_refs = resource["Properties"].get("Roles", [])
        if any(_logical_id_from_ref(role_ref) == role_logical_id for role_ref in role_refs):
            matches.append((logical_id, resource))
    return matches


def _as_list(value: Any) -> list[Any]:
    """CloudFormationが単一値と配列を使い分けるpropertyを比較可能にする。"""

    return value if isinstance(value, list) else [value]


def _normalize_inline_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """CDKがPascalCase化したinline schemaを正本JSONの形へ戻す。"""

    normalized: dict[str, Any] = {"type": schema["Type"]}
    if "Description" in schema:
        normalized["description"] = schema["Description"]
    if "Properties" in schema:
        normalized["properties"] = {
            name: _normalize_inline_schema(property_schema)
            for name, property_schema in schema["Properties"].items()
        }
    if "Required" in schema:
        normalized["required"] = schema["Required"]
    if "Items" in schema:
        normalized["items"] = _normalize_inline_schema(schema["Items"])
    return normalized


def _normalize_inline_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """CloudFormation上のToolDefinitionをtools.jsonと比較できる形へ戻す。"""

    return {
        "name": tool["Name"],
        "description": tool["Description"],
        "inputSchema": _normalize_inline_schema(tool["InputSchema"]),
    }


def _weather_stack(
    tmp_path: Path,
) -> tuple[cdk.App, cdk.Stack, dict[str, dict[str, Any]], Path]:
    """Runtime配線と分離した最小Stackをtmp outdirへsynth可能に構成する。"""

    outdir = tmp_path / "cdk.out"
    app = cdk.App(outdir=str(outdir))
    stack = cdk.Stack(
        app,
        "WeatherToolGatewayContractStack",
        env=cdk.Environment(account=_TEST_ACCOUNT_ID, region=_TEST_REGION),
    )
    weather_lambda = WeatherTimeMockLambdaConstruct(stack, "WeatherTimeMockLambda")
    weather_gateway = AgentCoreWeatherGatewayConstruct(stack, "WeatherGateway")
    WeatherTimeGatewayTargetConstruct(
        stack,
        "WeatherTimeGatewayTarget",
        gateway=weather_gateway.gateway,
        lambda_function=weather_lambda.function,
    )
    rendered = Template.from_stack(stack).to_json()
    return app, stack, rendered["Resources"], outdir


def test_weather_gateway_lambda_iam_schema_and_asset_contract(tmp_path: Path) -> None:
    app, stack, resources, outdir = _weather_stack(tmp_path)

    lambda_logical_id, lambda_resource = _single_resource(
        resources, "AWS::Lambda::Function"
    )
    log_group_logical_id, log_group_resource = _single_resource(
        resources, "AWS::Logs::LogGroup"
    )
    gateway_logical_id, gateway_resource = _single_resource(
        resources, "AWS::BedrockAgentCore::Gateway"
    )
    _, target_resource = _single_resource(
        resources, "AWS::BedrockAgentCore::GatewayTarget"
    )

    lambda_properties = lambda_resource["Properties"]
    assert lambda_properties["FunctionName"] == "OpenAiWeatherTimeMock"
    assert lambda_properties["Runtime"] == "python3.12"
    assert lambda_properties["Architectures"] == ["arm64"]
    assert lambda_properties["MemorySize"] == 128
    assert lambda_properties["Timeout"] == 5
    assert lambda_properties["Handler"] == "handler.lambda_handler"
    assert "Environment" not in lambda_properties
    assert "VpcConfig" not in lambda_properties
    assert lambda_properties["LoggingConfig"] == {
        "LogGroup": {"Ref": log_group_logical_id}
    }

    assert log_group_resource["Properties"] == {
        "LogGroupName": "/aws/lambda/OpenAiWeatherTimeMock",
        "RetentionInDays": 7,
    }
    assert log_group_resource["DeletionPolicy"] == "Delete"
    assert log_group_resource["UpdateReplacePolicy"] == "Delete"

    # FunctionのRole参照から専用Roleを解決し、managed basic policyや
    # CreateLogGroupのwildcard権限が紛れ込んでいないことを境界ごと確認する。
    lambda_role_logical_id = _logical_id_from_get_att(
        lambda_properties["Role"], "Arn"
    )
    lambda_role = resources[lambda_role_logical_id]
    assert lambda_role["Type"] == "AWS::IAM::Role"
    lambda_role_properties = lambda_role["Properties"]
    assert "ManagedPolicyArns" not in lambda_role_properties
    assert lambda_role_properties["AssumeRolePolicyDocument"]["Statement"] == [
        {
            "Action": "sts:AssumeRole",
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
        }
    ]
    lambda_policies = _policies_for_role(resources, lambda_role_logical_id)
    assert len(lambda_policies) == 1
    lambda_statements = lambda_policies[0][1]["Properties"]["PolicyDocument"][
        "Statement"
    ]
    assert len(lambda_statements) == 1
    lambda_log_statement = lambda_statements[0]
    assert set(_as_list(lambda_log_statement["Action"])) == {
        "logs:CreateLogStream",
        "logs:PutLogEvents",
    }
    assert lambda_log_statement["Effect"] == "Allow"
    log_resources = _as_list(lambda_log_statement["Resource"])
    assert len(log_resources) == 1
    assert _logical_id_from_get_att(log_resources[0], "Arn") == log_group_logical_id
    assert "logs:CreateLogGroup" not in json.dumps(lambda_policies)

    gateway_properties = gateway_resource["Properties"]
    assert gateway_properties["Name"] == "OpenAiWeatherGateway"
    assert gateway_properties["AuthorizerType"] == "AWS_IAM"
    assert gateway_properties["ProtocolType"] == "MCP"
    assert gateway_properties["ProtocolConfiguration"] == {
        "Mcp": {"SupportedVersions": ["2025-11-25", "2025-03-26"]}
    }
    assert "ExceptionLevel" not in gateway_properties
    assert "DEBUG" not in json.dumps(gateway_resource)

    # GatewayのRoleArn参照から専用Roleを特定することで、Constructのlogical ID変更を
    # 許容しながらtrust条件とLambda限定permissionを固定する。
    gateway_role_logical_id = _logical_id_from_get_att(
        gateway_properties["RoleArn"], "Arn"
    )
    gateway_role = resources[gateway_role_logical_id]
    assert gateway_role["Type"] == "AWS::IAM::Role"
    gateway_role_properties = gateway_role["Properties"]
    assert "ManagedPolicyArns" not in gateway_role_properties
    gateway_trust_statements = gateway_role_properties["AssumeRolePolicyDocument"][
        "Statement"
    ]
    gateway_service_statements = [
        statement
        for statement in gateway_trust_statements
        if statement.get("Principal")
        == {"Service": "bedrock-agentcore.amazonaws.com"}
    ]
    assert len(gateway_service_statements) == 1
    gateway_trust = gateway_service_statements[0]
    assert gateway_trust["Action"] == "sts:AssumeRole"
    assert gateway_trust["Effect"] == "Allow"
    assert gateway_trust["Condition"]["StringEquals"] == {
        "aws:SourceAccount": _TEST_ACCOUNT_ID
    }
    source_arn = gateway_trust["Condition"]["ArnLike"]["aws:SourceArn"]
    source_arn_text = json.dumps(source_arn)
    assert "bedrock-agentcore" in source_arn_text
    assert _TEST_REGION in source_arn_text
    assert _TEST_ACCOUNT_ID in source_arn_text
    # Gateway表示名は大文字を保持するが、AWSが生成するgatewayId／ARNは
    # 小文字prefixになるため、実際のAssumeRole SourceArnに一致させる。
    assert "gateway/openaiweathergateway-*" in source_arn_text
    assert gateway_logical_id not in source_arn_text
    assert all("Condition" in statement for statement in gateway_service_statements)

    gateway_policies = _policies_for_role(resources, gateway_role_logical_id)
    assert len(gateway_policies) == 1
    gateway_policy_logical_id, gateway_policy = gateway_policies[0]
    gateway_statements = gateway_policy["Properties"]["PolicyDocument"]["Statement"]
    assert len(gateway_statements) == 1
    invoke_statement = gateway_statements[0]
    assert invoke_statement["Action"] == "lambda:InvokeFunction"
    assert invoke_statement["Effect"] == "Allow"
    lambda_arn = {"Fn::GetAtt": [lambda_logical_id, "Arn"]}
    assert invoke_statement["Resource"] == [
        lambda_arn,
        {"Fn::Join": ["", [lambda_arn, ":*"]]},
    ]
    # inline schemaのbootstrap S3配布と混同せず、Gateway Roleだけを検査する。
    serialized_gateway_role = json.dumps(
        {"role": gateway_role, "policies": gateway_policies}
    )
    assert "s3:" not in serialized_gateway_role.lower()
    assert "secretsmanager:" not in serialized_gateway_role.lower()
    assert "kms:" not in serialized_gateway_role.lower()

    target_properties = target_resource["Properties"]
    assert target_properties["Name"] == "WeatherTimeMock"
    assert target_properties["CredentialProviderConfigurations"] == [
        {"CredentialProviderType": "GATEWAY_IAM_ROLE"}
    ]
    assert _logical_id_from_get_att(
        target_properties["GatewayIdentifier"], "GatewayIdentifier"
    ) == gateway_logical_id
    lambda_target = target_properties["TargetConfiguration"]["Mcp"]["Lambda"]
    assert _logical_id_from_get_att(lambda_target["LambdaArn"], "Arn") == (
        lambda_logical_id
    )
    target_dependencies = _as_list(target_resource.get("DependsOn", []))
    assert gateway_policy_logical_id in target_dependencies

    source_tools = json.loads(_TOOLS_SCHEMA_PATH.read_text(encoding="utf-8"))
    inline_tools = lambda_target["ToolSchema"]["InlinePayload"]
    assert [_normalize_inline_tool(tool) for tool in inline_tools] == source_tools

    # Lambda CodeのS3Keyからmanifest entryを逆引きし、source directoryではなく
    # 実際にsynthされたassetの内容を検査する。
    app.synth()
    assets_manifest = json.loads(
        (outdir / f"{stack.stack_name}.assets.json").read_text(encoding="utf-8")
    )
    s3_key = lambda_properties["Code"]["S3Key"]
    assert isinstance(s3_key, str) and s3_key.endswith(".zip")
    asset_hash = s3_key.removesuffix(".zip")
    lambda_asset = assets_manifest["files"][asset_hash]
    assert lambda_asset["source"]["packaging"] == "zip"
    staged_asset = outdir / lambda_asset["source"]["path"]
    assert staged_asset.is_relative_to(outdir)
    assert staged_asset.is_dir()
    staged_files = {
        path.relative_to(staged_asset).as_posix()
        for path in staged_asset.rglob("*")
        if path.is_file()
    }
    assert "handler.py" in staged_files
    assert "tools.json" not in staged_files
    assert not any("__pycache__" in Path(path).parts for path in staged_files)
    assert not any(Path(path).suffix in {".pyc", ".pyo"} for path in staged_files)
    assert not any(Path(path).name == ".DS_Store" for path in staged_files)
    assert not any(
        Path(path).name.endswith(("~", ".tmp", ".swp")) for path in staged_files
    )


def test_unsupported_inline_schema_shape_fails_before_synth(tmp_path: Path) -> None:
    unsupported_schema = tmp_path / "unsupported-tools.json"
    unsupported_schema.write_text(
        json.dumps(
            [
                {
                    "name": "unsupported_tool",
                    "description": "Unsupported schema shape for a fail-fast test.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "value": {
                                "type": "string",
                                "enum": ["unsupported"],
                            }
                        },
                        "required": ["value"],
                    },
                }
            ]
        ),
        encoding="utf-8",
    )

    # 未対応keywordを黙って捨てず、CloudFormationやassetを生成する前に拒否する。
    with pytest.raises(ValueError, match="未対応"):
        _load_tool_definitions(unsupported_schema)
    assert not (tmp_path / "cdk.out").exists()
