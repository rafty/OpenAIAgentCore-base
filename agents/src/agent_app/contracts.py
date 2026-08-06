"""Runtime HTTP入力とSSEイベントのアプリケーション契約。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, TypedDict, cast

from starlette.responses import JSONResponse


ACTOR_ID_MAX_LENGTH = 255
SESSION_ID_MAX_LENGTH = 100
_ACTOR_ID_PATTERN = re.compile(
    r"[a-zA-Z0-9][a-zA-Z0-9-_/]*(?::[a-zA-Z0-9-_/]+)*[a-zA-Z0-9-_/]*"
)
_SESSION_ID_PATTERN = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9-_]*")

BAD_REQUEST_MESSAGE = "入力内容が不正です。"
SERVER_ERROR_MESSAGE = "処理を開始できませんでした。"
STREAM_ERROR_MESSAGE = "処理中にエラーが発生しました。"


class ContractValidationError(ValueError):
    """安全な固定応答へ変換する入力契約違反。"""


@dataclass(frozen=True, slots=True)
class InvocationInput:
    prompt: str
    actor_id: str
    session_id: str


@dataclass(frozen=True, slots=True)
class InvocationPayload:
    prompt: str
    actor_id: str


class TextDeltaEvent(TypedDict):
    type: str
    delta: str


class CompletedEvent(TypedDict):
    type: str


class ErrorEvent(TypedDict):
    type: str
    message: str


StreamEvent = TextDeltaEvent | CompletedEvent | ErrorEvent


def validate_invocation(payload: Any, session_id: Any) -> InvocationInput:
    """payloadとRuntime由来session IDを一つの内部入力へ正規化する。"""

    validated_payload = validate_payload(payload)
    validated_session_id = validate_session_id(session_id)
    return InvocationInput(
        prompt=validated_payload.prompt,
        actor_id=validated_payload.actor_id,
        session_id=validated_session_id,
    )


def validate_payload(payload: Any) -> InvocationPayload:
    """利用者が送信できるJSON bodyだけを検証する。"""

    if not isinstance(payload, dict):
        raise ContractValidationError()

    prompt = payload.get("prompt")
    actor_id = payload.get("actor_id")

    if not isinstance(prompt, str) or not prompt.strip():
        raise ContractValidationError()
    if not _is_valid_actor_id(actor_id):
        raise ContractValidationError()
    return InvocationPayload(prompt=prompt, actor_id=actor_id)


def validate_session_id(session_id: Any) -> str:
    """bodyではなくAgentCore Runtimeコンテキスト由来のIDを検証する。"""

    if not _is_valid_session_id(session_id):
        raise ContractValidationError()
    return cast(str, session_id)


def _is_valid_actor_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= ACTOR_ID_MAX_LENGTH
        and _ACTOR_ID_PATTERN.fullmatch(value) is not None
    )


def _is_valid_session_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= SESSION_ID_MAX_LENGTH
        and _SESSION_ID_PATTERN.fullmatch(value) is not None
    )


def bad_request_response() -> JSONResponse:
    return JSONResponse({"error": BAD_REQUEST_MESSAGE}, status_code=400)


def server_error_response() -> JSONResponse:
    return JSONResponse({"error": SERVER_ERROR_MESSAGE}, status_code=500)


def text_delta_event(delta: str) -> TextDeltaEvent:
    return {"type": "text_delta", "delta": delta}


def completed_event() -> CompletedEvent:
    return {"type": "completed"}


def error_event() -> ErrorEvent:
    return {"type": "error", "message": STREAM_ERROR_MESSAGE}
