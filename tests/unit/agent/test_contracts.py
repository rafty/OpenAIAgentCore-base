"""HTTP入力境界と公開SSE event schemaを確認するテスト。"""

import pytest

from agent_app.contracts import (
    ContractValidationError,
    bad_request_response,
    completed_event,
    error_event,
    server_error_response,
    text_delta_event,
    validate_invocation,
)


def test_valid_input_uses_context_session_id() -> None:
    result = validate_invocation(
        {"prompt": "質問", "actor_id": "actor/group:member", "runtimeSessionId": "ignored"},
        "runtime-session_1",
    )
    assert result.prompt == "質問"
    assert result.actor_id == "actor/group:member"
    assert result.session_id == "runtime-session_1"


@pytest.mark.parametrize(
    ("payload", "session_id"),
    [
        ([], "session"),
        ({"actor_id": "actor"}, "session"),
        ({"prompt": "", "actor_id": "actor"}, "session"),
        ({"prompt": "   ", "actor_id": "actor"}, "session"),
        ({"prompt": 1, "actor_id": "actor"}, "session"),
        ({"prompt": "x"}, "session"),
        ({"prompt": "x", "actor_id": ""}, "session"),
        ({"prompt": "x", "actor_id": "-actor"}, "session"),
        ({"prompt": "x", "actor_id": "actor!"}, "session"),
        ({"prompt": "x", "actor_id": "a" * 256}, "session"),
        ({"prompt": "x", "actor_id": "actor"}, None),
        ({"prompt": "x", "actor_id": "actor"}, "-session"),
        ({"prompt": "x", "actor_id": "actor"}, "s" * 101),
    ],
)
def test_invalid_input_is_rejected(payload: object, session_id: object) -> None:
    with pytest.raises(ContractValidationError):
        validate_invocation(payload, session_id)


def test_boundary_lengths_are_accepted() -> None:
    assert validate_invocation({"prompt": "x", "actor_id": "a" * 255}, "s" * 100)


def test_safe_http_and_stream_events() -> None:
    assert bad_request_response().status_code == 400
    assert server_error_response().status_code == 500
    assert text_delta_event("差分") == {"type": "text_delta", "delta": "差分"}
    assert completed_event() == {"type": "completed"}
    assert error_event() == {
        "type": "error",
        "message": "処理中にエラーが発生しました。",
    }
