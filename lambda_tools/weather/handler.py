from typing import Any


TOOL_NAME_DELIMITER = "___"


def _get_tool_name(context: Any) -> str:
    """Extract the original tool name from AgentCore Lambda context metadata."""
    client_context = getattr(context, "client_context", None)
    custom = getattr(client_context, "custom", None) or {}
    full_tool_name = custom.get("bedrockAgentCoreToolName", "")

    if TOOL_NAME_DELIMITER in full_tool_name:
        return full_tool_name.split(TOOL_NAME_DELIMITER, maxsplit=1)[1]
    return full_tool_name


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Handle the tools registered in schemas/tools.json."""
    tool_name = _get_tool_name(context)

    if tool_name == "get_weather":
        location = event.get("location")
        if not isinstance(location, str) or not location.strip():
            return {"error": "location is required"}
        return {
            "location": location,
            "weather": "72 degrees Fahrenheit, Sunny",
            "data_type": "mock",
        }

    if tool_name == "get_time":
        timezone = event.get("timezone")
        if not isinstance(timezone, str) or not timezone.strip():
            return {"error": "timezone is required"}
        return {
            "timezone": timezone,
            "local_time": "2:30 PM",
            "data_type": "mock",
        }

    return {
        "error": "Unknown tool",
        "received_tool_name": tool_name,
    }
