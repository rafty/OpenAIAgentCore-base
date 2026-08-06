"""Runtime環境変数の固定値、必須値、安全なエラーを確認するテスト。"""

import pytest

from agent_app.config import AppConfig, ConfigurationError


VALID_ENV = {
    "AWS_REGION": "us-east-2",
    "BEDROCK_OPENAI_MODEL_ID": "openai.gpt-5.5",
    "AGENTCORE_MEMORY_ID": "memory-id",
    "OPENAI_AGENTS_DISABLE_TRACING": "1",
}


def test_valid_config_is_loaded() -> None:
    assert AppConfig.from_env(VALID_ENV) == AppConfig(
        aws_region="us-east-2",
        model_id="openai.gpt-5.5",
        memory_id="memory-id",
        tracing_disabled="1",
    )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("AWS_REGION", "us-east-1"),
        ("BEDROCK_OPENAI_MODEL_ID", "openai.gpt-other"),
        ("AGENTCORE_MEMORY_ID", ""),
        ("OPENAI_AGENTS_DISABLE_TRACING", "0"),
    ],
)
def test_invalid_config_raises_only_safe_message(key: str, value: str) -> None:
    env = dict(VALID_ENV)
    env[key] = value
    with pytest.raises(ConfigurationError) as error:
        AppConfig.from_env(env)
    assert str(error.value) == "Agentアプリケーションの設定が不正です。"
    if value:
        assert value not in str(error.value)


@pytest.mark.parametrize("missing", list(VALID_ENV))
def test_missing_config_is_rejected(missing: str) -> None:
    env = dict(VALID_ENV)
    del env[missing]
    with pytest.raises(ConfigurationError):
        AppConfig.from_env(env)
