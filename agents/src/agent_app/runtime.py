"""BedrockAgentCoreAppのHTTP/SSE境界と依存注入。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

from agents import Model
from bedrock_agentcore import BedrockAgentCoreApp, RequestContext
from starlette.responses import Response

from agent_app.agent_factory import create_agents
from agent_app.config import AppConfig
from agent_app.contracts import (
    ContractValidationError,
    InvocationInput,
    StreamEvent,
    bad_request_response,
    server_error_response,
    validate_payload,
    validate_session_id,
)
from agent_app.models import create_bedrock_responses_model
from agent_app.gateway_tools import create_gateway_mcp_server
from agent_app.service import (
    AgentFactory,
    MCPServerFactory,
    stream_agent_response,
)
from agent_app.session import (
    AgentCoreMemorySession,
    MemoryClientFactory,
    create_memory_data_client,
)


ConfigLoader = Callable[[], AppConfig]
ModelFactory = Callable[[AppConfig], Model]
SessionFactory = Callable[[AppConfig, InvocationInput], AgentCoreMemorySession]
StreamService = Callable[..., AsyncIterator[StreamEvent]]


def create_runtime_app(
    *,
    config: AppConfig | None = None,
    config_loader: ConfigLoader = AppConfig.from_env,
    model: Model | None = None,
    model_factory: ModelFactory = create_bedrock_responses_model,
    agent_factory: AgentFactory = create_agents,
    mcp_server_factory: MCPServerFactory = create_gateway_mcp_server,
    session_factory: SessionFactory | None = None,
    memory_client_factory: MemoryClientFactory = create_memory_data_client,
    stream_service: StreamService = stream_agent_response,
) -> BedrockAgentCoreApp:
    """HTTP境界を維持したままModel、MCP、Memoryを差し替え可能にする。"""

    app = BedrockAgentCoreApp()
    resolved_config = config
    resolved_model = model

    def resolve_config() -> AppConfig:
        """有効なHTTP入力が来るまで環境設定の評価を遅延する。"""

        nonlocal resolved_config
        if resolved_config is None:
            resolved_config = config_loader()
        return resolved_config

    def resolve_model(active_config: AppConfig) -> Model:
        """本番modelだけを初回の有効な呼び出し時に一度生成して再利用する。"""

        nonlocal resolved_model
        if resolved_model is None:
            resolved_model = model_factory(active_config)
        return resolved_model

    def default_session_factory(
        active_config: AppConfig,
        invocation: InvocationInput,
    ) -> AgentCoreMemorySession:
        """入力のactorとRuntimeのsessionをMemoryの分離キーへ対応付ける。"""

        return AgentCoreMemorySession(
            memory_id=active_config.memory_id,
            actor_id=invocation.actor_id,
            session_id=invocation.session_id,
            region=active_config.aws_region,
            client_factory=memory_client_factory,
        )

    build_session = session_factory or default_session_factory

    @app.entrypoint
    async def invoke(payload: Any, context: RequestContext) -> Response | AsyncIterator[StreamEvent]:
        # body不正は依存初期化より先に判定し、モデルやMemoryへ一切アクセスさせない。
        try:
            validated_payload = validate_payload(payload)
        except ContractValidationError:
            return bad_request_response()

        # contextと設定の不備もstream開始前にHTTP 5xxへ変換する。
        try:
            session_id = validate_session_id(context.session_id)
            active_config = resolve_config()
            invocation = InvocationInput(
                prompt=validated_payload.prompt,
                actor_id=validated_payload.actor_id,
                session_id=session_id,
            )
            active_model = resolve_model(active_config)
            session = build_session(active_config, invocation)
        except Exception:
            return server_error_response()

        # modelだけをprocess単位で共有し、MCP serverとAgentはiterator内部で毎回生成する。
        # factory注入により、実AWSへ接続せず同じ本番境界を決定的に検証できる。
        return stream_service(
            config=active_config,
            model=active_model,
            prompt=invocation.prompt,
            session=session,
            mcp_server_factory=mcp_server_factory,
            agent_factory=agent_factory,
        )

    return app
