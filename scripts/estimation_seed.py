#!/usr/bin/env python3
"""Estimation Sample Dataの検証、投入、待機、限定後片付けCLI。"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping

# `python scripts/...py`でもリポジトリ直下の共通モジュールを同じ実装として
# 読み込めるよう、直接実行時だけpackage rootを解決する。
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import boto3
from botocore.config import Config

from lambda_tools.estimation.embedding import (
    DIMENSIONS,
    MODEL_ID,
    NORMALIZATION_VERSION,
    BedrockEmbeddingAdapter,
    embedding_source_hash,
    normalize_text,
)
from lambda_tools.estimation.repository import INDEX_NAME, TABLE_NAME, EstimationRepository
from lambda_tools.estimation.sample_data import SeedBundle, load_seed_bundle


DEFAULT_SOURCE = Path(__file__).resolve().parents[1] / "dynamodb-seed"
DEFAULT_STACK_NAME = "OpenAiAgentCoreBaseStack"


def _aws_clients(region: str) -> tuple[Any, Any, Any]:
    config = Config(connect_timeout=5, read_timeout=20, retries={"max_attempts": 3})
    return (
        boto3.client("cloudformation", region_name=region, config=config),
        boto3.client("dynamodb", region_name=region, config=config),
        boto3.client("bedrock-runtime", region_name=region, config=config),
    )


def resolve_resources(
    cloudformation: Any,
    *,
    stack_name: str,
    table_name: str | None,
    index_name: str | None,
) -> tuple[str, str]:
    """明示値を優先し、不足分だけをCloudFormation出力から解決する。"""

    if table_name and index_name:
        return table_name, index_name
    response = cloudformation.describe_stacks(StackName=stack_name)
    stacks = response.get("Stacks", [])
    if len(stacks) != 1:
        raise RuntimeError("対象CloudFormation Stackを一意に解決できません。")
    outputs = {
        item.get("OutputKey"): item.get("OutputValue")
        for item in stacks[0].get("Outputs", [])
    }
    resolved_table = table_name or outputs.get("EstimationTableName")
    resolved_index = index_name or outputs.get("EstimationVectorIndexName")
    if not resolved_table or not resolved_index:
        raise RuntimeError("EstimationのCloudFormation出力が不足しています。")
    return str(resolved_table), str(resolved_index)


def wait_for_index(
    dynamodb: Any,
    *,
    table_name: str,
    index_name: str,
    timeout_seconds: int,
    interval_seconds: float = 5,
) -> None:
    """非同期Vector Indexが検索可能になるまで対象Indexだけを確認する。"""

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        table = dynamodb.describe_table(TableName=table_name).get("Table", {})
        index = next(
            (
                item
                for item in table.get("VectorIndexes", [])
                if item.get("IndexName") == index_name
            ),
            None,
        )
        if index is not None and index.get("IndexStatus") == "ACTIVE":
            return
        if index is not None and index.get("IndexStatus") in {"FAILED", "DELETING"}:
            raise RuntimeError("Vector Indexが検索可能な状態になりません。")
        time.sleep(interval_seconds)
    raise TimeoutError("Vector IndexのACTIVE待機がtimeoutしました。")


def _summary_item(summary: Mapping[str, Any]) -> dict[str, Any]:
    return {"PK": f"PROJECT#{summary['project_id']}", "SK": "SUMMARY", **summary}


def _actual_item(actual: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "PK": f"PROJECT#{actual['project_id']}",
        "SK": "ACTUAL#FINAL",
        "entity_type": "PROJECT_ACTUAL",
        **actual,
    }


def _master_items(bundle: SeedBundle) -> Iterable[dict[str, Any]]:
    for item in bundle.effort_standards:
        yield {
            "PK": f"MASTER#EFFORT#{item['service']}#{item['task_type']}",
            "SK": f"VALID_FROM#{item['valid_from']}#VERSION#{int(item['version']):04d}",
            "entity_type": "EFFORT_STANDARD",
            **item,
        }
    for item in bundle.rate_cards:
        yield {
            "PK": f"MASTER#RATE#{item['role']}",
            "SK": f"VALID_FROM#{item['valid_from']}#VERSION#{int(item['version']):04d}",
            "entity_type": "RATE_CARD",
            **item,
        }
    for item in bundle.pricing_policies:
        yield {
            "PK": f"MASTER#PRICING#{item['policy_id']}",
            "SK": f"VALID_FROM#{item['valid_from']}#VERSION#{int(item['version']):04d}",
            "entity_type": "PRICING_POLICY",
            **item,
        }


def apply_seed(
    bundle: SeedBundle,
    repository: EstimationRepository,
    embedding: BedrockEmbeddingAdapter,
) -> dict[str, int]:
    """正本JSONを変更せず、生成Vectorとメタデータを実行時Itemだけへ追加する。"""

    counts = {"embedded": 0, "summary_skipped": 0, "structured_upserted": 0}
    for source in bundle.project_summaries:
        item = _summary_item(source)
        normalized = normalize_text(str(source["search_summary"]))
        source_hash = embedding_source_hash(normalized, "search_document")
        existing = repository.get_item(str(item["PK"]), str(item["SK"]))
        if (
            existing is not None
            and existing.get("embedding_source_hash") == source_hash
            and existing.get("embedding_model_id") == MODEL_ID
            and int(existing.get("embedding_dimensions", 0)) == DIMENSIONS
            and existing.get("embedding_normalization_version") == NORMALIZATION_VERSION
        ):
            # hash一致ならBedrock呼び出しと書き込みの両方を省略し、再投入を安価で
            # 冪等な運用にする。
            counts["summary_skipped"] += 1
            continue
        generated = embedding.embed(str(source["search_summary"]), input_type="search_document")
        item.update(
            {
                # boto3の低レベルDynamoDB serializerはfloatを受理しないため、
                # Bedrock応答を保存する境界で有限値をDecimalへ変換する。正本JSONと
                # Embeddingアダプターの契約は実行時Vectorから独立させる。
                "embedding": [Decimal(str(value)) for value in generated.vector],
                "embedding_model_id": MODEL_ID,
                "embedding_input_type": "search_document",
                "embedding_dimensions": DIMENSIONS,
                "embedding_source_hash": generated.source_hash,
                "embedding_normalization_version": NORMALIZATION_VERSION,
                "embedding_generated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        repository.batch_seed([item])
        counts["embedded"] += 1

    structured_items = [
        *(_actual_item(item) for item in bundle.project_actuals),
        *_master_items(bundle),
    ]
    repository.batch_seed(structured_items)
    counts["structured_upserted"] = len(structured_items)
    return counts


def cleanup_draft(
    repository: EstimationRepository,
    *,
    project_id: str,
    estimate_id: str,
    version: int,
) -> bool:
    """完全なDraft IDから当該Draftと対応する冪等性Itemだけを削除する。"""

    draft = repository.get_draft(project_id, estimate_id, version)
    if draft is None:
        return False
    actor_id = draft.get("created_by")
    idempotency_key = draft.get("idempotency_key")
    if not isinstance(actor_id, str) or not isinstance(idempotency_key, str):
        raise RuntimeError("関連する冪等性Itemを安全に特定できません。")
    repository.delete_saved_draft(
        project_id=project_id,
        estimate_id=estimate_id,
        version=version,
        actor_id=actor_id,
        idempotency_key=idempotency_key,
    )
    return True


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--stack-name", default=DEFAULT_STACK_NAME)
    parser.add_argument("--table-name")
    parser.add_argument("--index-name")
    subparsers = parser.add_subparsers(dest="command")
    validate = subparsers.add_parser("validate")
    # tasks.mdと手動手順で使う`validate --source ...`も受理し、未指定時は
    # 親parserの既定値を上書きしない。
    validate.add_argument("--source", type=Path, default=argparse.SUPPRESS)
    wait = subparsers.add_parser("wait-index")
    wait.add_argument("--timeout-seconds", type=int, default=3600)
    apply = subparsers.add_parser("apply")
    apply.add_argument("--apply", action="store_true", dest="confirmed")
    apply.add_argument("--timeout-seconds", type=int, default=3600)
    cleanup = subparsers.add_parser("cleanup-draft")
    cleanup.add_argument("--apply", action="store_true", dest="confirmed")
    cleanup.add_argument("--project-id", required=True)
    cleanup.add_argument("--estimate-id", required=True)
    cleanup.add_argument("--version", type=int, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    command = args.command or "validate"
    bundle = load_seed_bundle(args.source)
    if command == "validate":
        print(json.dumps({"status": "VALID", "source": str(args.source)}, ensure_ascii=False))
        return 0
    if command in {"apply", "cleanup-draft"} and not args.confirmed:
        # 書き込みと削除はコマンド名だけで実行せず、明示flagを二重確認にする。
        raise SystemExit("変更操作には --apply が必要です。")
    cloudformation, dynamodb, bedrock = _aws_clients(args.region)
    table_name, index_name = resolve_resources(
        cloudformation,
        stack_name=args.stack_name,
        table_name=args.table_name,
        index_name=args.index_name,
    )
    repository = EstimationRepository(
        dynamodb,
        table_name=table_name,
        index_name=index_name,
    )
    if command == "wait-index":
        wait_for_index(
            dynamodb,
            table_name=table_name,
            index_name=index_name,
            timeout_seconds=args.timeout_seconds,
        )
        print(json.dumps({"status": "ACTIVE", "index_name": index_name}, ensure_ascii=False))
        return 0
    if command == "apply":
        # Index不整合期間へVector Itemを投入しないようACTIVEを先に確認する。
        wait_for_index(
            dynamodb,
            table_name=table_name,
            index_name=index_name,
            timeout_seconds=args.timeout_seconds,
        )
        counts = apply_seed(bundle, repository, BedrockEmbeddingAdapter(bedrock))
        print(json.dumps({"status": "APPLIED", **counts}, ensure_ascii=False))
        return 0
    deleted = cleanup_draft(
        repository,
        project_id=args.project_id,
        estimate_id=args.estimate_id,
        version=args.version,
    )
    print(json.dumps({"status": "DELETED" if deleted else "NOT_FOUND"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
