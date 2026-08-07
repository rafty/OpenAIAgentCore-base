"""マネージャーAgentとWeather AgentをAgents-as-Toolsで構成する。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from agents import Agent, Model
from agents.mcp import MCPServer


WEATHER_TOOL_NAME = "weather_agent"
WEATHER_TOOL_DESCRIPTION = (
    "天気と時刻に関する質問を担当する専門Agentです。専用Gatewayの固定モックToolを利用し、"
    "現在の実データではないこと、または取得不能であることを正確に返します。"
)

WEATHER_AVAILABLE_INSTRUCTIONS = """あなたは天気と時刻を担当するWeather Agentです。
天気に関する依頼ではget_weather(location)、時刻・タイムゾーン・都市の時刻に関する依頼ではget_time(timezone)に対応するMCP Toolを必ず使用してください。
正常結果はdata_typeがmockであることを確認し、現在の実天気・実時刻ではないテスト用の固定モック値だと日本語で明示してください。
Toolがerrorを返す、結果形式が不正、または必要なToolを利用できない場合は、天気や時刻を取得できないことだけを返してください。
固定値を知識として補完したり、システム時計や推測値を使ったりしてはいけません。
回答は日本語で、簡潔かつ正確に返してください。"""

WEATHER_UNAVAILABLE_INSTRUCTIONS = """あなたは天気と時刻を担当するWeather Agentです。
現在、専用GatewayのWeather／Time Toolを利用できません。
天気、予報、気温、降水、現在時刻またはタイムゾーン時刻を取得できないことを明確に伝えてください。
固定モック値、システム時計、学習済み知識または推測値で代替してはいけません。
回答は日本語で、簡潔かつ正確に返してください。"""

MANAGER_AVAILABLE_INSTRUCTIONS = """あなたは利用者との会話と最終回答を所有するマネージャーAgentです。
天気または時刻に関する質問にはweather_agentを使用し、その専門結果を利用者向けの最終回答へ統合してください。
Weather Agentが返したdata_type=mockの結果は、現在の実天気・実時刻ではないテスト用固定モックだと日本語で明示してください。
Weather Agentが取得不能を返した場合は、その状態を維持し、あなた自身で値を推測・補完してはいけません。
専門Agentへ会話をHandoffせず、必ずあなたが日本語で最終回答を返してください。
天気・時刻以外の質問には、利用可能な情報の範囲で正確かつ簡潔に対応してください。"""

MANAGER_UNAVAILABLE_INSTRUCTIONS = """あなたは利用者との会話と最終回答を所有するマネージャーAgentです。
天気または時刻に関する質問にはweather_agentを使用してください。現在Gateway Toolは利用不能であり、専門結果の取得不能を利用者へ日本語で案内してください。
固定モック値、現在の実天気、実時刻、システム時計または推測値をあなた自身で補完してはいけません。
専門Agentへ会話をHandoffせず、必ずあなたが日本語で最終回答を返してください。
天気・時刻以外の質問には、利用可能な情報の範囲で正確かつ簡潔に対応してください。"""

# 既存importとの互換性を保ち、通常利用可能状態の標準instructionsを明示する。
WEATHER_INSTRUCTIONS = WEATHER_AVAILABLE_INSTRUCTIONS
MANAGER_INSTRUCTIONS = MANAGER_AVAILABLE_INSTRUCTIONS


@dataclass(frozen=True, slots=True)
class AgentBundle:
    """実行起点のManagerと、Tool化したWeather Agentの組。"""

    manager: Agent
    weather: Agent


def create_agents(
    model: Model,
    mcp_servers: Sequence[MCPServer] = (),
    gateway_available: bool = False,
) -> AgentBundle:
    """Gateway利用可否に応じたリクエスト専用Agents-as-Tools構成を生成する。"""

    # 接続確認済みserverがある場合だけ利用可能状態とし、状態とTool登録がずれた場合も
    # MCPなしの取得不能側へ倒す。list化して呼び出し間のmutable状態も共有しない。
    active_mcp_servers = list(mcp_servers) if gateway_available and mcp_servers else []
    is_gateway_available = bool(active_mcp_servers)
    weather = Agent(
        name="Weather Agent",
        instructions=(
            WEATHER_AVAILABLE_INSTRUCTIONS
            if is_gateway_available
            else WEATHER_UNAVAILABLE_INSTRUCTIONS
        ),
        model=model,
        tools=[],
        handoffs=[],
        mcp_servers=active_mcp_servers,
    )
    weather_tool = weather.as_tool(
        tool_name=WEATHER_TOOL_NAME,
        tool_description=WEATHER_TOOL_DESCRIPTION,
    )
    # Gateway ToolをManagerへ直接渡さず、会話と最終回答の所有境界を維持する。
    manager = Agent(
        name="Manager Agent",
        instructions=(
            MANAGER_AVAILABLE_INSTRUCTIONS
            if is_gateway_available
            else MANAGER_UNAVAILABLE_INSTRUCTIONS
        ),
        model=model,
        tools=[weather_tool],
        handoffs=[],
        mcp_servers=[],
    )
    return AgentBundle(manager=manager, weather=weather)
