"""Runtime entrypointのHTTP検証順序とSSE変換を確認するテスト。"""

import json

from starlette.testclient import TestClient

from agent_app.config import AppConfig
from agent_app.runtime import create_runtime_app


SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"
CONFIG = AppConfig("us-east-2", "openai.gpt-5.5", "memory", "1")


def test_invalid_payload_does_not_build_model_or_session() -> None:
    calls = []

    def should_not_run(*args, **kwargs):
        # 入力エラーより後段の依存へ到達した場合、テストを即時失敗させる。
        calls.append((args, kwargs))
        raise AssertionError("dependency factory must not be called")

    app = create_runtime_app(
        config=CONFIG,
        model_factory=should_not_run,
        session_factory=should_not_run,
    )
    with TestClient(app) as client:
        response = client.post(
            "/invocations",
            json={"prompt": "", "actor_id": "actor"},
            headers={SESSION_HEADER: "session"},
        )
    assert response.status_code == 400
    assert response.json() == {"error": "入力内容が不正です。"}
    assert calls == []


def test_context_or_config_failure_returns_safe_5xx() -> None:
    app = create_runtime_app(config_loader=lambda: (_ for _ in ()).throw(RuntimeError("secret")))
    with TestClient(app) as client:
        no_context = client.post("/invocations", json={"prompt": "x", "actor_id": "actor"})
        bad_config = client.post(
            "/invocations",
            json={"prompt": "x", "actor_id": "actor"},
            headers={SESSION_HEADER: "session"},
        )
    assert no_context.status_code == 500
    assert bad_config.status_code == 500
    assert no_context.json() == {"error": "処理を開始できませんでした。"}
    assert "secret" not in bad_config.text


def test_valid_request_streams_json_sse_and_uses_context_session() -> None:
    invocations = []

    def session_factory(config, invocation):
        invocations.append(invocation)
        return object()

    async def stream_service(**kwargs):
        yield {"type": "text_delta", "delta": "A"}
        yield {"type": "text_delta", "delta": "B"}
        yield {"type": "completed"}

    app = create_runtime_app(
        config=CONFIG,
        manager_agent=object(),
        session_factory=session_factory,
        stream_service=stream_service,
    )
    with TestClient(app) as client:
        response = client.post(
            "/invocations",
            json={
                "prompt": "質問",
                "actor_id": "actor",
                "runtimeSessionId": "payload-session-must-not-be-used",
            },
            headers={SESSION_HEADER: "context-session"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    data = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert data == [
        {"type": "text_delta", "delta": "A"},
        {"type": "text_delta", "delta": "B"},
        {"type": "completed"},
    ]
    assert invocations[0].session_id == "context-session"
