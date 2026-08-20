#!/usr/bin/env python3
"""Sample Dataに限定したDynamoDB実Vector検索の回帰評価CLI。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lambda_tools.estimation.embedding import (
    DIMENSIONS,
    MODEL_ID,
    NORMALIZATION_VERSION,
    BedrockEmbeddingAdapter,
)
from lambda_tools.estimation.repository import EstimationRepository
from lambda_tools.estimation.sample_data import SeedBundle, load_seed_bundle
from scripts.estimation_seed import DEFAULT_SOURCE, DEFAULT_STACK_NAME, _aws_clients, resolve_resources


def _seed_hash(bundle: SeedBundle) -> str:
    payload = json.dumps(
        bundle.project_summaries,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=lambda value: format(value, "f") if isinstance(value, Decimal) else str(value),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _delta_query(bundle: SeedBundle) -> str:
    value = bundle.sample_project_delta["normalized_input"]
    components = "、".join(
        f"{item['service']} {item['quantity']} {item['unit']}"
        for item in value["components"]
    )
    return f"{value['architecture_summary']} {components} {' '.join(value['work_scope'])}"


def evaluation_cases(bundle: SeedBundle) -> list[dict[str, Any]]:
    """正本6件にDeltaを加え、期待値をPoC Sample Data内だけの回帰基準とする。"""

    return [
        *bundle.search_quality_cases,
        {
            "case_id": "SAMPLE-PROJECT-DELTA",
            "query": _delta_query(bundle),
            "filters": {
                "project_type": "NEW_BUILD",
                "architecture_family": "EC2_RDS_WEB",
                "outcome_quality": "ACCEPTED",
            },
            "expected_top1_project_id": "HIST-001",
        },
    ]


def evaluate(
    bundle: SeedBundle,
    repository: EstimationRepository,
    embedding: BedrockEmbeddingAdapter,
    *,
    region: str,
) -> dict[str, Any]:
    results = []
    for case in evaluation_cases(bundle):
        embedded = embedding.embed(str(case["query"]), input_type="search_query")
        candidates = repository.search_vectors(embedded.vector, case.get("filters", {}))
        ranking = [candidate["project_id"] for candidate in candidates]
        # COSINE scoreの絶対値はモデル・サービス実装で変動し得るため、固定値ではなく
        # Sample Data内の期待top-1だけを機械判定する。
        results.append(
            {
                "case_id": case["case_id"],
                "expected_top1_project_id": case["expected_top1_project_id"],
                "ranking": ranking,
                "scores": [str(candidate["distance"]) for candidate in candidates],
                "passed": bool(ranking) and ranking[0] == case["expected_top1_project_id"],
            }
        )
    return {
        "evaluation_scope": "POC_SAMPLE_DATA_REGRESSION_ONLY",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "region": region,
        "model_id": MODEL_ID,
        "dimensions": DIMENSIONS,
        "normalization_version": NORMALIZATION_VERSION,
        "seed_hash": _seed_hash(bundle),
        "table_name": repository.table_name,
        "index_name": repository.index_name,
        "case_count": len(results),
        "passed": all(item["passed"] for item in results),
        "results": results,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["evaluate"])
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--stack-name", default=DEFAULT_STACK_NAME)
    parser.add_argument("--table-name")
    parser.add_argument("--index-name")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    bundle = load_seed_bundle(args.source)
    cloudformation, dynamodb, bedrock = _aws_clients(args.region)
    table_name, index_name = resolve_resources(
        cloudformation,
        stack_name=args.stack_name,
        table_name=args.table_name,
        index_name=args.index_name,
    )
    report = evaluate(
        bundle,
        EstimationRepository(dynamodb, table_name=table_name, index_name=index_name),
        BedrockEmbeddingAdapter(bedrock),
        region=args.region,
    )
    # 評価証跡は呼出側が指定したファイルだけへ書き、正本Sample Dataを変更しない。
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"status": "PASSED" if report["passed"] else "FAILED", "output": str(args.output)}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
