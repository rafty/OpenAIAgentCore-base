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
    assert success.status_code == 200
    events = _events(success)
    assert events == [
        {"type": "text_delta", "delta": "container"},
        {"type": "completed"},
    ]
    assert sum(event["type"] == "completed" for event in events) == 1
    assert all(event["type"] != "error" for event in events)


def test_container_harness_error_sse(monkeypatch) -> None:
    monkeypatch.setenv("CONTAINER_TEST_MODE", "error")
    with TestClient(create_harness_app()) as client:
        response = client.post(
            "/invocations",
            json={"prompt": "x", "actor_id": "actor"},
            headers={SESSION_HEADER: "session"},
        )
    assert response.status_code == 200
    events = _events(response)
    assert events == [
        {"type": "text_delta", "delta": "container"},
        {"type": "error", "message": "処理中にエラーが発生しました。"},
    ]
    assert sum(event["type"] == "error" for event in events) == 1
    assert all(event["type"] != "completed" for event in events)
