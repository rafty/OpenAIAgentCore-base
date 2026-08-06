"""BedrockAgentCoreAppのHTTP/SSE境界と依存注入。"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

from agents import Agent, Model
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
from agent_app.service import stream_agent_response
from agent_app.session import (
    AgentCoreMemorySession,
    MemoryClientFactory,
    create_memory_data_client,
)


ConfigLoader = Callable[[], AppConfig]
ModelFactory = Callable[[AppConfig], Model]
AgentFactory = Callable[[Model], Any]
SessionFactory = Callable[[AppConfig, InvocationInput], AgentCoreMemorySession]
StreamService = Callable[..., AsyncIterator[StreamEvent]]


def create_runtime_app(
    *,
    config: AppConfig | None = None,
    config_loader: ConfigLoader = AppConfig.from_env,
    model: Model | None = None,
    manager_agent: Agent | None = None,
    model_factory: ModelFactory = create_bedrock_responses_model,
    agent_factory: AgentFactory = create_agents,
    session_factory: SessionFactory | None = None,
    memory_client_factory: MemoryClientFactory = create_memory_data_client,
    stream_service: StreamService = stream_agent_response,
) -> BedrockAgentCoreApp:
    """本番境界を維持したままModelとMemoryをテストダブルへ差し替える。"""

    app = BedrockAgentCoreApp()
    resolved_config = config
    resolved_manager = manager_agent

    def resolve_config() -> AppConfig:
        """有効なHTTP入力が来るまで環境設定の評価を遅延する。"""

        nonlocal resolved_config
        if resolved_config is None:
            resolved_config = config_loader()
        return resolved_config

    def resolve_manager(active_config: AppConfig) -> Agent:
        """本番modelとAgentを初回の有効な呼び出し時に一度だけ生成する。"""

        nonlocal resolved_manager
        if resolved_manager is None:
            active_model = model if model is not None else model_factory(active_config)
            resolved_manager = agent_factory(active_model).manager
        return resolved_manager

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
            active_manager = resolve_manager(active_config)
            session = build_session(active_config, invocation)
        except Exception:
            return server_error_response()

        # ここで初めてasync iteratorを返すため、以降の失敗はSSE errorとして扱われる。
        return stream_service(
            manager_agent=active_manager,
            prompt=invocation.prompt,
            session=session,
        )

    return app
