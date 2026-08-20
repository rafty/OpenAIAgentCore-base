"""DynamoDB Vector IndexのCustom Resourceと限定Providerを定義する。"""

from pathlib import Path

from aws_cdk import CustomResource, Duration, RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import custom_resources as cr
from constructs import Construct


ESTIMATION_VECTOR_INDEX_NAME = "EstimationProjectVectorIndexV1"


class DynamoDbVectorIndexConstruct(Construct):
    """CloudFormation未対応のVector IndexだけをCustom Resourceで補完する。"""

    def __init__(self, scope: Construct, construct_id: str, *, table: dynamodb.ITable) -> None:
        super().__init__(scope, construct_id)
        stack = Stack.of(self)
        root = Path(__file__).resolve().parents[2]
        source_file = "lambda_tools/dynamodb_vector_index/Dockerfile"

        role = iam.Role(self, "ProviderRole", assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"))
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["dynamodb:DescribeTable", "dynamodb:UpdateTable"],
                resources=[table.table_arn],
            )
        )
        on_event_logs = logs.LogGroup(
            self,
            "OnEventLogs",
            log_group_name="/aws/lambda/OpenAiEstimationVectorIndexOnEvent",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )
        is_complete_logs = logs.LogGroup(
            self,
            "IsCompleteLogs",
            log_group_name="/aws/lambda/OpenAiEstimationVectorIndexIsComplete",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )
        on_event_logs.grant_write(role)
        is_complete_logs.grant_write(role)
        on_event = lambda_.DockerImageFunction(
            self,
            "OnEvent",
            function_name="OpenAiEstimationVectorIndexOnEvent",
            code=lambda_.DockerImageCode.from_image_asset(str(root), file=source_file, cmd=["lambda_tools.dynamodb_vector_index.handler.on_event"]),
            architecture=lambda_.Architecture.ARM_64,
            timeout=Duration.seconds(60),
            memory_size=256,
            role=role,
            log_group=on_event_logs,
        )
        is_complete = lambda_.DockerImageFunction(
            self,
            "IsComplete",
            function_name="OpenAiEstimationVectorIndexIsComplete",
            code=lambda_.DockerImageCode.from_image_asset(str(root), file=source_file, cmd=["lambda_tools.dynamodb_vector_index.handler.is_complete"]),
            architecture=lambda_.Architecture.ARM_64,
            timeout=Duration.seconds(30),
            memory_size=256,
            role=role,
            log_group=is_complete_logs,
        )
        provider = cr.Provider(
            self,
            "Provider",
            on_event_handler=on_event,
            is_complete_handler=is_complete,
            query_interval=Duration.seconds(15),
            total_timeout=Duration.minutes(60),
        )
        # Index契約はAgent入力ではなくCloudFormation propertiesとして固定し、
        # Providerが任意の属性・次元・filterを受ける汎用APIにならないようにする。
        self.resource = CustomResource(
            self,
            "Index",
            service_token=provider.service_token,
            resource_type="Custom::DynamoDbVectorIndex",
            properties={
                "TableName": table.table_name,
                "IndexName": ESTIMATION_VECTOR_INDEX_NAME,
                "VectorAttribute": "embedding",
                "Dimensions": 1024,
                "DistanceFunction": "COSINE",
                "SearchSchema": [
                    {"AttributeName": "search_scope", "SearchSchemaElementType": "HASH"},
                    {"AttributeName": "entity_type", "SearchSchemaElementType": "INLINE_FILTER"},
                    {"AttributeName": "project_type", "SearchSchemaElementType": "INLINE_FILTER"},
                    {"AttributeName": "architecture_family", "SearchSchemaElementType": "INLINE_FILTER"},
                    {"AttributeName": "outcome_quality", "SearchSchemaElementType": "INLINE_FILTER"},
                ],
                "Projection": {
                    "ProjectionType": "INCLUDE",
                    "NonKeyAttributes": [
                        "project_id",
                        "project_name",
                        "search_summary",
                        "entity_type",
                        "search_scope",
                        "project_type",
                        "architecture_family",
                        "outcome_quality",
                    ],
                },
            },
        )
        self.resource.node.add_dependency(table)
        self.index_name = ESTIMATION_VECTOR_INDEX_NAME
