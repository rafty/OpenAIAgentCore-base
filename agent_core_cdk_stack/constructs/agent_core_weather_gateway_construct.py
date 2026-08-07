"""Weather／Time Tool専用のAgentCore Gatewayと実行Roleを定義する。"""

from aws_cdk import ArnFormat, Stack
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_iam as iam
from constructs import Construct


WEATHER_GATEWAY_NAME = "OpenAiWeatherGateway"


class AgentCoreWeatherGatewayConstruct(Construct):
    """IAM受信認証の専用MCP Gatewayと条件付き信頼を所有する。"""

    def __init__(self, scope: Construct, construct_id: str) -> None:
        super().__init__(scope, construct_id)

        stack = Stack.of(self)
        # Gateway自身のARN tokenをtrustへ使うとRole→Gateway→Roleの循環になるため、
        # 固定Gateway名とstack tokenだけで対象名を限定したARN patternを組み立てる。
        # AgentCoreは表示名の大文字小文字を保持する一方、gatewayIdとARNのprefixは
        # 小文字へ正規化するため、実際にAssumeRoleへ渡されるSourceArnへ合わせる。
        gateway_arn_pattern = stack.format_arn(
            service="bedrock-agentcore",
            resource="gateway",
            resource_name=f"{WEATHER_GATEWAY_NAME.lower()}-*",
            arn_format=ArnFormat.SLASH_RESOURCE_NAME,
        )
        # L2既定Roleではなく専用Roleを渡し、GatewayからTargetへ進める権限境界を
        # このConstructで明示的に管理する。
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
            gateway_name=WEATHER_GATEWAY_NAME,
            role=self.execution_role,
            authorizer_configuration=agentcore.GatewayAuthorizer.using_aws_iam(),
            protocol_configuration=agentcore.GatewayProtocol.mcp(
                supported_versions=[
                    agentcore.MCPProtocolVersion.of("2025-11-25"),
                    agentcore.MCPProtocolVersion.MCP_2025_03_26,
                ]
            ),
        )
