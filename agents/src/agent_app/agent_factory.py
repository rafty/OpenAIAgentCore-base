"""マネージャーAgentとWeather AgentをAgents-as-Toolsで構成する。"""

from __future__ import annotations

from dataclasses import dataclass

from agents import Agent, Model


WEATHER_TOOL_NAME = "weather_agent"
WEATHER_TOOL_DESCRIPTION = (
    "天気に関する質問を担当する専門Agentです。現在は実データを取得するToolが未実装のため、"
    "取得不能であることだけを正確に案内し、天気を推測・捏造しません。"
)

WEATHER_INSTRUCTIONS = """あなたは天気分野を担当するWeather Agentです。
現在、実在する天気データを取得するToolは実装されていません。
現在の天気、予報、気温、降水などを取得できないことを明確に伝えてください。
取得していない情報を推測したり、架空の天気を事実として回答したりしてはいけません。
既存のlambda_tools/weatherを含む外部Toolは利用できません。
回答は日本語で、簡潔かつ正確に返してください。"""

MANAGER_INSTRUCTIONS = """あなたは利用者との会話と最終回答を所有するマネージャーAgentです。
天気に関する質問にはweather_agentを使用し、その専門結果を利用者向けの最終回答へ統合してください。
Weather Agentの実データ取得Toolは未実装です。あなた自身も天気を推測・捏造してはいけません。
専門Agentへ会話をHandoffせず、必ずあなたが日本語で最終回答を返してください。
天気以外の質問には、利用可能な情報の範囲で正確かつ簡潔に対応してください。"""


@dataclass(frozen=True, slots=True)
class AgentBundle:
    """実行起点のManagerと、Tool化したWeather Agentの組。"""

    manager: Agent
    weather: Agent


def create_agents(model: Model) -> AgentBundle:
    """同じmodelを共有するAgents-as-Tools構成を生成する。"""

    # Weather Agentには実データ取得Toolを渡さず、モデル単独での捏造をinstructionsで禁止する。
    weather = Agent(
        name="Weather Agent",
        instructions=WEATHER_INSTRUCTIONS,
        model=model,
        tools=[],
        handoffs=[],
    )
    weather_tool = weather.as_tool(
        tool_name=WEATHER_TOOL_NAME,
        tool_description=WEATHER_TOOL_DESCRIPTION,
    )
    # HandoffではなくToolとして登録するため、利用者との会話と最終回答はManagerが保持する。
    manager = Agent(
        name="Manager Agent",
        instructions=MANAGER_INSTRUCTIONS,
        model=model,
        tools=[weather_tool],
        handoffs=[],
    )
    return AgentBundle(manager=manager, weather=weather)
