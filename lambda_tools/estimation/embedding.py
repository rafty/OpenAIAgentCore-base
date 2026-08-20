"""Bedrock Cohere Embeddingの正規化、検証、再試行を共有する。"""

from __future__ import annotations

import hashlib
import json
import random
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError, ConnectTimeoutError, ReadTimeoutError

from .errors import DependencyUnavailableError, ValidationError


MODEL_ID = "cohere.embed-multilingual-v3"
DIMENSIONS = 1024
NORMALIZATION_VERSION = "v1"
MAX_INPUT_CHARACTERS = 2048
MAX_ATTEMPTS = 3
ATTEMPT_TIMEOUT_SECONDS = 15
TOTAL_TIMEOUT_SECONDS = 45
TRANSIENT_CODES = {
    "ThrottlingException",
    "TooManyRequestsException",
    "RequestTimeout",
    "RequestTimeoutException",
    "InternalServerException",
    "ServiceUnavailableException",
}


@dataclass(frozen=True)
class EmbeddingResult:
    vector: list[float]
    source_hash: str
    normalized_text: str
    input_type: str


def normalize_text(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ValidationError("Embedding入力は空でない文字列で指定してください")
    normalized = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.strip().split()) for line in normalized.split("\n")]
    compact: list[str] = []
    for line in lines:
        if line or (compact and compact[-1]):
            compact.append(line)
    result = "\n".join(compact).strip()
    if len(result) > MAX_INPUT_CHARACTERS:
        # 暗黙の切り詰めは保存Vectorと検索Vectorの意味空間を変えるため、
        # truncate=NONEと合わせて呼び出し前に明示的に拒否する。
        raise ValidationError("Embedding入力が2048文字を超えています")
    return result


def embedding_source_hash(normalized_text: str, input_type: str) -> str:
    canonical = json.dumps(
        {
            "dimensions": DIMENSIONS,
            "input_type": input_type,
            "model_id": MODEL_ID,
            "normalization_version": NORMALIZATION_VERSION,
            "text": normalized_text,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, (ConnectTimeoutError, ReadTimeoutError)):
        return True
    if isinstance(exc, ClientError):
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
        code = exc.response.get("Error", {}).get("Code", "")
        return code in TRANSIENT_CODES or int(status or 0) >= 500
    return isinstance(exc, BotoCoreError) and not isinstance(exc, ValidationError)


class BedrockEmbeddingAdapter:
    """DynamoDBを書き込まず、検証済みVectorだけを返すadapter。"""

    def __init__(
        self,
        client: Any,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        jitter: Callable[[], float] = random.random,
        metrics_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._client = client
        self._sleep = sleep
        self._clock = clock
        self._jitter = jitter
        self._metrics_sink = metrics_sink or (lambda _: None)

    def embed(self, text: str, *, input_type: str) -> EmbeddingResult:
        if input_type not in {"search_document", "search_query"}:
            raise ValidationError("Embedding input_typeが不正です")
        normalized = normalize_text(text)
        source_hash = embedding_source_hash(normalized, input_type)
        started = self._clock()
        attempts = 0
        throttles = 0
        while attempts < MAX_ATTEMPTS:
            attempts += 1
            try:
                response = self._client.invoke_model(
                    modelId=MODEL_ID,
                    contentType="application/json",
                    accept="application/json",
                    body=json.dumps(
                        {
                            "texts": [normalized],
                            "input_type": input_type,
                            "embedding_types": ["float"],
                            "truncate": "NONE",
                        }
                    ),
                )
                vector = self._parse_response(response)
                self._emit(started, attempts, throttles, "SUCCESS")
                return EmbeddingResult(vector, source_hash, normalized, input_type)
            except ValidationError:
                self._emit(started, attempts, throttles, "FAILURE")
                raise
            except Exception as exc:
                transient = _is_transient(exc)
                if isinstance(exc, ClientError) and exc.response.get("Error", {}).get("Code") in {
                    "ThrottlingException",
                    "TooManyRequestsException",
                }:
                    throttles += 1
                elapsed = self._clock() - started
                if not transient or attempts >= MAX_ATTEMPTS:
                    self._emit(started, attempts, throttles, "FAILURE")
                    raise DependencyUnavailableError("Embeddingを生成できません") from exc
                delay = min(2 ** (attempts - 1) + self._jitter(), TOTAL_TIMEOUT_SECONDS - elapsed)
                if delay <= 0 or elapsed + delay >= TOTAL_TIMEOUT_SECONDS:
                    self._emit(started, attempts, throttles, "FAILURE")
                    raise DependencyUnavailableError("Embeddingの総待機時間を超えました") from exc
                self._sleep(delay)
        raise DependencyUnavailableError("Embeddingを生成できません")

    @staticmethod
    def _parse_response(response: dict[str, Any]) -> list[float]:
        body = response.get("body")
        if hasattr(body, "read"):
            body = body.read()
        if isinstance(body, bytes):
            body = body.decode("utf-8")
        payload = json.loads(body) if isinstance(body, str) else body
        embeddings = payload.get("embeddings") if isinstance(payload, dict) else None
        if isinstance(embeddings, dict):
            embeddings = embeddings.get("float")
        if not isinstance(embeddings, list) or len(embeddings) != 1:
            raise ValidationError("Embedding応答の件数が不正です")
        vector = embeddings[0]
        if not isinstance(vector, list) or len(vector) != DIMENSIONS:
            raise ValidationError("Embedding応答は1024次元ではありません")
        converted = [float(value) for value in vector]
        if any(value != value or value in {float("inf"), float("-inf")} for value in converted):
            raise ValidationError("Embedding応答に有限でない値が含まれます")
        return converted

    def _emit(self, started: float, attempts: int, throttles: int, outcome: str) -> None:
        # 本文やVectorをdimensionへ含めず、呼出回数と結果だけをEMFへ渡す。
        self._metrics_sink(
            {
                "_aws": {
                    "Timestamp": int(time.time() * 1000),
                    "CloudWatchMetrics": [
                        {
                            "Namespace": "OpenAiAgentCore/Estimation",
                            "Dimensions": [["ModelId", "Outcome"]],
                            "Metrics": [
                                {"Name": "EmbeddingCalls", "Unit": "Count"},
                                {"Name": "EmbeddingRetries", "Unit": "Count"},
                                {"Name": "EmbeddingThrottles", "Unit": "Count"},
                                {"Name": "EmbeddingLatency", "Unit": "Milliseconds"},
                            ],
                        }
                    ],
                },
                "ModelId": MODEL_ID,
                "Outcome": outcome,
                "EmbeddingCalls": attempts,
                "EmbeddingRetries": max(0, attempts - 1),
                "EmbeddingThrottles": throttles,
                "EmbeddingLatency": max(0, int((self._clock() - started) * 1000)),
            }
        )
