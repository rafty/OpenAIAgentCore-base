"""実モデルを使わずAgent-as-Toolの実行経路を確認する結合テスト。"""

import asyncio
import json
from collections.abc import AsyncIterator

from agents import Model, Runner, set_tracing_disabled
from agents.items import ModelResponse
from agents.usage import Usage
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)

from agent_app.agent_factory import create_agents


class DeterministicMultiAgentModel(Model):
    """Weather Tool呼び出しとManager最終回答を決定的に返すテストmodel。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.weather_called = False

    async def get_response(
        self,
        system_instructions,
        input,
        model_settings,
        tools,
        output_schema,
        handoffs,
        tracing,
        **kwargs,
    ) -> ModelResponse:
        self.calls.append(
            {
                "instructions": system_instructions,
                "input": input,
                "tools": [tool.name for tool in tools],
                "handoffs": handoffs,
            }
        )

        # Weather Agent自身の呼び出しでは、取得不能という安全な専門回答を返す。
        if "あなたは天気分野を担当するWeather Agentです" in system_instructions:
            self.weather_called = True
            return _message("天気取得Toolは未実装のため、現在の天気は取得できません。", "weather")

        input_items = input if isinstance(input, list) else []
        # 初回のManager呼び出しだけでWeather Agent Toolを要求する。
        if not any(item.get("type") == "function_call_output" for item in input_items):
            return ModelResponse(
                output=[
                    ResponseFunctionToolCall(
                        arguments=json.dumps({"input": "東京の現在の天気を確認してください。"}),
                        call_id="weather-call",
                        name="weather_agent",
                        type="function_call",
                        status="completed",
                    )
                ],
                usage=Usage(),
                response_id=None,
            )

        # Tool結果を受け取った二回目はManager自身の最終回答にする。
        return _message(
            "Weather Agentで確認しましたが、天気取得Toolは未実装のため、現在の天気は案内できません。",
            "manager-final",
        )

    async def stream_response(self, *args, **kwargs) -> AsyncIterator:
        if False:
            yield None


def _message(text: str, item_id: str) -> ModelResponse:
    return ModelResponse(
        output=[
            ResponseOutputMessage(
                id=item_id,
                content=[ResponseOutputText(annotations=[], text=text, type="output_text")],
                role="assistant",
                status="completed",
                type="message",
            )
        ],
        usage=Usage(),
        response_id=None,
    )


def test_weather_agent_is_called_as_tool_and_manager_owns_final_answer() -> None:
    set_tracing_disabled(True)
    model = DeterministicMultiAgentModel()
    bundle = create_agents(model)

    result = asyncio.run(Runner.run(bundle.manager, "東京の現在の天気を教えてください。"))

    assert model.weather_called is True
    assert result.last_agent is bundle.manager
    assert result.final_output == (
        "Weather Agentで確認しましたが、天気取得Toolは未実装のため、現在の天気は案内できません。"
    )
    assert all(call["handoffs"] == [] for call in model.calls)
    assert "晴れ" not in result.final_output
    assert "雨" not in result.final_output
