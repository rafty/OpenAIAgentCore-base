"""Manager／Weather Agentの構成と安全instructionsを固定するテスト。"""

from agent_app.agent_factory import (
    MANAGER_INSTRUCTIONS,
    WEATHER_INSTRUCTIONS,
    WEATHER_TOOL_DESCRIPTION,
    create_agents,
)
from agent_app.config import AppConfig
from agent_app.models import create_bedrock_responses_model


def test_agents_as_tool_configuration_and_safety_instructions() -> None:
    model = create_bedrock_responses_model(
        AppConfig("us-east-2", "openai.gpt-5.5", "memory", "1")
    )
    bundle = create_agents(model)

    assert bundle.manager.model is model
    assert bundle.weather.model is model
    assert bundle.manager.handoffs == []
    assert bundle.weather.handoffs == []
    assert bundle.weather.tools == []
    assert [tool.name for tool in bundle.manager.tools] == ["weather_agent"]
    assert bundle.manager.tools[0].description == WEATHER_TOOL_DESCRIPTION
    assert "Handoffせず" in MANAGER_INSTRUCTIONS
    assert "最終回答" in MANAGER_INSTRUCTIONS
    assert "捏造してはいけません" in MANAGER_INSTRUCTIONS
    assert "実在する天気データを取得するToolは実装されていません" in WEATHER_INSTRUCTIONS
    assert "架空の天気" in WEATHER_INSTRUCTIONS
    assert "lambda_tools/weather" in WEATHER_INSTRUCTIONS
