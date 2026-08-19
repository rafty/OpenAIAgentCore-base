"""責務別Constructを組み合わせるAgentCore PoCスタック。"""

from aws_cdk import CfnOutput, Stack
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
from agent_core_cdk_stack.constructs.agent_core_knowledge_gateway_construct import (
    AgentCoreKnowledgeGatewayConstruct,
)
from agent_core_cdk_stack.constructs.knowledge_data_source_construct import (
    KnowledgeDataSourceConstruct,
)
from agent_core_cdk_stack.constructs.knowledge_document_bucket_construct import (
    KnowledgeDocumentBucketConstruct,
)
from agent_core_cdk_stack.constructs.knowledge_retrieve_gateway_target_construct import (
    KnowledgeRetrieveGatewayTargetConstruct,
)
from agent_core_cdk_stack.constructs.managed_knowledge_base_construct import (
    ManagedKnowledgeBaseConstruct,
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
        knowledge_documents = KnowledgeDocumentBucketConstruct(
            self, "KnowledgeDocuments"
        )
        managed_knowledge_base = ManagedKnowledgeBaseConstruct(
            self,
            "ManagedKnowledgeBase",
            document_bucket=knowledge_documents.bucket,
        )
        knowledge_data_source = KnowledgeDataSourceConstruct(
            self,
            "KnowledgeDataSource",
            knowledge_base=managed_knowledge_base.knowledge_base,
            document_bucket=knowledge_documents.bucket,
            document_deployment=knowledge_documents.deployment,
        )
        weather_lambda = WeatherTimeMockLambdaConstruct(self, "WeatherTimeMockLambda")
        weather_gateway = AgentCoreWeatherGatewayConstruct(self, "WeatherGateway")
        weather_target = WeatherTimeGatewayTargetConstruct(
            self,
            "WeatherTimeGatewayTarget",
            gateway=weather_gateway.gateway,
            lambda_function=weather_lambda.function,
        )
        knowledge_gateway = AgentCoreKnowledgeGatewayConstruct(
            self,
            "KnowledgeGateway",
            knowledge_base=managed_knowledge_base.knowledge_base,
        )
        knowledge_target = KnowledgeRetrieveGatewayTargetConstruct(
            self,
            "KnowledgeRetrieveGatewayTarget",
            gateway=knowledge_gateway.gateway,
            knowledge_base=managed_knowledge_base.knowledge_base,
            backend_policy=knowledge_gateway.backend_policy,
        )
        runtime = AgentCoreRuntimeConstruct(
            self,
            "AgentCoreRuntime",
            memory=memory.memory,
            weather_gateway=weather_gateway.gateway,
            # TargetとRuntimeが同じ定数を共有し、公開Tool接頭辞のずれを防ぐ。
            weather_gateway_target_name=weather_target.target_name,
            knowledge_gateway=knowledge_gateway.gateway,
            knowledge_gateway_target_name=knowledge_target.target_name,
        )
        # URL参照だけではTarget READYの作成順を表せないため、Runtimeを両Targetへ
        # 依存させる。Knowledge Data Sourceの同期は意図的にdeployから分離する。
        runtime.runtime.node.add_dependency(weather_target.target, knowledge_target.target)

        CfnOutput(
            self,
            "KnowledgeBaseId",
            value=managed_knowledge_base.knowledge_base.attr_knowledge_base_id,
            description="Initial ingestion用Managed Knowledge Base ID",
        )
        CfnOutput(
            self,
            "KnowledgeDataSourceId",
            value=knowledge_data_source.data_source_id,
            description="Initial ingestion用Data Source ID",
        )
