"""Estimation Seed CLIの保存境界と冪等性を検証する。"""

from decimal import Decimal
from pathlib import Path

from boto3.dynamodb.types import TypeSerializer

from lambda_tools.estimation.embedding import EmbeddingResult
from lambda_tools.estimation.sample_data import load_seed_bundle
from scripts.estimation_seed import apply_seed


SOURCE = Path(__file__).resolve().parents[2] / "dynamodb-seed"


class FakeEmbedding:
    def embed(self, text: str, *, input_type: str) -> EmbeddingResult:
        assert input_type == "search_document"
        return EmbeddingResult([0.25] * 1024, "source-hash", text, input_type)


class CapturingRepository:
    def __init__(self) -> None:
        self.items: list[dict[str, object]] = []

    def get_item(self, _pk: str, _sk: str):
        return None

    def batch_seed(self, items) -> None:
        serializer = TypeSerializer()
        for item in items:
            # 実DynamoDBへ到達する前と同じserializerでfloat混入を検出する。
            {key: serializer.serialize(value) for key, value in item.items()}
            self.items.append(dict(item))


def test_apply_seed_serializes_generated_vectors_as_dynamodb_numbers() -> None:
    repository = CapturingRepository()
    counts = apply_seed(
        load_seed_bundle(SOURCE),
        repository,  # type: ignore[arg-type]
        FakeEmbedding(),  # type: ignore[arg-type]
    )

    summaries = [item for item in repository.items if item.get("SK") == "SUMMARY"]
    assert counts["embedded"] == 3
    assert len(summaries) == 3
    assert all(len(item["embedding"]) == 1024 for item in summaries)  # type: ignore[arg-type]
    assert all(
        isinstance(value, Decimal)
        for item in summaries
        for value in item["embedding"]  # type: ignore[union-attr]
    )
