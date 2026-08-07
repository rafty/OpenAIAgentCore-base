"""Weather／TimeモックToolのスキーマとLambda応答契約を確認するテスト。"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any

import pytest

from lambda_tools.weather.handler import TOOL_ERROR_MESSAGE, lambda_handler


ROOT = Path(__file__).resolve().parents[2]
TOOLS_PATH = ROOT / "lambda_tools" / "weather" / "tools.json"
TARGET_NAME = "WeatherTimeMock"
NORMAL_OUTPUT_FIELDS = {
    "location",
    "weather",
    "timezone",
    "local_time",
    "data_type",
}
TOOL_CASES = (
    (
        "get_weather",
        "location",
        "Tokyo",
        {
            "location": "Tokyo",
            "weather": "72 degrees Fahrenheit, Sunny",
            "data_type": "mock",
        },
    ),
    (
        "get_time",
        "timezone",
        "Asia/Tokyo",
        {
            "timezone": "Asia/Tokyo",
            "local_time": "2:30 PM",
            "data_type": "mock",
        },
    ),
)


@pytest.fixture
def gateway_context() -> Callable[[str], SimpleNamespace]:
    """AgentCore GatewayがLambda contextへ格納する公開Tool名を再現する。"""

    def build(tool_name: str) -> SimpleNamespace:
        # GatewayはTarget名と元Tool名を`___`で連結してcustom metadataへ渡す。
        return SimpleNamespace(
            client_context=SimpleNamespace(
                custom={"bedrockAgentCoreToolName": f"{TARGET_NAME}___{tool_name}"}
            )
        )

    return build


def _assert_json_compatible(result: dict[str, Any]) -> None:
    encoded = json.dumps(result, ensure_ascii=False)
    assert json.loads(encoded) == result


def _assert_safe_error(result: dict[str, Any], *received_values: str) -> None:
    """異常応答が正常値や受信した内部値を反射しないことを確認する。"""

    assert result == {"error": TOOL_ERROR_MESSAGE}
    assert NORMAL_OUTPUT_FIELDS.isdisjoint(result)
    encoded = json.dumps(result, ensure_ascii=False)
    for received_value in received_values:
        if received_value:
            assert received_value not in encoded
    _assert_json_compatible(result)


def test_tools_json_defines_only_supported_mock_tool_contracts() -> None:
    schema = json.loads(TOOLS_PATH.read_text(encoding="utf-8"))

    assert isinstance(schema, list)
    assert {tool["name"] for tool in schema} == {"get_weather", "get_time"}
    assert len(schema) == 2

    by_name = {tool["name"]: tool for tool in schema}
    for tool_name, input_name, _, _ in TOOL_CASES:
        tool = by_name[tool_name]
        description = tool["description"].lower()
        assert "mock" in description
        assert "does not call a real" in description

        input_schema = tool["inputSchema"]
        assert input_schema["type"] == "object"
        assert set(input_schema["properties"]) == {input_name}
        assert input_schema["properties"][input_name]["type"] == "string"
        assert input_schema["required"] == [input_name]


@pytest.mark.parametrize(
    ("tool_name", "input_name", "input_value", "expected"),
    TOOL_CASES,
    ids=("weather", "time"),
)
def test_handler_returns_json_compatible_fixed_mock_results(
    gateway_context: Callable[[str], SimpleNamespace],
    tool_name: str,
    input_name: str,
    input_value: str,
    expected: dict[str, Any],
) -> None:
    result = lambda_handler({input_name: input_value}, gateway_context(tool_name))

    assert result == expected
    assert result["data_type"] == "mock"
    _assert_json_compatible(result)


def test_handler_accepts_mapping_event_and_preserves_non_blank_input(
    gateway_context: Callable[[str], SimpleNamespace],
) -> None:
    # Gateway入力はdict互換のMappingで届くため、具象dictだけへ限定しない契約を固定する。
    event = MappingProxyType({"location": " Tokyo "})

    result = lambda_handler(event, gateway_context("get_weather"))

    assert result["location"] == " Tokyo "
    assert result["weather"] == "72 degrees Fahrenheit, Sunny"
    assert result["data_type"] == "mock"
    _assert_json_compatible(result)


@pytest.mark.parametrize(
    "event",
    [None, "private-event", ["private-event"], 1, True],
    ids=("none", "string", "list", "integer", "boolean"),
)
def test_non_mapping_event_returns_only_safe_error(event: Any) -> None:
    result = lambda_handler(
        event,
        SimpleNamespace(
            client_context=SimpleNamespace(
                custom={"bedrockAgentCoreToolName": f"{TARGET_NAME}___get_weather"}
            )
        ),
    )

    _assert_safe_error(result, "private-event")


@pytest.mark.parametrize(
    ("tool_name", "input_name", "event"),
    [
        ("get_weather", "location", {}),
        ("get_weather", "location", {"timezone": "private-input"}),
        ("get_weather", "location", {"location": None}),
        ("get_weather", "location", {"location": 1}),
        ("get_weather", "location", {"location": True}),
        ("get_weather", "location", {"location": []}),
        ("get_weather", "location", {"location": {}}),
        ("get_weather", "location", {"location": ""}),
        ("get_weather", "location", {"location": " "}),
        ("get_weather", "location", {"location": "\t\n"}),
        ("get_time", "timezone", {}),
        ("get_time", "timezone", {"location": "private-input"}),
        ("get_time", "timezone", {"timezone": None}),
        ("get_time", "timezone", {"timezone": 1}),
        ("get_time", "timezone", {"timezone": True}),
        ("get_time", "timezone", {"timezone": []}),
        ("get_time", "timezone", {"timezone": {}}),
        ("get_time", "timezone", {"timezone": ""}),
        ("get_time", "timezone", {"timezone": " "}),
        ("get_time", "timezone", {"timezone": "\t\n"}),
    ],
    ids=(
        "weather-missing",
        "weather-wrong-field",
        "weather-none",
        "weather-integer",
        "weather-boolean",
        "weather-list",
        "weather-mapping",
        "weather-empty",
        "weather-space",
        "weather-whitespace",
        "time-missing",
        "time-wrong-field",
        "time-none",
        "time-integer",
        "time-boolean",
        "time-list",
        "time-mapping",
        "time-empty",
        "time-space",
        "time-whitespace",
    ),
)
def test_missing_or_invalid_tool_input_returns_only_safe_error(
    gateway_context: Callable[[str], SimpleNamespace],
    tool_name: str,
    input_name: str,
    event: dict[str, Any],
) -> None:
    result = lambda_handler(event, gateway_context(tool_name))

    assert input_name not in result
    _assert_safe_error(result, "private-input")


@pytest.mark.parametrize(
    ("context", "received_value"),
    [
        (None, ""),
        (SimpleNamespace(), ""),
        (SimpleNamespace(client_context=None), ""),
        (SimpleNamespace(client_context=SimpleNamespace(custom=["private-custom"])), "private-custom"),
        (SimpleNamespace(client_context=SimpleNamespace(custom={})), ""),
        (
            SimpleNamespace(
                client_context=SimpleNamespace(
                    custom={"bedrockAgentCoreToolName": 123}
                )
            ),
            "",
        ),
        (
            SimpleNamespace(
                client_context=SimpleNamespace(
                    custom={"bedrockAgentCoreToolName": ""}
                )
            ),
            "",
        ),
        (
            SimpleNamespace(
                client_context=SimpleNamespace(
                    custom={"bedrockAgentCoreToolName": "private-tool"}
                )
            ),
            "private-tool",
        ),
        (
            SimpleNamespace(
                client_context=SimpleNamespace(
                    custom={"bedrockAgentCoreToolName": "___get_weather"}
                )
            ),
            "get_weather",
        ),
        (
            SimpleNamespace(
                client_context=SimpleNamespace(
                    custom={"bedrockAgentCoreToolName": " WeatherTimeMock___get_weather"}
                )
            ),
            "WeatherTimeMock",
        ),
        (
            SimpleNamespace(
                client_context=SimpleNamespace(
                    custom={"bedrockAgentCoreToolName": "WeatherTimeMock___"}
                )
            ),
            "WeatherTimeMock",
        ),
        (
            SimpleNamespace(
                client_context=SimpleNamespace(
                    custom={
                        "bedrockAgentCoreToolName": "WeatherTimeMock___get_weather___private-tool"
                    }
                )
            ),
            "private-tool",
        ),
    ],
    ids=(
        "context-none",
        "client-context-missing",
        "client-context-none",
        "custom-non-mapping",
        "tool-name-missing",
        "tool-name-non-string",
        "tool-name-empty",
        "delimiter-missing",
        "target-empty",
        "target-surrounding-whitespace",
        "tool-empty",
        "delimiter-multiple",
    ),
)
def test_invalid_gateway_context_returns_only_safe_error(
    context: Any,
    received_value: str,
) -> None:
    # 壊れたcontextの内容は診断目的でも応答へ反射せず、Tool列挙を防ぐ。
    result = lambda_handler({"location": "private-location"}, context)

    _assert_safe_error(result, "private-location", received_value)


def test_unknown_tool_name_returns_only_safe_error() -> None:
    full_tool_name = f"{TARGET_NAME}___private_unknown_tool"
    context = SimpleNamespace(
        client_context=SimpleNamespace(
            custom={"bedrockAgentCoreToolName": full_tool_name}
        )
    )

    result = lambda_handler({"location": "private-location"}, context)

    _assert_safe_error(result, "private_unknown_tool", "private-location", full_tool_name)
