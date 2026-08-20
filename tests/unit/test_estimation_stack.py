"""Estimationインフラの固定CloudFormation・IAM契約を検証する。"""

import json

import aws_cdk as cdk
from aws_cdk.assertions import Template

from agent_core_cdk_stack.agent_core_stack import AgentCoreStack


def _render(tmp_path):
    app = cdk.App(outdir=str(tmp_path))
    stack = AgentCoreStack(
        app,
        "OpenAiAgentCoreBaseStack",
        env=cdk.Environment(region="us-east-1"),
    )
    return Template.from_stack(stack).to_json()


def _actions(statements):
    return {
        action
        for statement in statements
        for action in (
            statement["Action"]
            if isinstance(statement["Action"], list)
            else [statement["Action"]]
        )
    }


def test_estimation_resources_and_fixed_vector_contract(tmp_path) -> None:
    rendered = _render(tmp_path)
    resources = rendered["Resources"]
    tables = [item for item in resources.values() if item["Type"] == "AWS::DynamoDB::Table"]
    estimation_table = next(item for item in tables if item["Properties"].get("TableName") == "OpenAiEstimationData")
    assert estimation_table["Properties"]["BillingMode"] == "PAY_PER_REQUEST"
    assert estimation_table["Properties"]["KeySchema"] == [
        {"AttributeName": "PK", "KeyType": "HASH"},
        {"AttributeName": "SK", "KeyType": "RANGE"},
    ]
    assert estimation_table["Properties"]["AttributeDefinitions"] == [
        {"AttributeName": "PK", "AttributeType": "S"},
        {"AttributeName": "SK", "AttributeType": "S"},
    ]
    assert estimation_table["Properties"]["TimeToLiveSpecification"] == {
        "AttributeName": "expires_at_epoch",
        "Enabled": True,
    }
    assert estimation_table["Properties"]["PointInTimeRecoverySpecification"] == {
        "PointInTimeRecoveryEnabled": False
    }
    assert estimation_table["DeletionPolicy"] == "Delete"

    indexes = [item for item in resources.values() if item["Type"] == "Custom::DynamoDbVectorIndex"]
    assert len(indexes) == 1
    properties = indexes[0]["Properties"]
    assert properties["IndexName"] == "EstimationProjectVectorIndexV1"
    assert properties["VectorAttribute"] == "embedding"
    assert properties["Dimensions"] == 1024
    assert properties["DistanceFunction"] == "COSINE"
    assert properties["SearchSchema"] == [
        {"AttributeName": "search_scope", "SearchSchemaElementType": "HASH"},
        {"AttributeName": "entity_type", "SearchSchemaElementType": "INLINE_FILTER"},
        {"AttributeName": "project_type", "SearchSchemaElementType": "INLINE_FILTER"},
        {"AttributeName": "architecture_family", "SearchSchemaElementType": "INLINE_FILTER"},
        {"AttributeName": "outcome_quality", "SearchSchemaElementType": "INLINE_FILTER"},
    ]
    assert all("Seed" not in item["Type"] for item in resources.values())


def test_gateway_lambda_logs_and_iam_are_separated(tmp_path) -> None:
    rendered = _render(tmp_path)
    resources = rendered["Resources"]
    lambdas = [item for item in resources.values() if item["Type"] == "AWS::Lambda::Function"]
    tool_lambda = next(item for item in lambdas if item["Properties"].get("FunctionName") == "OpenAiEstimationTools")
    assert tool_lambda["Properties"]["Timeout"] == 60
    assert tool_lambda["Properties"]["Architectures"] == ["arm64"]
    logs = [item for item in resources.values() if item["Type"] == "AWS::Logs::LogGroup"]
    assert next(item for item in logs if item["Properties"].get("LogGroupName") == "/aws/lambda/OpenAiEstimationTools")["Properties"]["RetentionInDays"] == 7

    gateways = [item for item in resources.values() if item["Type"] == "AWS::BedrockAgentCore::Gateway"]
    assert any(item["Properties"]["Name"] == "OpenAiEstimationGateway" for item in gateways)
    targets = [item for item in resources.values() if item["Type"] == "AWS::BedrockAgentCore::GatewayTarget"]
    target = next(item for item in targets if item["Properties"]["Name"] == "EstimationTools")
    schemas = target["Properties"]["TargetConfiguration"]["Mcp"]["Lambda"]["ToolSchema"]["InlinePayload"]
    assert [item["Name"] for item in schemas] == [
        "search_similar_projects",
        "get_estimation_reference_data",
        "create_estimate_draft",
        "get_estimate_draft",
    ]

    policies = [item for item in resources.values() if item["Type"] == "AWS::IAM::Policy"]
    statements = [statement for policy in policies for statement in policy["Properties"]["PolicyDocument"]["Statement"]]
    leading = next(statement for statement in statements if "dynamodb:LeadingKeys" in json.dumps(statement))
    assert leading["Condition"]["ForAllValues:StringLike"]["dynamodb:LeadingKeys"] == [
        "SEARCH_CONTEXT#*",
        "ESTIMATE_PROJECT#*",
        "IDEMPOTENCY#*",
    ]
    assert any(statement.get("Action") == "dynamodb:SearchVectors" and "EstimationProjectVectorIndexV1" in json.dumps(statement) for statement in statements)
    assert any(statement.get("Action") == "bedrock:InvokeModel" and "cohere.embed-multilingual-v3" in json.dumps(statement) for statement in statements)
    provider = next(statement for statement in statements if statement.get("Action") == ["dynamodb:DescribeTable", "dynamodb:UpdateTable"])
    assert provider["Effect"] == "Allow"

    runtime = next(item for item in resources.values() if item["Type"] == "AWS::BedrockAgentCore::Runtime")
    role_id = runtime["Properties"]["RoleArn"]["Fn::GetAtt"][0]
    runtime_statements = [
        statement
        for policy in policies
        if {"Ref": role_id} in policy["Properties"]["Roles"]
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
    ]
    assert not any(action.startswith("dynamodb:") for action in _actions(runtime_statements))
    assert "bedrock:InvokeModel" not in _actions(runtime_statements)
    assert runtime["Properties"]["EnvironmentVariables"]["AGENTCORE_ESTIMATION_GATEWAY_TARGET_NAME"] == "EstimationTools"
