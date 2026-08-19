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
        weather_gateway: agentcore.IGateway,
        weather_gateway_target_name: str,
        knowledge_gateway: agentcore.IGateway,
        knowledge_gateway_target_name: str,
    ) -> None:
        super().__init__(scope, construct_id)

        weather_gateway_url = weather_gateway.gateway_url
        knowledge_gateway_url = knowledge_gateway.gateway_url
        if not weather_gateway_url or not knowledge_gateway_url:
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
                # Managed Knowledge Base、Gateway、モデルを同じリージョンへ置き、
                # SigV4署名先とRuntime設定がcross-regionにならないよう固定する。
                "AWS_REGION": "us-east-1",
                "BEDROCK_OPENAI_MODEL_ID": "openai.gpt-5.5",
                "OPENAI_AGENTS_DISABLE_TRACING": "1",
                "AGENTCORE_MEMORY_ID": memory.memory_id,
                # Gateway URLはCloudFormation tokenのまま非秘密設定として渡し、
                # 生成IDやaccountをAgentコードへ固定しない。
                "AGENTCORE_GATEWAY_URL": weather_gateway_url,
                "AGENTCORE_GATEWAY_TARGET_NAME": weather_gateway_target_name,
                "AGENTCORE_KNOWLEDGE_GATEWAY_URL": knowledge_gateway_url,
                "AGENTCORE_KNOWLEDGE_GATEWAY_TARGET_NAME": (
                    knowledge_gateway_target_name
                ),
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
        # Runtimeは各専門Gatewayだけを呼び、Knowledge Base、S3、Target、Lambdaへ
        # 直接アクセスしない。権限と片系障害をGateway単位で分離する。
        weather_gateway.grant_invoke(self.runtime.role)
        knowledge_gateway.grant_invoke(self.runtime.role)
