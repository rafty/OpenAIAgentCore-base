"""実AWS接続なしで本番Runtime factoryを起動するコンテナ契約ハーネス。"""

import os
from typing import Any

from agent_app.config import AppConfig, GatewayConfig
from agent_app.runtime import create_runtime_app


HARNESS_CONFIG = AppConfig(
    aws_region="us-east-1",
    model_id="openai.gpt-5.5",
    memory_id="test-memory",
    tracing_disabled="1",
    weather_gateway=GatewayConfig(
        url=(
            "https://test-gateway.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
        ),
        region="us-east-1",
        target_name="WeatherTimeMock",
    ),
    knowledge_gateway=GatewayConfig(
        url=(
            "https://test-knowledge.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
        ),
        region="us-east-1",
        target_name="KnowledgeRetrieve",
    ),
)
HARNESS_MODEL = object()
HARNESS_SESSION = object()


def _unexpected_external_dependency(*args: Any, **kwargs: Any) -> object:
    """ハーネスから実Gateway、Lambda、Agentへ到達した場合は即座に失敗する。"""

    raise AssertionError("コンテナ契約ハーネスが外部依存へ到達しました。")


def create_harness_app():
    """本番HTTP境界へ決定的な依存だけを注入した検証用アプリを返す。"""

    mode = os.environ.get("CONTAINER_TEST_MODE", "success")

    async def stream_service(
        *,
        config,
        model,
        prompt,
        session,
        weather_mcp_server_factory,
        knowledge_mcp_server_factory,
        agent_factory,
    ):
        # 実モデルやAWSを使わず、コンテナ内で正常・異常SSEだけを再現する。
        assert config is HARNESS_CONFIG
        assert model is HARNESS_MODEL
        assert prompt
        assert session is HARNESS_SESSION
        assert weather_mcp_server_factory is _unexpected_external_dependency
        assert knowledge_mcp_server_factory is _unexpected_external_dependency
        assert agent_factory is _unexpected_external_dependency
        yield {"type": "text_delta", "delta": "container"}
        if mode == "error":
            yield {"type": "error", "message": "処理中にエラーが発生しました。"}
            return
        yield {"type": "completed"}

    # テスト専用HTTP実装との契約ずれを防ぐため本番factoryを必ず通し、
    # 外部I/Oだけを依存注入境界で決定的な代替へ差し替える。
    return create_runtime_app(
        config=HARNESS_CONFIG,
        model=HARNESS_MODEL,
        agent_factory=_unexpected_external_dependency,
        weather_mcp_server_factory=_unexpected_external_dependency,
        knowledge_mcp_server_factory=_unexpected_external_dependency,
        session_factory=lambda config, invocation: HARNESS_SESSION,
        stream_service=stream_service,
    )


def main() -> None:
    create_harness_app().run(port=8080)


if __name__ == "__main__":
    main()
