"""PoC用AgentCore Memoryを定義するConstruct。"""

from aws_cdk import Duration, RemovalPolicy
from aws_cdk import aws_bedrockagentcore as agentcore
from constructs import Construct


class AgentCoreMemoryConstruct(Construct):
    """30日保持の短期記憶だけを所有するPoC用Construct。"""

    def __init__(self, scope: Construct, construct_id: str) -> None:
        super().__init__(scope, construct_id)

        # strategyとKMS keyを指定しないことで、長期記憶を作らずAWS所有キーを利用する。
        self.memory = agentcore.Memory(
            self,
            "Memory",
            memory_name="OpenAiAgentMemory",
            description="OpenAI Agents SDK PoC short-term conversation memory",
            expiration_duration=Duration.days(30),
        )
        # Memory L2はdefault_childを公開しないため、配下のL1へ削除方針を明示する。
        # PoCスタック削除時には会話履歴も意図的に削除する。
        cfn_memory = self.memory.node.find_child("Memory")
        if not isinstance(cfn_memory, agentcore.CfnMemory):
            raise TypeError("AgentCore MemoryのL1 resourceを解決できません。")
        cfn_memory.apply_removal_policy(RemovalPolicy.DESTROY)
