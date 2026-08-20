"""固定Bedrock Embedding境界をfake clientで検証する。"""

import io
import json

import pytest
from botocore.exceptions import ClientError

from lambda_tools.estimation.embedding import (
    DIMENSIONS,
    MODEL_ID,
    BedrockEmbeddingAdapter,
    embedding_source_hash,
    normalize_text,
)
from lambda_tools.estimation.errors import DependencyUnavailableError, ValidationError


class FakeBedrock:
    def __init__(self, failures: list[Exception] | None = None) -> None:
        self.failures = list(failures or [])
        self.calls: list[dict[str, object]] = []

    def invoke_model(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        if self.failures:
            raise self.failures.pop(0)
        return {
            "body": io.BytesIO(
                json.dumps({"embeddings": {"float": [[0.0] * DIMENSIONS]}}).encode()
            )
        }


def _client_error(code: str, status: int) -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": "private"}, "ResponseMetadata": {"HTTPStatusCode": status}},
        "InvokeModel",
    )


def test_normalization_hash_and_input_type_are_reproducible() -> None:
    assert normalize_text(" Ａ  B\r\n\r\n C ") == "A B\n\nC"
    assert embedding_source_hash("same", "search_document") == embedding_source_hash(
        "same", "search_document"
    )
    assert embedding_source_hash("same", "search_document") != embedding_source_hash(
        "same", "search_query"
    )
    client = FakeBedrock()
    result = BedrockEmbeddingAdapter(client).embed("検索 文", input_type="search_query")
    body = json.loads(client.calls[0]["body"])  # type: ignore[arg-type]
    assert client.calls[0]["modelId"] == MODEL_ID
    assert body["input_type"] == "search_query"
    assert body["truncate"] == "NONE"
    assert len(result.vector) == DIMENSIONS


def test_input_and_response_limits_fail_before_or_after_bedrock() -> None:
    client = FakeBedrock()
    with pytest.raises(ValidationError):
        BedrockEmbeddingAdapter(client).embed("x" * 2049, input_type="search_query")
    with pytest.raises(ValidationError):
        BedrockEmbeddingAdapter(client).embed("x", input_type="classification")
    assert client.calls == []

    malformed = FakeBedrock()
    malformed.invoke_model = lambda **_: {"body": json.dumps({"embeddings": [[0.0]]})}  # type: ignore[method-assign]
    with pytest.raises(ValidationError):
        BedrockEmbeddingAdapter(malformed).embed("x", input_type="search_document")


def test_transient_is_retried_three_times_but_permanent_is_not() -> None:
    transient = FakeBedrock([_client_error("ThrottlingException", 429)] * 3)
    metrics: list[dict[str, object]] = []
    with pytest.raises(DependencyUnavailableError):
        BedrockEmbeddingAdapter(
            transient,
            sleep=lambda _: None,
            jitter=lambda: 0,
            metrics_sink=metrics.append,
        ).embed("x", input_type="search_query")
    assert len(transient.calls) == 3
    assert metrics[-1]["EmbeddingRetries"] == 2
    assert "x" not in json.dumps(metrics, ensure_ascii=False)

    permanent = FakeBedrock([_client_error("ValidationException", 400)])
    with pytest.raises(DependencyUnavailableError):
        BedrockEmbeddingAdapter(permanent).embed("x", input_type="search_query")
    assert len(permanent.calls) == 1
