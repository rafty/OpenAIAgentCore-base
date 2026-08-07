from collections.abc import Mapping
from typing import Any


TOOL_NAME_DELIMITER = "___"
TOOL_ERROR_MESSAGE = "ツールを実行できませんでした。"


def _get_tool_name(context: Any) -> str | None:
    """AgentCore Lambda contextから検証済みのTool名を取得する。"""

    client_context = getattr(context, "client_context", None)
    custom = getattr(client_context, "custom", None) or {}
    # SDK objectとcustom Mappingを段階検証し、壊れたmetadataを正常呼び出しとして扱わない。
    if not isinstance(custom, Mapping):
        return None

    full_tool_name = custom.get("bedrockAgentCoreToolName")
    if not isinstance(full_tool_name, str) or not full_tool_name:
        return None
    # 公開名はTargetとToolの境界を示す`___`を一つだけ持つ必要がある。
    if full_tool_name.count(TOOL_NAME_DELIMITER) != 1:
        return None

    target_name, tool_name = full_tool_name.split(TOOL_NAME_DELIMITER)
    if not target_name or target_name.strip() != target_name or not tool_name:
        return None
    return tool_name


def lambda_handler(event: Any, context: Any) -> dict[str, Any]:
    """`tools.json`に登録した固定モックToolを安全に実行する。"""

    if not isinstance(event, Mapping):
        return {"error": TOOL_ERROR_MESSAGE}
    tool_name = _get_tool_name(context)

    if tool_name == "get_weather":
        location = event.get("location")
        if not isinstance(location, str) or not location.strip():
            return {"error": TOOL_ERROR_MESSAGE}
        return {
            "location": location,
            "weather": "72 degrees Fahrenheit, Sunny",
            "data_type": "mock",
        }

    if tool_name == "get_time":
        timezone = event.get("timezone")
        if not isinstance(timezone, str) or not timezone.strip():
            return {"error": TOOL_ERROR_MESSAGE}
        return {
            "timezone": timezone,
            "local_time": "2:30 PM",
            "data_type": "mock",
        }

    # 不正な入力やTool名をエラーへ反射せず、内部値の露出と列挙を防ぐ。
    return {"error": TOOL_ERROR_MESSAGE}
