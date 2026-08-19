"""Managed Knowledge BaseとKnowledge GatewayのCDK契約を検証する。"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

from agent_core_cdk_stack.constructs.agent_core_knowledge_gateway_construct import (
    AgentCoreKnowledgeGatewayConstruct,
)
from agent_core_cdk_stack.constructs.knowledge_data_source_construct import (
    KnowledgeDataSourceConstruct,
)
from agent_core_cdk_stack.constructs import knowledge_document_bucket_construct
from agent_core_cdk_stack.constructs.knowledge_document_bucket_construct import (
    KNOWLEDGE_DOCUMENT_PATHS,
    KnowledgeDocumentBucketConstruct,
)
from agent_core_cdk_stack.constructs.knowledge_retrieve_gateway_target_construct import (
    KnowledgeRetrieveGatewayTargetConstruct,
)
from agent_core_cdk_stack.constructs.managed_knowledge_base_construct import (
    ManagedKnowledgeBaseConstruct,
)


ACCOUNT = "123456789012"
REGION = "us-east-1"


def _stack(app: cdk.App, stack_id: str) -> cdk.Stack:
    return cdk.Stack(
        app,
        stack_id,
        env=cdk.Environment(account=ACCOUNT, region=REGION),
    )


def _only_resource(rendered: dict, resource_type: str) -> tuple[str, dict]:
    matches = [
        (logical_id, resource)
        for logical_id, resource in rendered["Resources"].items()
        if resource["Type"] == resource_type
    ]
    assert len(matches) == 1
    return matches[0]


def _asset_manifest_entry(outdir: Path, stack_id: str) -> tuple[str, dict]:
    manifest = json.loads((outdir / f"{stack_id}.assets.json").read_text())
    matches = [
        (asset_id, entry)
        for asset_id, entry in manifest["files"].items()
        if entry["displayName"].endswith("/Deployment/Asset1")
    ]
    assert len(matches) == 1
    return matches[0]


def _synth_document_asset(outdir: Path, stack_id: str) -> tuple[dict, str, Path]:
    app = cdk.App(outdir=str(outdir))
    stack = _stack(app, stack_id)
    KnowledgeDocumentBucketConstruct(stack, "Docs")
    rendered = Template.from_stack(stack).to_json()
    app.synth()
    asset_id, entry = _asset_manifest_entry(outdir, stack_id)
    return rendered, asset_id, outdir / entry["source"]["path"]


def test_knowledge_document_bucket_and_deployment_contract(tmp_path: Path) -> None:
    outdir = tmp_path / "cdk.out"
    rendered, asset_id, staged_asset = _synth_document_asset(outdir, "DocsStack")

    bucket_id, bucket = _only_resource(rendered, "AWS::S3::Bucket")
    assert bucket["Properties"]["BucketEncryption"] == {
        "ServerSideEncryptionConfiguration": [
            {"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
        ]
    }
    assert bucket["Properties"]["PublicAccessBlockConfiguration"] == {
        "BlockPublicAcls": True,
        "BlockPublicPolicy": True,
        "IgnorePublicAcls": True,
        "RestrictPublicBuckets": True,
    }
    assert bucket["DeletionPolicy"] == "Delete"
    assert bucket["UpdateReplacePolicy"] == "Delete"

    _, bucket_policy = _only_resource(rendered, "AWS::S3::BucketPolicy")
    ssl_denies = [
        statement
        for statement in bucket_policy["Properties"]["PolicyDocument"]["Statement"]
        if statement["Effect"] == "Deny"
    ]
    assert len(ssl_denies) == 1
    assert ssl_denies[0]["Action"] == "s3:*"
    assert ssl_denies[0]["Condition"] == {
        "Bool": {"aws:SecureTransport": "false"}
    }
    assert {"Ref": bucket_id} == bucket_policy["Properties"]["Bucket"]

    _, deployment = _only_resource(rendered, "Custom::CDKBucketDeployment")
    properties = deployment["Properties"]
    assert properties["DestinationBucketName"] == {"Ref": bucket_id}
    assert properties["Prune"] is True
    assert properties["RetainOnDelete"] is False
    assert deployment["DeletionPolicy"] == "Delete"
    assert properties["SourceObjectKeys"] == [f"{asset_id}.zip"]
    assert re.fullmatch(r"[0-9a-f]{64}", asset_id)

    # CDKがstageしたassetを直接調べ、rootからの相対pathと10ファイル限定を固定する。
    assert staged_asset.is_dir()
    staged_paths = {
        path.relative_to(staged_asset).as_posix()
        for path in staged_asset.rglob("*")
        if path.is_file()
    }
    assert staged_paths == KNOWLEDGE_DOCUMENT_PATHS


def test_knowledge_document_asset_hash_changes_with_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "knowledge-base-s3"
    shutil.copytree(
        knowledge_document_bucket_construct.KNOWLEDGE_DOCUMENTS_DIRECTORY,
        source,
    )
    monkeypatch.setattr(
        knowledge_document_bucket_construct,
        "KNOWLEDGE_DOCUMENTS_DIRECTORY",
        source,
    )

    _, first_hash, _ = _synth_document_asset(tmp_path / "first", "FirstStack")
    document = source / "standards" / "security_standard.md"
    document.write_text(document.read_text() + "\n", encoding="utf-8")
    _, second_hash, _ = _synth_document_asset(tmp_path / "second", "SecondStack")

    assert first_hash != second_hash


def test_knowledge_document_validation_fails_before_asset_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "knowledge-base-s3"
    shutil.copytree(
        knowledge_document_bucket_construct.KNOWLEDGE_DOCUMENTS_DIRECTORY,
        source,
    )
    (source / "unexpected.tmp").write_text("generated", encoding="utf-8")
    monkeypatch.setattr(
        knowledge_document_bucket_construct,
        "KNOWLEDGE_DOCUMENTS_DIRECTORY",
        source,
    )

    app = cdk.App(outdir=str(tmp_path / "invalid"))
    stack = _stack(app, "InvalidDocsStack")
    with pytest.raises(ValueError, match="登録対象が仕様と一致しません"):
        KnowledgeDocumentBucketConstruct(stack, "Docs")

    assert not (tmp_path / "invalid" / "InvalidDocsStack.assets.json").exists()


def _managed_stack(outdir: Path) -> tuple[cdk.App, cdk.Stack, dict]:
    app = cdk.App(outdir=str(outdir))
    stack = _stack(app, "ManagedStack")
    documents = KnowledgeDocumentBucketConstruct(stack, "Docs")
    managed = ManagedKnowledgeBaseConstruct(
        stack,
        "ManagedKnowledgeBase",
        document_bucket=documents.bucket,
    )
    KnowledgeDataSourceConstruct(
        stack,
        "DataSource",
        knowledge_base=managed.knowledge_base,
        document_bucket=documents.bucket,
        document_deployment=documents.deployment,
    )
    return app, stack, Template.from_stack(stack).to_json()


def test_managed_knowledge_base_and_data_source_contract(tmp_path: Path) -> None:
    _, _, rendered = _managed_stack(tmp_path / "managed")
    resources = rendered["Resources"]
    bucket_id, _ = _only_resource(rendered, "AWS::S3::Bucket")
    knowledge_base_id, knowledge_base = _only_resource(
        rendered, "AWS::Bedrock::KnowledgeBase"
    )
    data_source_id, data_source = _only_resource(rendered, "AWS::Bedrock::DataSource")

    assert knowledge_base["Properties"]["Name"] == "OpenAiKnowledgeBase"
    assert knowledge_base["Properties"]["KnowledgeBaseConfiguration"] == {
        "Type": "MANAGED",
        "ManagedKnowledgeBaseConfiguration": {"EmbeddingModelType": "MANAGED"},
    }
    assert "StorageConfiguration" not in knowledge_base["Properties"]
    assert knowledge_base["DeletionPolicy"] == "Delete"
    assert knowledge_base["UpdateReplacePolicy"] == "Delete"

    service_role_id = knowledge_base["Properties"]["RoleArn"]["Fn::GetAtt"][0]
    trust = resources[service_role_id]["Properties"]["AssumeRolePolicyDocument"][
        "Statement"
    ]
    assert trust == [
        {
            "Action": "sts:AssumeRole",
            "Condition": {
                "ArnLike": {
                    "aws:SourceArn": {
                        "Fn::Join": [
                            "",
                            [
                                "arn:",
                                {"Ref": "AWS::Partition"},
                                f":bedrock:{REGION}:{ACCOUNT}:knowledge-base/*",
                            ],
                        ]
                    }
                },
                "StringEquals": {"aws:SourceAccount": ACCOUNT},
            },
            "Effect": "Allow",
            "Principal": {"Service": "bedrock.amazonaws.com"},
        }
    ]
    role_policies = [
        resource
        for resource in resources.values()
        if resource["Type"] == "AWS::IAM::Policy"
        and {"Ref": service_role_id} in resource["Properties"]["Roles"]
    ]
    assert len(role_policies) == 1
    statements = role_policies[0]["Properties"]["PolicyDocument"]["Statement"]
    assert {statement["Action"] for statement in statements} == {
        "s3:ListBucket",
        "s3:GetObject",
    }
    list_statement = next(s for s in statements if s["Action"] == "s3:ListBucket")
    get_statement = next(s for s in statements if s["Action"] == "s3:GetObject")
    assert list_statement["Resource"] == {"Fn::GetAtt": [bucket_id, "Arn"]}
    assert get_statement["Resource"] == {
        "Fn::Join": ["", [{"Fn::GetAtt": [bucket_id, "Arn"]}, "/*"]]
    }

    configuration = data_source["Properties"]["DataSourceConfiguration"]
    assert configuration["Type"] == "MANAGED_KNOWLEDGE_BASE_CONNECTOR"
    managed_connector = configuration["ManagedKnowledgeBaseConnectorConfiguration"]
    assert managed_connector["ConnectorParameters"] == {
        "type": "S3",
        "version": "1",
        "connectionConfiguration": {
            "bucketName": {"Ref": bucket_id},
            "bucketOwnerAccountId": ACCOUNT,
        },
    }
    assert managed_connector["DeletionProtectionConfiguration"] == {
        "DeletionProtectionStatus": "ENABLED",
        "DeletionProtectionThreshold": 20,
    }
    assert data_source["Properties"]["DataDeletionPolicy"] == "DELETE"
    assert data_source["Properties"]["KnowledgeBaseId"] == {
        "Fn::GetAtt": [knowledge_base_id, "KnowledgeBaseId"]
    }
    assert data_source["DeletionPolicy"] == "Delete"
    assert data_source["UpdateReplacePolicy"] == "Delete"
    dependencies = set(data_source["DependsOn"])
    deployment_id, _ = _only_resource(rendered, "Custom::CDKBucketDeployment")
    assert {knowledge_base_id, deployment_id}.issubset(dependencies)

    serialized = json.dumps(rendered)
    assert "InvokeModel" not in serialized
    assert "StorageConfiguration" not in serialized
    assert "AWS::CloudFormation::CustomResource" not in serialized
    assert "StartIngestionJob" not in serialized
    assert data_source_id in resources


def test_knowledge_gateway_and_retrieve_target_contract(tmp_path: Path) -> None:
    app = cdk.App(outdir=str(tmp_path / "gateway"))
    stack = _stack(app, "GatewayStack")
    documents = KnowledgeDocumentBucketConstruct(stack, "Docs")
    managed = ManagedKnowledgeBaseConstruct(
        stack,
        "ManagedKnowledgeBase",
        document_bucket=documents.bucket,
    )
    gateway_construct = AgentCoreKnowledgeGatewayConstruct(
        stack,
        "KnowledgeGateway",
        knowledge_base=managed.knowledge_base,
    )
    target_construct = KnowledgeRetrieveGatewayTargetConstruct(
        stack,
        "RetrieveTarget",
        gateway=gateway_construct.gateway,
        knowledge_base=managed.knowledge_base,
        backend_policy=gateway_construct.backend_policy,
    )
    rendered = Template.from_stack(stack).to_json()
    resources = rendered["Resources"]

    knowledge_base_id, _ = _only_resource(rendered, "AWS::Bedrock::KnowledgeBase")
    gateway_id, gateway = _only_resource(rendered, "AWS::BedrockAgentCore::Gateway")
    target_id, target = _only_resource(
        rendered, "AWS::BedrockAgentCore::GatewayTarget"
    )
    assert gateway["Properties"]["Name"] == "OpenAiKnowledgeGateway"
    assert gateway["Properties"]["AuthorizerType"] == "AWS_IAM"
    assert gateway["Properties"]["ProtocolType"] == "MCP"

    execution_role_id = gateway["Properties"]["RoleArn"]["Fn::GetAtt"][0]
    trust = resources[execution_role_id]["Properties"]["AssumeRolePolicyDocument"][
        "Statement"
    ][0]
    assert trust["Principal"] == {"Service": "bedrock-agentcore.amazonaws.com"}
    assert trust["Condition"] == {
        "ArnLike": {
            "aws:SourceArn": {
                "Fn::Join": [
                    "",
                    [
                        "arn:",
                        {"Ref": "AWS::Partition"},
                        f":bedrock-agentcore:{REGION}:{ACCOUNT}:gateway/"
                        "openaiknowledgegateway-*",
                    ],
                ]
            }
        },
        "StringEquals": {"aws:SourceAccount": ACCOUNT},
    }

    backend_policies = [
        (logical_id, resource)
        for logical_id, resource in resources.items()
        if resource["Type"] == "AWS::IAM::Policy"
        and {"Ref": execution_role_id} in resource["Properties"]["Roles"]
    ]
    assert len(backend_policies) == 1
    backend_policy_id, backend_policy = backend_policies[0]
    assert backend_policy["Properties"]["PolicyDocument"]["Statement"] == [
        {
            "Action": ["bedrock:GetKnowledgeBase", "bedrock:Retrieve"],
            "Effect": "Allow",
            "Resource": {
                "Fn::GetAtt": [knowledge_base_id, "KnowledgeBaseArn"]
            },
        }
    ]

    properties = target["Properties"]
    assert properties["Name"] == "KnowledgeRetrieve"
    assert properties["Description"] == "Managed Knowledge BaseのRetrieveを最大5件で公開します。"
    assert properties["GatewayIdentifier"] == {
        "Fn::GetAtt": [gateway_id, "GatewayIdentifier"]
    }
    assert properties["CredentialProviderConfigurations"] == [
        {"CredentialProviderType": "GATEWAY_IAM_ROLE"}
    ]
    connector = properties["TargetConfiguration"]["Mcp"]["Connector"]
    assert connector["Source"] == {"ConnectorId": "bedrock-knowledge-bases"}
    assert connector["Enabled"] == ["Retrieve"]
    assert len(connector["Configurations"]) == 1
    retrieve = connector["Configurations"][0]
    assert retrieve["Name"] == "Retrieve"
    assert retrieve["Description"] == "社内AWS標準、見積基準、過去案件を最大5件検索します。"
    assert retrieve["ParameterValues"] == {
        "knowledgeBaseId": {
            "Fn::GetAtt": [knowledge_base_id, "KnowledgeBaseId"]
        },
        "retrievalConfiguration": {
            "managedSearchConfiguration": {
                "overrideSearchType": "HYBRID",
            }
        },
    }
    assert retrieve["ParameterOverrides"] == [
        {
            "Description": "空白ではない検索文字列。",
            "Path": "$.retrievalQuery.text",
            "Visible": True,
        },
        {
            "Description": "許可されたmetadataだけを使用する検索filter。",
            "Path": "$.retrievalConfiguration.managedSearchConfiguration.filter",
            "Visible": True,
        },
    ]
    assert backend_policy_id in target["DependsOn"]

    serialized = json.dumps(target)
    assert "KnowledgeRetrieve___Retrieve" not in serialized
    assert "AgenticRetrieveStream" not in serialized
    assert "userContext" not in serialized
    # CloudFormationがDocument内の数値を文字列化するため、Bedrock既定の5件を使う。
    assert "numberOfResults" not in json.dumps(retrieve["ParameterValues"])
    assert "numberOfResults" not in json.dumps(retrieve["ParameterOverrides"])
    assert target_id in resources
