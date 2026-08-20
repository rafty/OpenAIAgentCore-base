"""Estimation Tool専用AgentCore Gatewayと実行Roleを定義する。"""

from aws_cdk import ArnFormat, Stack
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_iam as iam
from constructs import Construct


ESTIMATION_GATEWAY_NAME = "OpenAiEstimationGateway"


class AgentCoreEstimationGatewayConstruct(Construct):
    """既存Gatewayと障害・権限を分けたIAM認証MCP Gateway。"""

    def __init__(self, scope: Construct, construct_id: str) -> None:
        super().__init__(scope, construct_id)
        stack = Stack.of(self)
        gateway_arn_pattern = stack.format_arn(
            service="bedrock-agentcore",
            resource="gateway",
            resource_name=f"{ESTIMATION_GATEWAY_NAME.lower()}-*",
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
        self.gateway = agentcore.Gateway(
            self,
            "Gateway",
            gateway_name=ESTIMATION_GATEWAY_NAME,
            role=self.execution_role,
            authorizer_configuration=agentcore.GatewayAuthorizer.using_aws_iam(),
            protocol_configuration=agentcore.GatewayProtocol.mcp(
                supported_versions=[
                    agentcore.MCPProtocolVersion.of("2025-11-25"),
                    agentcore.MCPProtocolVersion.MCP_2025_03_26,
                ]
            ),
        )
