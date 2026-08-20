"""Estimation Lambdaを4 Toolのinline schemaでGateway Targetへ登録する。"""

from pathlib import Path

from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_lambda as lambda_
from constructs import Construct

from agent_core_cdk_stack.constructs.weather_time_gateway_target_construct import (
    _load_tool_definitions,
)


ESTIMATION_GATEWAY_TARGET_NAME = "EstimationTools"
_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "lambda_tools" / "estimation" / "tools.json"


class EstimationGatewayTargetConstruct(Construct):
    """4業務Toolだけを単一Lambda Targetへ公開する。"""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        gateway: agentcore.IGateway,
        lambda_function: lambda_.IFunction,
    ) -> None:
        super().__init__(scope, construct_id)
        # 既存Weather Targetと同じ限定JSON Schema変換を再利用し、任意OpenAPIや
        # 汎用DynamoDB ToolをGatewayへ混入させない。
        tool_schema = agentcore.ToolSchema.from_inline(_load_tool_definitions(_SCHEMA_PATH))
        invoke_grant = lambda_function.grant_invoke(gateway.role)
        self.target_name = ESTIMATION_GATEWAY_TARGET_NAME
        self.target = agentcore.GatewayTarget.for_lambda(
            self,
            "Target",
            gateway=gateway,
            lambda_function=lambda_function,
            tool_schema=tool_schema,
            gateway_target_name=self.target_name,
            credential_provider_configurations=[agentcore.GatewayCredentialProvider.from_iam_role()],
        )
        invoke_grant.apply_before(self.target)
