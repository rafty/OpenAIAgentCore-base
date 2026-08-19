"""Managed Knowledge Baseと最小権限service roleを定義する。"""

from aws_cdk import ArnFormat, RemovalPolicy, Stack
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from constructs import Construct


MANAGED_KNOWLEDGE_BASE_NAME = "OpenAiKnowledgeBase"


class ManagedKnowledgeBaseConstruct(Construct):
    """サービス管理Embeddingを使う単一Managed Knowledge Baseを所有する。"""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        document_bucket: s3.IBucket,
    ) -> None:
        super().__init__(scope, construct_id)

        stack = Stack.of(self)
        # Knowledge Base IDはresource作成前に得られないため、wildcardは同一
        # partition／region／accountのknowledge-base resource内だけに閉じる。
        knowledge_base_arn_pattern = stack.format_arn(
            service="bedrock",
            resource="knowledge-base",
            resource_name="*",
            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
        )
        self.service_role = iam.Role(
            self,
            "ServiceRole",
            assumed_by=iam.ServicePrincipal(
                "bedrock.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": stack.account},
                    "ArnLike": {"aws:SourceArn": knowledge_base_arn_pattern},
                },
            ),
        )
        self.service_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:ListBucket"],
                resources=[document_bucket.bucket_arn],
            )
        )
        self.service_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject"],
                resources=[document_bucket.arn_for_objects("*")],
            )
        )

        # service-managed embeddingではBedrockがモデルを選ぶため、このroleへ
        # InvokeModelや顧客管理Vector Storeの権限を付けない。
        self.knowledge_base = bedrock.CfnKnowledgeBase(
            self,
            "KnowledgeBase",
            name=MANAGED_KNOWLEDGE_BASE_NAME,
            role_arn=self.service_role.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="MANAGED",
                managed_knowledge_base_configuration=bedrock.CfnKnowledgeBase.ManagedKnowledgeBaseConfigurationProperty(
                    embedding_model_type="MANAGED"
                ),
            ),
        )
        self.knowledge_base.apply_removal_policy(RemovalPolicy.DESTROY)
