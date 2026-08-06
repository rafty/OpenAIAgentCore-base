"""責務別Constructを組み合わせるAgentCore PoCスタック。"""

from aws_cdk import Stack
from constructs import Construct

from agent_core_cdk_stack.constructs.agent_core_memory_construct import (
    AgentCoreMemoryConstruct,
)
from agent_core_cdk_stack.constructs.agent_core_runtime_construct import (
    AgentCoreRuntimeConstruct,
)


class AgentCoreStack(Stack):
    """Memoryを先に作成し、その参照をRuntimeへ接続する構成ルート。"""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # スタック自身には個別AWSリソースの詳細を持たせず、依存関係だけを表現する。
        memory = AgentCoreMemoryConstruct(self, "AgentCoreMemory")
        AgentCoreRuntimeConstruct(
            self,
            "AgentCoreRuntime",
            memory=memory.memory,
        )
