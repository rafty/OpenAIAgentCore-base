"""Bedrock Responses modelのregion、model ID、SigV4認証方式を確認するテスト。"""

from agent_app.config import AppConfig
from agent_app.models import create_bedrock_client, create_bedrock_responses_model


CONFIG = AppConfig(
    "us-east-1",
    "openai.gpt-5.5",
    "memory-id",
    "1",
    "https://gateway-id.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp",
    "WeatherTimeMock",
)


def test_bedrock_responses_model_uses_sigv4_default_chain(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "must-not-be-used")

    client = create_bedrock_client(CONFIG)
    # providerの公開生成APIだけでは認証方式を判定できないため、固定versionの内部状態も検査する。
    runtime = client._provider_runtime
    auth = runtime.prepare_async_request.__self__

    assert runtime.name == "bedrock"
    assert runtime.region == "us-east-1"
    assert str(client.base_url) == "https://bedrock-mantle.us-east-1.api.aws/openai/v1/"
    assert client.api_key == ""
    assert type(auth).__name__ == "_BedrockSigV4Auth"
    assert auth._config.source == "default"
    assert auth._config.access_key_id is None
    assert auth._config.secret_access_key is None


def test_model_id_and_client_are_injected() -> None:
    client = create_bedrock_client(CONFIG)
    model = create_bedrock_responses_model(CONFIG, client=client)
    assert model.model == "openai.gpt-5.5"
    assert model._client is client
