"""Managed Knowledge BaseのRetrieveだけをGateway Targetとして公開する。"""

from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_iam as iam
from constructs import Construct


KNOWLEDGE_RETRIEVE_GATEWAY_TARGET_NAME = "KnowledgeRetrieve"
KNOWLEDGE_RETRIEVE_TOOL_NAME = (
    f"{KNOWLEDGE_RETRIEVE_GATEWAY_TARGET_NAME}___Retrieve"
)


class KnowledgeRetrieveGatewayTargetConstruct(Construct):
    """管理者固定の検索設定を持つRetrieve connectorを所有する。"""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        gateway: agentcore.IGateway,
        knowledge_base: bedrock.CfnKnowledgeBase,
        backend_policy: iam.Policy,
    ) -> None:
        super().__init__(scope, construct_id)

        self.target_name = KNOWLEDGE_RETRIEVE_GATEWAY_TARGET_NAME
        # 固定CDK版ではparameterValuesがJSON object型なので、AWS公式Connector
        # shapeをこのConstructだけで組み立て、他のTargetへ曖昧なdictを広げない。
        retrieve_configuration = agentcore.CfnGatewayTarget.ConnectorConfigurationProperty(
            name="Retrieve",
            description="社内AWS標準、見積基準、過去案件を最大5件検索します。",
            parameter_values={
                "knowledgeBaseId": knowledge_base.attr_knowledge_base_id,
                "retrievalConfiguration": {
                    "managedSearchConfiguration": {
                        # CloudFormation resource providerはDocument内の数値を文字列化し、
                        # GatewayからBedrockへ不正な"5"を送る。既定値が5であるため省略し、
                        # override非公開のまま有効な型と取得上限を維持する。
                        "overrideSearchType": "HYBRID",
                    }
                },
            },
            parameter_overrides=[
                agentcore.CfnGatewayTarget.ConnectorParameterOverrideProperty(
                    path="$.retrievalQuery.text",
                    description="空白ではない検索文字列。",
                    visible=True,
                ),
                agentcore.CfnGatewayTarget.ConnectorParameterOverrideProperty(
                    path="$.retrievalConfiguration.managedSearchConfiguration.filter",
                    description="許可されたmetadataだけを使用する検索filter。",
                    visible=True,
                ),
            ],
        )
        self.target = agentcore.CfnGatewayTarget(
            self,
            "Target",
            name=self.target_name,
            description="Managed Knowledge BaseのRetrieveを最大5件で公開します。",
            gateway_identifier=gateway.gateway_id,
            credential_provider_configurations=[
                agentcore.CfnGatewayTarget.CredentialProviderConfigurationProperty(
                    credential_provider_type="GATEWAY_IAM_ROLE"
                )
            ],
            target_configuration=agentcore.CfnGatewayTarget.TargetConfigurationProperty(
                mcp=agentcore.CfnGatewayTarget.McpTargetConfigurationProperty(
                    connector=agentcore.CfnGatewayTarget.ConnectorTargetConfigurationProperty(
                        source=agentcore.CfnGatewayTarget.ConnectorSourceProperty(
                            connector_id="bedrock-knowledge-bases"
                        ),
                        configurations=[retrieve_configuration],
                        enabled=["Retrieve"],
                    )
                )
            ),
        )
        # Target作成直後からbackendを呼べるよう、Gateway roleの対象KB限定
        # policyを先に作成する。knowledgeBaseIdや件数はモデルへ公開しない。
        self.target.node.add_dependency(backend_policy)
