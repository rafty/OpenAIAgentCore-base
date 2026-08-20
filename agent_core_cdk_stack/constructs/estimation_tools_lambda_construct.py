"""Estimation 4 ToolのLambdaコンテナ、ログ、最小権限を定義する。"""

from pathlib import Path

from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct


ESTIMATION_TOOLS_FUNCTION_NAME = "OpenAiEstimationTools"


class EstimationToolsLambdaConstruct(Construct):
    """決定的な計算と限定Item操作を一つの業務Lambdaへ集約する。"""

    def __init__(self, scope: Construct, construct_id: str, *, table: dynamodb.ITable, index_name: str) -> None:
        super().__init__(scope, construct_id)
        stack = Stack.of(self)
        role = iam.Role(self, "ExecutionRole", assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"))
        logs_group = logs.LogGroup(
            self,
            "LogGroup",
            log_group_name=f"/aws/lambda/{ESTIMATION_TOOLS_FUNCTION_NAME}",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )
        logs_group.grant_write(role)
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["dynamodb:GetItem", "dynamodb:Query"],
                resources=[table.table_arn],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["dynamodb:PutItem", "dynamodb:TransactWriteItems"],
                resources=[table.table_arn],
                conditions={
                    "ForAllValues:StringLike": {
                        "dynamodb:LeadingKeys": [
                            "SEARCH_CONTEXT#*",
                            "ESTIMATE_PROJECT#*",
                            "IDEMPOTENCY#*",
                        ]
                    }
                },
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["dynamodb:SearchVectors"],
                resources=[f"{table.table_arn}/index/{index_name}"],
            )
        )
        model_arn = stack.format_arn(
            service="bedrock",
            region="us-east-1",
            account="",
            resource="foundation-model",
            resource_name="cohere.embed-multilingual-v3",
        )
        role.add_to_policy(iam.PolicyStatement(actions=["bedrock:InvokeModel"], resources=[model_arn]))
        root = Path(__file__).resolve().parents[2]
        self.function = lambda_.DockerImageFunction(
            self,
            "Function",
            function_name=ESTIMATION_TOOLS_FUNCTION_NAME,
            code=lambda_.DockerImageCode.from_image_asset(str(root), file="lambda_tools/estimation/Dockerfile"),
            architecture=lambda_.Architecture.ARM_64,
            timeout=Duration.seconds(60),
            memory_size=512,
            role=role,
            log_group=logs_group,
            environment={
                "ESTIMATION_TABLE_NAME": table.table_name,
                "ESTIMATION_VECTOR_INDEX_NAME": index_name,
                "ESTIMATION_GATEWAY_TARGET_NAME": "EstimationTools",
            },
        )
        self.execution_role = role
        self.log_group = logs_group
