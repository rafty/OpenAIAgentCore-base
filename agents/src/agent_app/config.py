"""Agentアプリケーションの非秘密設定を読み込み、起動時に検証する。"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass


AWS_REGION = "us-east-2"
BEDROCK_OPENAI_MODEL_ID = "openai.gpt-5.5"
TRACING_DISABLED_VALUE = "1"


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

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> AppConfig:
        """Runtime環境変数を読み込み、仕様で固定された値だけを受理する。"""

        values = os.environ if environ is None else environ
        aws_region = values.get("AWS_REGION", "").strip()
        model_id = values.get("BEDROCK_OPENAI_MODEL_ID", "").strip()
        memory_id = values.get("AGENTCORE_MEMORY_ID", "").strip()
        tracing_disabled = values.get("OPENAI_AGENTS_DISABLE_TRACING", "").strip()

        # 個別の値を含む例外を返さず、設定値や認証情報が応答へ漏れる余地を作らない。
        if (
            aws_region != AWS_REGION
            or model_id != BEDROCK_OPENAI_MODEL_ID
            or not memory_id
            or tracing_disabled != TRACING_DISABLED_VALUE
        ):
            raise ConfigurationError()

        return cls(
            aws_region=aws_region,
            model_id=model_id,
            memory_id=memory_id,
            tracing_disabled=tracing_disabled,
        )
