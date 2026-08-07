"""Runtime環境変数の固定値、必須値、安全なエラーを確認するテスト。"""

import pytest

from agent_app.config import AppConfig, ConfigurationError


VALID_GATEWAY_URL = (
    "https://gateway-123.gateway.bedrock-agentcore.us-east-2.amazonaws.com/mcp"
)
VALID_GATEWAY_TARGET_NAME = "WeatherTimeMock"
VALID_ENV = {
    "AWS_REGION": "us-east-2",
    "BEDROCK_OPENAI_MODEL_ID": "openai.gpt-5.5",
    "AGENTCORE_MEMORY_ID": "memory-id",
    "OPENAI_AGENTS_DISABLE_TRACING": "1",
    "AGENTCORE_GATEWAY_URL": VALID_GATEWAY_URL,
    "AGENTCORE_GATEWAY_TARGET_NAME": VALID_GATEWAY_TARGET_NAME,
}


def test_valid_config_is_loaded() -> None:
    assert AppConfig.from_env(VALID_ENV) == AppConfig(
        aws_region="us-east-2",
        model_id="openai.gpt-5.5",
        memory_id="memory-id",
        tracing_disabled="1",
        gateway_url=VALID_GATEWAY_URL,
        gateway_target_name=VALID_GATEWAY_TARGET_NAME,
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
def test_invalid_config_raises_only_safe_message(
    key: str,
    value: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    env = dict(VALID_ENV)
    env[key] = value
    with pytest.raises(ConfigurationError) as error:
        AppConfig.from_env(env)
    assert str(error.value) == "Agentアプリケーションの設定が不正です。"
    if value:
        assert value not in str(error.value)
        assert value not in caplog.text


@pytest.mark.parametrize("missing", list(VALID_ENV))
def test_missing_config_is_rejected(
    missing: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    env = dict(VALID_ENV)
    del env[missing]
    with pytest.raises(ConfigurationError) as error:
        AppConfig.from_env(env)
    assert str(error.value) == "Agentアプリケーションの設定が不正です。"
    assert VALID_GATEWAY_URL not in str(error.value)
    assert VALID_GATEWAY_TARGET_NAME not in str(error.value)
    assert VALID_GATEWAY_URL not in caplog.text
    assert VALID_GATEWAY_TARGET_NAME not in caplog.text


@pytest.mark.parametrize(
    "gateway_url",
    [
        pytest.param(
            "http://gateway-123.gateway.bedrock-agentcore.us-east-2.amazonaws.com/mcp",
            id="scheme",
        ),
        pytest.param("https://gateway.example.com/mcp", id="host"),
        pytest.param(
            "https://gateway-123.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp",
            id="region",
        ),
        pytest.param(
            "https://gateway-123.gateway.bedrock-agentcore.us-east-2.amazonaws.com/tools",
            id="path",
        ),
        pytest.param(
            "https://user:password@gateway-123.gateway.bedrock-agentcore.us-east-2.amazonaws.com/mcp",
            id="userinfo",
        ),
        pytest.param(
            "https://gateway-123.gateway.bedrock-agentcore.us-east-2.amazonaws.com:443/mcp",
            id="port",
        ),
        pytest.param(f"{VALID_GATEWAY_URL}?token=sensitive-value", id="query"),
        pytest.param(f"{VALID_GATEWAY_URL}#sensitive-fragment", id="fragment"),
    ],
)
def test_invalid_gateway_url_is_rejected_without_exposure(
    gateway_url: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # 各URL構成要素は、SigV4署名先をus-east-2の専用Gatewayへ固定する安全境界に対応する。
    env = {**VALID_ENV, "AGENTCORE_GATEWAY_URL": gateway_url}

    with pytest.raises(ConfigurationError) as error:
        AppConfig.from_env(env)

    assert str(error.value) == "Agentアプリケーションの設定が不正です。"
    assert gateway_url not in str(error.value)
    assert gateway_url not in caplog.text


# GatewayTarget APIの長さ契約は1〜100文字なので、両端を受理して101文字目を拒否する。
@pytest.mark.parametrize(
    "target_name",
    [
        pytest.param("A", id="minimum-length"),
        pytest.param(VALID_GATEWAY_TARGET_NAME, id="normal"),
        pytest.param("Weather-Time9", id="allowed-characters"),
        pytest.param("A" * 100, id="maximum-length"),
    ],
)
def test_valid_gateway_target_name_boundaries_are_loaded(target_name: str) -> None:
    env = {**VALID_ENV, "AGENTCORE_GATEWAY_TARGET_NAME": target_name}

    assert AppConfig.from_env(env).gateway_target_name == target_name


@pytest.mark.parametrize(
    "target_name",
    [
        pytest.param("A" * 101, id="over-maximum-length"),
        pytest.param("Weather_Time", id="underscore"),
        pytest.param("Weather Time", id="space"),
        pytest.param("-WeatherTime", id="leading-hyphen"),
        pytest.param("WeatherTime-", id="trailing-hyphen"),
        pytest.param("Weather--Time", id="consecutive-hyphens"),
        pytest.param("天気", id="non-ascii"),
    ],
)
def test_invalid_gateway_target_name_is_rejected_without_exposure(
    target_name: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    env = {**VALID_ENV, "AGENTCORE_GATEWAY_TARGET_NAME": target_name}

    with pytest.raises(ConfigurationError) as error:
        AppConfig.from_env(env)

    assert str(error.value) == "Agentアプリケーションの設定が不正です。"
    assert target_name not in str(error.value)
    assert target_name not in caplog.text
