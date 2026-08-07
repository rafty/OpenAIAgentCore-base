"""AgentCoreのCloudFormation構成とDocker asset契約を確認するCDKテスト。"""

import json

import aws_cdk as cdk
from aws_cdk.assertions import Template

from agent_core_cdk_stack.agent_core_stack import AgentCoreStack


def _stack(app: cdk.App) -> AgentCoreStack:
    return AgentCoreStack(
        app,
        "OpenAiAgentCoreBaseStack",
        env=cdk.Environment(region="us-east-2"),
    )


def test_agentcore_resources_and_properties(tmp_path) -> None:
    app = cdk.App(outdir=str(tmp_path))
    stack = _stack(app)
    rendered = Template.from_stack(stack).to_json()
    resources = rendered["Resources"]

    # logical IDへ依存せずresource typeから対象を特定し、Construct内の命名変更を許容する。
    memories = [r for r in resources.values() if r["Type"] == "AWS::BedrockAgentCore::Memory"]
    runtime_entries = [
        (logical_id, resource)
        for logical_id, resource in resources.items()
        if resource["Type"] == "AWS::BedrockAgentCore::Runtime"
    ]
    gateway_entries = [
        (logical_id, resource)
        for logical_id, resource in resources.items()
        if resource["Type"] == "AWS::BedrockAgentCore::Gateway"
    ]
    target_entries = [
        (logical_id, resource)
        for logical_id, resource in resources.items()
        if resource["Type"] == "AWS::BedrockAgentCore::GatewayTarget"
    ]
    endpoints = [r for r in resources.values() if r["Type"] == "AWS::BedrockAgentCore::RuntimeEndpoint"]
    assert len(memories) == 1
    assert len(runtime_entries) == 1
    assert len(gateway_entries) == 1
    assert len(target_entries) == 1
    assert endpoints == []

    memory = memories[0]
    assert memory["Properties"]["EventExpiryDuration"] == 30
    assert "MemoryStrategies" not in memory["Properties"]
    assert "EncryptionKeyArn" not in memory["Properties"]
    assert memory["DeletionPolicy"] == "Delete"
    assert memory["UpdateReplacePolicy"] == "Delete"

    _, runtime_resource = runtime_entries[0]
    gateway_logical_id, gateway_resource = gateway_entries[0]
    target_logical_id, _ = target_entries[0]
    runtime = runtime_resource["Properties"]
    assert runtime["ProtocolConfiguration"] == "HTTP"
    assert runtime["NetworkConfiguration"] == {"NetworkMode": "PUBLIC"}
    # IAM authorizerとtracing=falseはCloudFormation既定値のためL2がpropertyを省略する。
    assert "AuthorizerConfiguration" not in runtime
    assert "TracingConfiguration" not in runtime
    environment = runtime["EnvironmentVariables"]
    assert environment == {
        "AWS_REGION": "us-east-2",
        "BEDROCK_OPENAI_MODEL_ID": "openai.gpt-5.5",
        "OPENAI_AGENTS_DISABLE_TRACING": "1",
        "AGENTCORE_MEMORY_ID": environment["AGENTCORE_MEMORY_ID"],
        "AGENTCORE_GATEWAY_URL": {
            "Fn::GetAtt": [gateway_logical_id, "GatewayUrl"],
        },
        "AGENTCORE_GATEWAY_TARGET_NAME": "WeatherTimeMock",
    }
    assert "Fn::GetAtt" in environment["AGENTCORE_MEMORY_ID"]

    # URL文字列ではなく同一Gatewayのtokenを照合し、別Gatewayへの誤配線を検出する。
    assert runtime_resource["DependsOn"][-1] == target_logical_id
    assert gateway_resource["Properties"]["Name"] == "OpenAiWeatherGateway"

    runtime_role_logical_id = runtime["RoleArn"]["Fn::GetAtt"][0]
    runtime_policies = [
        resource
        for resource in resources.values()
        if resource["Type"] == "AWS::IAM::Policy"
        and {"Ref": runtime_role_logical_id} in resource["Properties"]["Roles"]
    ]
    assert len(runtime_policies) == 1
    statements = runtime_policies[0]["Properties"]["PolicyDocument"]["Statement"]
    gateway_statements = [
        statement
        for statement in statements
        if statement["Action"] == "bedrock-agentcore:InvokeGateway"
    ]
    assert gateway_statements == [
        {
            "Action": "bedrock-agentcore:InvokeGateway",
            "Effect": "Allow",
            "Resource": {"Fn::GetAtt": [gateway_logical_id, "GatewayArn"]},
        }
    ]

    # 管理policy、Memory操作権限、秘密情報の非混入をテンプレート全体で確認する。
    serialized = json.dumps(rendered)
    assert "AmazonBedrockMantleInferenceAccess" in serialized
    assert "bedrock-agentcore:ListEvents" in serialized
    assert "bedrock-agentcore:CreateEvent" in serialized
    assert "OPENAI_API_KEY" not in serialized
    assert "AWS_ACCESS_KEY_ID" not in serialized
    assert "AWS_SECRET_ACCESS_KEY" not in serialized
    assert "DEBUG" not in serialized
    assert stack.region == "us-east-2"

    # CloudFormation本体には出ないDocker build platformをasset manifestで確認する。
    app.synth()
    assets = json.loads((tmp_path / "OpenAiAgentCoreBaseStack.assets.json").read_text())
    docker_images = list(assets["dockerImages"].values())
    assert len(docker_images) == 1
    assert docker_images[0]["source"]["platform"] == "linux/arm64"
