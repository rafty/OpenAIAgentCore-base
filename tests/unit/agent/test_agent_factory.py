"""Manager／Weather Agentの所有境界と安全instructionsを固定するテスト。"""

from typing import cast

import pytest
from agents import Model
from agents.mcp import MCPServer

from agent_app.agent_factory import (
    MANAGER_AVAILABLE_INSTRUCTIONS,
    MANAGER_INSTRUCTIONS,
    MANAGER_UNAVAILABLE_INSTRUCTIONS,
    WEATHER_AVAILABLE_INSTRUCTIONS,
    WEATHER_INSTRUCTIONS,
    WEATHER_TOOL_DESCRIPTION,
    WEATHER_TOOL_NAME,
    WEATHER_UNAVAILABLE_INSTRUCTIONS,
    AgentBundle,
    create_agents,
)
from agent_app.config import AppConfig
from agent_app.models import create_bedrock_responses_model


CONFIG = AppConfig(
    "us-east-2",
    "openai.gpt-5.5",
    "memory",
    "1",
    "https://weather-time.gateway.bedrock-agentcore.us-east-2.amazonaws.com/mcp",
    "WeatherTimeMock",
)


@pytest.fixture(scope="module")
def model() -> Model:
    return create_bedrock_responses_model(CONFIG)


def _mcp_server() -> MCPServer:
    """接続を伴わず、Factoryへ渡すMCP serverの同一性だけを検証する。"""

    return cast(MCPServer, object())


def _assert_agent_as_tool_boundary(
    bundle: AgentBundle,
    expected_weather_mcp_servers: list[MCPServer],
) -> None:
    # 会話と最終回答はManagerが所有し、Gateway ToolはWeather経由でだけ利用させる。
    assert bundle.manager.mcp_servers == []
    assert bundle.weather.mcp_servers == expected_weather_mcp_servers
    assert bundle.weather.tools == []
    assert [tool.name for tool in bundle.manager.tools] == [WEATHER_TOOL_NAME]
    assert bundle.manager.tools[0].description == WEATHER_TOOL_DESCRIPTION
    assert bundle.manager.handoffs == []
    assert bundle.weather.handoffs == []


def test_available_gateway_configures_weather_only_mcp_and_safe_routing(
    model: Model,
) -> None:
    mcp_server = _mcp_server()

    bundle = create_agents(model, [mcp_server], gateway_available=True)

    assert bundle.manager.model is model
    assert bundle.weather.model is model
    _assert_agent_as_tool_boundary(bundle, [mcp_server])
    assert bundle.weather.instructions == WEATHER_AVAILABLE_INSTRUCTIONS
    assert bundle.manager.instructions == MANAGER_AVAILABLE_INSTRUCTIONS

    weather_instructions = WEATHER_AVAILABLE_INSTRUCTIONS
    manager_instructions = MANAGER_AVAILABLE_INSTRUCTIONS
    assert "天気に関する依頼ではget_weather(location)" in weather_instructions
    assert "時刻・タイムゾーン・都市の時刻に関する依頼ではget_time(timezone)" in (
        weather_instructions
    )
    assert "MCP Toolを必ず使用" in weather_instructions
    assert "data_typeがmock" in weather_instructions
    assert "現在の実天気・実時刻ではないテスト用の固定モック値" in weather_instructions
    assert "システム時計や推測値を使ったりしてはいけません" in weather_instructions

    assert "天気または時刻に関する質問にはweather_agentを使用" in manager_instructions
    assert "data_type=mock" in manager_instructions
    assert "現在の実天気・実時刻ではないテスト用固定モック" in manager_instructions
    assert "推測・補完してはいけません" in manager_instructions
    assert "Handoffせず" in manager_instructions
    assert "最終回答" in manager_instructions

    assert "天気と時刻" in WEATHER_TOOL_DESCRIPTION
    assert "固定モックTool" in WEATHER_TOOL_DESCRIPTION
    assert "現在の実データではない" in WEATHER_TOOL_DESCRIPTION
    assert "取得不能" in WEATHER_TOOL_DESCRIPTION


@pytest.mark.parametrize(
    ("gateway_available", "has_mcp_server"),
    [(False, True), (True, False)],
    ids=("availability-flag-false", "server-missing"),
)
def test_unavailable_gateway_keeps_mcp_closed_and_forbids_substitution(
    model: Model,
    gateway_available: bool,
    has_mcp_server: bool,
) -> None:
    mcp_server = _mcp_server()
    mcp_servers = [mcp_server] if has_mcp_server else []

    bundle = create_agents(
        model,
        mcp_servers,
        gateway_available=gateway_available,
    )

    # 接続確認とserver登録のどちらかが欠ければ、MCPを公開せず取得不能側へ倒す。
    _assert_agent_as_tool_boundary(bundle, [])
    assert bundle.weather.instructions == WEATHER_UNAVAILABLE_INSTRUCTIONS
    assert bundle.manager.instructions == MANAGER_UNAVAILABLE_INSTRUCTIONS

    weather_instructions = WEATHER_UNAVAILABLE_INSTRUCTIONS
    manager_instructions = MANAGER_UNAVAILABLE_INSTRUCTIONS
    assert "Weather／Time Toolを利用できません" in weather_instructions
    assert "天気、予報、気温、降水、現在時刻またはタイムゾーン時刻を取得できない" in (
        weather_instructions
    )
    for prohibited_source in (
        "固定モック値",
        "システム時計",
        "学習済み知識",
        "推測値",
    ):
        assert prohibited_source in weather_instructions
    assert "代替してはいけません" in weather_instructions

    assert "天気または時刻に関する質問にはweather_agentを使用" in manager_instructions
    assert "Gateway Toolは利用不能" in manager_instructions
    assert "取得不能" in manager_instructions
    for prohibited_source in (
        "固定モック値",
        "現在の実天気",
        "実時刻",
        "システム時計",
        "推測値",
    ):
        assert prohibited_source in manager_instructions
    assert "補完してはいけません" in manager_instructions
    assert "Handoffせず" in manager_instructions
    assert "最終回答" in manager_instructions


def test_default_instruction_aliases_are_the_available_contract() -> None:
    assert WEATHER_INSTRUCTIONS == WEATHER_AVAILABLE_INSTRUCTIONS
    assert MANAGER_INSTRUCTIONS == MANAGER_AVAILABLE_INSTRUCTIONS
