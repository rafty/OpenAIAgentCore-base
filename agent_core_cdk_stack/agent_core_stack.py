"""責務別Constructを組み合わせるAgentCore PoCスタック。"""

from aws_cdk import Stack
from constructs import Construct

from agent_core_cdk_stack.constructs.agent_core_memory_construct import (
    AgentCoreMemoryConstruct,
)
from agent_core_cdk_stack.constructs.agent_core_runtime_construct import (
    AgentCoreRuntimeConstruct,
)
from agent_core_cdk_stack.constructs.agent_core_weather_gateway_construct import (
    AgentCoreWeatherGatewayConstruct,
)
from agent_core_cdk_stack.constructs.weather_time_gateway_target_construct import (
    WeatherTimeGatewayTargetConstruct,
)
from agent_core_cdk_stack.constructs.weather_time_mock_lambda_construct import (
    WeatherTimeMockLambdaConstruct,
)


class AgentCoreStack(Stack):
    """責務別Constructの参照と作成順だけを接続する構成ルート。"""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # スタック自身には個別resourceの詳細を持たせず、正本と権限境界を共有する
        # Construct間の依存配線だけを表現する。
        memory = AgentCoreMemoryConstruct(self, "AgentCoreMemory")
        weather_lambda = WeatherTimeMockLambdaConstruct(self, "WeatherTimeMockLambda")
        weather_gateway = AgentCoreWeatherGatewayConstruct(self, "WeatherGateway")
        weather_target = WeatherTimeGatewayTargetConstruct(
            self,
            "WeatherTimeGatewayTarget",
            gateway=weather_gateway.gateway,
            lambda_function=weather_lambda.function,
        )
        runtime = AgentCoreRuntimeConstruct(
            self,
            "AgentCoreRuntime",
            memory=memory.memory,
            gateway=weather_gateway.gateway,
            # TargetとRuntimeが同じ定数を共有し、公開Tool接頭辞のずれを防ぐ。
            gateway_target_name=weather_target.target_name,
        )
        # URL参照だけではTarget READYの作成順を表せないため、RuntimeをTargetへ依存させる。
        runtime.runtime.node.add_dependency(weather_target.target)
