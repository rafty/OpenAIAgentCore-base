"""Amazon Bedrock Mantle向けOpenAI Responses model factory。"""

from __future__ import annotations

from collections.abc import Callable

from agents.models.openai_responses import OpenAIResponsesModel
from openai import AsyncOpenAI
from openai.providers import bedrock

from agent_app.config import AppConfig


OpenAIClientFactory = Callable[[AppConfig], AsyncOpenAI]


def create_bedrock_client(config: AppConfig) -> AsyncOpenAI:
    """標準AWS認証情報チェーンとSigV4を使う非同期clientを生成する。"""

    # api_key=Noneを明示し、Bearer環境変数へのfallbackを無効化する。
    provider = bedrock(region=config.aws_region, api_key=None)
    return AsyncOpenAI(provider=provider)


def create_bedrock_responses_model(
    config: AppConfig,
    *,
    client: AsyncOpenAI | None = None,
    client_factory: OpenAIClientFactory = create_bedrock_client,
) -> OpenAIResponsesModel:
    """固定model IDと明示clientからAgents SDK用Responses modelを生成する。"""

    openai_client = client if client is not None else client_factory(config)
    return OpenAIResponsesModel(model=config.model_id, openai_client=openai_client)
