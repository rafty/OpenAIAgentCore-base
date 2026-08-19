"""Knowledge Retrieve専用AgentCore Gatewayと実行roleを定義する。"""

from aws_cdk import ArnFormat, Stack
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_iam as iam
from constructs import Construct


KNOWLEDGE_GATEWAY_NAME = "OpenAiKnowledgeGateway"


class AgentCoreKnowledgeGatewayConstruct(Construct):
    """Managed Knowledge Baseだけを呼ぶ専用MCP Gatewayを所有する。"""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        knowledge_base: bedrock.CfnKnowledgeBase,
    ) -> None:
        super().__init__(scope, construct_id)

        stack = Stack.of(self)
        # Gateway ARN tokenをtrustに使う循環を避けつつ、AgentCoreが生成する
        # 小文字gateway ID prefixまでSourceArnを限定する。
        gateway_arn_pattern = stack.format_arn(
            service="bedrock-agentcore",
            resource="gateway",
            resource_name=f"{KNOWLEDGE_GATEWAY_NAME.lower()}-*",
            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
        )
        self.execution_role = iam.Role(
            self,
            "ExecutionRole",
            assumed_by=iam.ServicePrincipal(
                "bedrock-agentcore.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": stack.account},
                    "ArnLike": {"aws:SourceArn": gateway_arn_pattern},
                },
            ),
        )
        self.backend_policy = iam.Policy(
            self,
            "KnowledgeBasePolicy",
            statements=[
                iam.PolicyStatement(
                    actions=["bedrock:GetKnowledgeBase", "bedrock:Retrieve"],
                    resources=[knowledge_base.attr_knowledge_base_arn],
                )
            ],
        )
        self.execution_role.attach_inline_policy(self.backend_policy)

        # Weather経路と障害・権限を共有しないため、Knowledge connectorだけを
        # 収容する別Gatewayとして作成する。
        self.gateway = agentcore.Gateway(
            self,
            "Gateway",
            gateway_name=KNOWLEDGE_GATEWAY_NAME,
            role=self.execution_role,
            authorizer_configuration=agentcore.GatewayAuthorizer.using_aws_iam(),
            protocol_configuration=agentcore.GatewayProtocol.mcp(
                supported_versions=[
                    agentcore.MCPProtocolVersion.of("2025-11-25"),
                    agentcore.MCPProtocolVersion.MCP_2025_03_26,
                ]
            ),
        )
