"""Agentコンテナ、Runtime、実行ロール権限を定義するConstruct。"""

from pathlib import Path

from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_ecr_assets as ecr_assets
from aws_cdk import aws_iam as iam
from constructs import Construct


class AgentCoreRuntimeConstruct(Construct):
    """コンテナRuntimeと、その実行ロール権限をまとめて定義するConstruct。"""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        memory: agentcore.Memory,
        gateway: agentcore.IGateway,
        gateway_target_name: str,
    ) -> None:
        super().__init__(scope, construct_id)

        gateway_url = gateway.gateway_url
        if not gateway_url:
            raise ValueError("AgentCore Gateway URLを解決できません。")

        # AgentCore Runtimeの実行基盤に合わせ、同じagents/をLinux ARM64としてbuildする。
        agents_directory = Path(__file__).resolve().parents[2] / "agents"
        artifact = agentcore.AgentRuntimeArtifact.from_asset(
            directory=str(agents_directory),
            platform=ecr_assets.Platform.LINUX_ARM64,
        )

        # 入力認証はIAM、ネットワークはPoC向けPublic、通信契約はHTTPに固定する。
        self.runtime = agentcore.Runtime(
            self,
            "Runtime",
            runtime_name="OpenAiAgentRuntime",
            description="OpenAI Agents SDK multi-agent PoC runtime",
            agent_runtime_artifact=artifact,
            authorizer_configuration=agentcore.RuntimeAuthorizerConfiguration.using_iam(),
            network_configuration=agentcore.RuntimeNetworkConfiguration.using_public_network(),
            protocol_configuration=agentcore.ProtocolType.HTTP,
            tracing_enabled=False,
            environment_variables={
                "AWS_REGION": "us-east-2",
                "BEDROCK_OPENAI_MODEL_ID": "openai.gpt-5.5",
                "OPENAI_AGENTS_DISABLE_TRACING": "1",
                "AGENTCORE_MEMORY_ID": memory.memory_id,
                # Gateway URLはCloudFormation tokenのまま非秘密設定として渡し、
                # 生成IDやaccountをAgentコードへ固定しない。
                "AGENTCORE_GATEWAY_URL": gateway_url,
                "AGENTCORE_GATEWAY_TARGET_NAME": gateway_target_name,
            },
        )

        # モデルとMemoryはいずれもコンテナへ鍵を渡さず、Runtime実行ロールで認可する。
        self.runtime.role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name(
                "AmazonBedrockMantleInferenceAccess"
            )
        )
        memory.grant_read_short_term_memory(self.runtime.role)
        memory.grant_write(self.runtime.role)
        # Runtimeには専用Gatewayの呼び出しだけを追加し、Target／Lambda権限は渡さない。
        gateway.grant_invoke(self.runtime.role)
