"""本番Runtime factoryを利用するコンテナハーネスのHTTP契約テスト。"""

import json

from starlette.testclient import TestClient

from tests.container.harness_main import create_harness_app


SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"


def _events(response):
    """BedrockAgentCoreAppが生成したSSEからdata JSONだけを取り出す。"""

    return [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def test_container_harness_uses_production_http_contract(monkeypatch) -> None:
    monkeypatch.setenv("CONTAINER_TEST_MODE", "success")
    with TestClient(create_harness_app()) as client:
        ping = client.get("/ping")
        invalid = client.post("/invocations", json={"prompt": ""})
        success = client.post(
            "/invocations",
            json={"prompt": "x", "actor_id": "actor"},
            headers={SESSION_HEADER: "session"},
        )
    assert ping.status_code == 200
    assert ping.json()["status"] in {"Healthy", "HealthyBusy"}
    assert invalid.status_code == 400
    assert _events(success) == [
        {"type": "text_delta", "delta": "container"},
        {"type": "completed"},
    ]


def test_container_harness_error_sse(monkeypatch) -> None:
    monkeypatch.setenv("CONTAINER_TEST_MODE", "error")
    with TestClient(create_harness_app()) as client:
        response = client.post(
            "/invocations",
            json={"prompt": "x", "actor_id": "actor"},
            headers={SESSION_HEADER: "session"},
        )
    assert _events(response)[-1]["type"] == "error"
    assert all(event["type"] != "completed" for event in _events(response))
