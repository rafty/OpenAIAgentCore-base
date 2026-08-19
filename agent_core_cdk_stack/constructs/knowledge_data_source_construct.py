"""Managed Knowledge Base向けS3 connector data sourceを定義する。"""

from aws_cdk import RemovalPolicy, Stack
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3_deployment
from constructs import Construct


KNOWLEDGE_DATA_SOURCE_NAME = "OpenAiKnowledgeDataSource"


class KnowledgeDataSourceConstruct(Construct):
    """専用bucketを取り込むmanaged connectorと削除保護を所有する。"""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        knowledge_base: bedrock.CfnKnowledgeBase,
        document_bucket: s3.IBucket,
        document_deployment: s3_deployment.BucketDeployment,
    ) -> None:
        super().__init__(scope, construct_id)

        stack = Stack.of(self)
        self.data_source = bedrock.CfnDataSource(
            self,
            "DataSource",
            name=KNOWLEDGE_DATA_SOURCE_NAME,
            knowledge_base_id=knowledge_base.attr_knowledge_base_id,
            data_deletion_policy="DELETE",
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="MANAGED_KNOWLEDGE_BASE_CONNECTOR",
                managed_knowledge_base_connector_configuration=bedrock.CfnDataSource.ManagedKnowledgeBaseConnectorConfigurationProperty(
                    # connectorParametersは固定CDK版でもJSON object型であるため、
                    # AWS公式S3 managed connectorのshapeをこの境界だけで組み立てる。
                    connector_parameters={
                        "type": "S3",
                        "version": "1",
                        "connectionConfiguration": {
                            "bucketName": document_bucket.bucket_name,
                            "bucketOwnerAccountId": stack.account,
                        },
                    },
                    deletion_protection_configuration=bedrock.CfnDataSource.DeletionProtectionConfigurationProperty(
                        deletion_protection_status="ENABLED",
                        # 5文書のうち意図的な1件削除は許容し、2件以上の
                        # 同期削除を止めて人の確認へ戻すため20%に固定する。
                        deletion_protection_threshold=20,
                    ),
                ),
            ),
        )
        self.data_source.apply_removal_policy(RemovalPolicy.DESTROY)
        # Data Source作成時に正本10ファイルがbucketへ存在するようにし、
        # deploy自体には非同期のingestion jobを組み込まない。
        self.data_source.node.add_dependency(knowledge_base, document_deployment)

    @property
    def data_source_id(self) -> str:
        """初回同期手順へ公開するCloudFormation上のData Source ID。"""

        return self.data_source.attr_data_source_id
