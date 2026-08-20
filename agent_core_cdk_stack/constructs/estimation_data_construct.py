"""Estimation PoCの単一DynamoDBテーブルを定義する。"""

from aws_cdk import CfnOutput, RemovalPolicy
from aws_cdk import aws_dynamodb as dynamodb
from constructs import Construct


ESTIMATION_TABLE_NAME = "OpenAiEstimationData"


class EstimationDataConstruct(Construct):
    """Sample Dataと利用時データを論理キーで分ける単一テーブルを所有する。"""

    def __init__(self, scope: Construct, construct_id: str) -> None:
        super().__init__(scope, construct_id)

        # PoCではデータ関係とLeadingKeys境界を一つのテーブルで検証する。
        # 本番向けPITR・明細分割は仕様対象外なのでここで暗黙に有効化しない。
        self.table = dynamodb.Table(
            self,
            "Table",
            table_name=ESTIMATION_TABLE_NAME,
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=False
            ),
            time_to_live_attribute="expires_at_epoch",
            removal_policy=RemovalPolicy.DESTROY,
        )
        self.table_name_output = CfnOutput(
            self,
            "TableName",
            value=self.table.table_name,
        )
        self.table_name_output.override_logical_id("EstimationTableName")
