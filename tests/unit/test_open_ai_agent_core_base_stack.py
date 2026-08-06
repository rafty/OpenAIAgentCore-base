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
    runtimes = [r for r in resources.values() if r["Type"] == "AWS::BedrockAgentCore::Runtime"]
    endpoints = [r for r in resources.values() if r["Type"] == "AWS::BedrockAgentCore::RuntimeEndpoint"]
    assert len(memories) == 1
    assert len(runtimes) == 1
    assert endpoints == []

    memory = memories[0]
    assert memory["Properties"]["EventExpiryDuration"] == 30
    assert "MemoryStrategies" not in memory["Properties"]
    assert "EncryptionKeyArn" not in memory["Properties"]
    assert memory["DeletionPolicy"] == "Delete"
    assert memory["UpdateReplacePolicy"] == "Delete"

    runtime = runtimes[0]["Properties"]
    assert runtime["ProtocolConfiguration"] == "HTTP"
    assert runtime["NetworkConfiguration"] == {"NetworkMode": "PUBLIC"}
    # IAM authorizerとtracing=falseはCloudFormation既定値のためL2がpropertyを省略する。
    assert "AuthorizerConfiguration" not in runtime
    assert "TracingConfiguration" not in runtime
    assert runtime["EnvironmentVariables"] == {
        "AWS_REGION": "us-east-2",
        "BEDROCK_OPENAI_MODEL_ID": "openai.gpt-5.5",
        "OPENAI_AGENTS_DISABLE_TRACING": "1",
        "AGENTCORE_MEMORY_ID": runtime["EnvironmentVariables"]["AGENTCORE_MEMORY_ID"],
    }
    assert "Fn::GetAtt" in runtime["EnvironmentVariables"]["AGENTCORE_MEMORY_ID"]

    # 管理policy、Memory操作権限、秘密情報の非混入をテンプレート全体で確認する。
    serialized = json.dumps(rendered)
    assert "AmazonBedrockMantleInferenceAccess" in serialized
    assert "bedrock-agentcore:ListEvents" in serialized
    assert "bedrock-agentcore:CreateEvent" in serialized
    assert "OPENAI_API_KEY" not in serialized
    assert "AWS_ACCESS_KEY_ID" not in serialized
    assert stack.region == "us-east-2"

    # CloudFormation本体には出ないDocker build platformをasset manifestで確認する。
    app.synth()
    assets = json.loads((tmp_path / "OpenAiAgentCoreBaseStack.assets.json").read_text())
    docker_images = list(assets["dockerImages"].values())
    assert len(docker_images) == 1
    assert docker_images[0]["source"]["platform"] == "linux/arm64"
