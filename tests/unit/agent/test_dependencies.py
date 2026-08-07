"""コンテナと開発環境の固定依存、および公開APIの存在を確認するテスト。"""

import importlib
import importlib.metadata
import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
EXPECTED = {
    "openai-agents": "0.19.4",
    "openai": "2.53.0",
    "bedrock-agentcore": "1.20.0",
    "mcp-proxy-for-aws": "1.6.4",
    "mcp": "1.29.0",
}


def _pinned_requirements(lines: list[str]) -> dict[str, str]:
    """完全一致指定されたpackage名とversionだけを抽出する。"""

    result: dict[str, str] = {}
    for line in lines:
        match = re.fullmatch(r"([a-z0-9-]+)(?:\[[^]]+\])?==([^\s]+)", line.strip())
        if match:
            result[match.group(1)] = match.group(2)
    return result


def test_agent_dependencies_are_pinned_and_equal() -> None:
    requirements = _pinned_requirements(
        (ROOT / "agents" / "requirements.txt").read_text().splitlines()
    )
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    development = _pinned_requirements(pyproject["dependency-groups"]["dev"])

    assert {name: requirements[name] for name in EXPECTED} == EXPECTED
    assert {name: development[name] for name in EXPECTED} == EXPECTED
    assert {
        name: importlib.metadata.version(name) for name in EXPECTED
    } == EXPECTED


def test_required_public_interfaces_can_be_imported() -> None:
    imports = {
        "openai": ["AsyncOpenAI"],
        "openai.providers": ["bedrock"],
        "agents": ["Agent", "Runner", "SessionABC"],
        "agents.mcp": ["MCPServerStreamableHttp"],
        "agents.models.openai_responses": ["OpenAIResponsesModel"],
        "bedrock_agentcore": ["BedrockAgentCoreApp"],
        "bedrock_agentcore.memory": ["MemoryClient"],
        "mcp_proxy_for_aws.client": ["aws_iam_streamablehttp_client"],
    }
    for module_name, names in imports.items():
        module = importlib.import_module(module_name)
        for name in names:
            assert getattr(module, name) is not None


def test_mcp_latest_protocol_version_matches_gateway_contract() -> None:
    mcp_types = importlib.import_module("mcp.types")

    # 依存更新でクライアントの提示versionだけが暗黙に変わることを防ぎ、Gatewayとの契約を固定する。
    assert mcp_types.LATEST_PROTOCOL_VERSION == "2025-11-25"
