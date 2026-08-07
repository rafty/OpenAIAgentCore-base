"""Weather／Time固定モックを返すLambdaと最小権限を定義するConstruct。"""

from pathlib import Path

from aws_cdk import Duration, IgnoreMode, RemovalPolicy
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct


WEATHER_TIME_FUNCTION_NAME = "OpenAiWeatherTimeMock"


class WeatherTimeMockLambdaConstruct(Construct):
    """外部I/Oを持たない固定モックLambdaと専用ログ境界を所有する。"""

    def __init__(self, scope: Construct, construct_id: str) -> None:
        super().__init__(scope, construct_id)

        # LogGroupを先に固定名で作成し、Lambda既定Roleが要求するCreateLogGroupの
        # wildcard権限を避ける。PoCの短期ログだけなのでstack削除時に同時削除する。
        self.log_group = logs.LogGroup(
            self,
            "LogGroup",
            log_group_name=f"/aws/lambda/{WEATHER_TIME_FUNCTION_NAME}",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )
        self.execution_role = iam.Role(
            self,
            "ExecutionRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
        )
        self.log_group.grant_write(self.execution_role)

        weather_source = Path(__file__).resolve().parents[2] / "lambda_tools" / "weather"
        self.function = lambda_.Function(
            self,
            "Function",
            function_name=WEATHER_TIME_FUNCTION_NAME,
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="handler.lambda_handler",
            memory_size=128,
            timeout=Duration.seconds(5),
            role=self.execution_role,
            log_group=self.log_group,
            # Lambda code assetのbootstrap S3配布は必要だが、Tool schemaはGatewayへ
            # inline設定する。実行時に不要な正本JSONと一時生成物はassetへ含めない。
            code=lambda_.Code.from_asset(
                str(weather_source),
                ignore_mode=IgnoreMode.GLOB,
                exclude=[
                    "tools.json",
                    "__pycache__",
                    "**/__pycache__",
                    "*.py[cod]",
                    "**/*.py[cod]",
                    ".DS_Store",
                    "**/.DS_Store",
                ],
            ),
        )
