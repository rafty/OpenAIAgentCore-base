"""Agentアプリケーションの非秘密設定を読み込み、起動時に検証する。"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit


AWS_REGION = "us-east-2"
BEDROCK_OPENAI_MODEL_ID = "openai.gpt-5.5"
TRACING_DISABLED_VALUE = "1"
GATEWAY_HOST_SUFFIX = ".gateway.bedrock-agentcore.us-east-2.amazonaws.com"
GATEWAY_PATH = "/mcp"
GATEWAY_TARGET_NAME_MAX_LENGTH = 100
_GATEWAY_ID_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?")
_GATEWAY_TARGET_NAME_PATTERN = re.compile(
    r"[a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9]))*"
)


class ConfigurationError(RuntimeError):
    """利用者へ内部設定値を露出しない起動時設定エラー。"""

    def __init__(self) -> None:
        super().__init__("Agentアプリケーションの設定が不正です。")


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Runtimeから供給される非秘密設定。"""

    aws_region: str
    model_id: str
    memory_id: str
    tracing_disabled: str
    gateway_url: str
    gateway_target_name: str

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> AppConfig:
        """Runtime環境変数を読み込み、仕様で固定された値だけを受理する。"""

        values = os.environ if environ is None else environ
        aws_region = values.get("AWS_REGION", "").strip()
        model_id = values.get("BEDROCK_OPENAI_MODEL_ID", "").strip()
        memory_id = values.get("AGENTCORE_MEMORY_ID", "").strip()
        tracing_disabled = values.get("OPENAI_AGENTS_DISABLE_TRACING", "").strip()
        gateway_url = values.get("AGENTCORE_GATEWAY_URL", "").strip()
        gateway_target_name = values.get("AGENTCORE_GATEWAY_TARGET_NAME", "").strip()

        # Gateway URLはSigV4の署名先になるため、scheme・region・service hostを固定し、
        # 利用者が任意の送信先へRuntime認証情報を署名させる余地を作らない。
        if (
            aws_region != AWS_REGION
            or model_id != BEDROCK_OPENAI_MODEL_ID
            or not memory_id
            or tracing_disabled != TRACING_DISABLED_VALUE
            or not _is_valid_gateway_url(gateway_url)
            or not _is_valid_gateway_target_name(gateway_target_name)
        ):
            # 個別値を例外へ含めず、内部endpointや設定値がHTTP応答へ漏れないようにする。
            raise ConfigurationError()

        return cls(
            aws_region=aws_region,
            model_id=model_id,
            memory_id=memory_id,
            tracing_disabled=tracing_disabled,
            gateway_url=gateway_url,
            gateway_target_name=gateway_target_name,
        )


def _is_valid_gateway_url(value: str) -> bool:
    """専用GatewayのSigV4署名先として許可するURLだけを判定する。"""

    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False

    hostname = parsed.hostname or ""
    if not hostname.endswith(GATEWAY_HOST_SUFFIX):
        return False
    gateway_id = hostname.removesuffix(GATEWAY_HOST_SUFFIX)
    return (
        parsed.scheme == "https"
        and parsed.netloc == hostname
        and parsed.username is None
        and parsed.password is None
        and port is None
        and parsed.path == GATEWAY_PATH
        and not parsed.query
        and not parsed.fragment
        and _GATEWAY_ID_PATTERN.fullmatch(gateway_id) is not None
    )


def _is_valid_gateway_target_name(value: str) -> bool:
    """固定Tool接頭辞として安全に扱えるGatewayTarget名かを判定する。"""

    return (
        1 <= len(value) <= GATEWAY_TARGET_NAME_MAX_LENGTH
        and _GATEWAY_TARGET_NAME_PATTERN.fullmatch(value) is not None
    )
