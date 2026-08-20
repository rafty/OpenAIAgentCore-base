"""AgentCore GatewayのLambda Targetから4 Toolを安全にルーティングする。"""

from __future__ import annotations

import json
import logging
import os
import secrets
from collections.abc import Mapping
from typing import Any

import boto3
from botocore.config import Config

from .contracts import TOOL_NAMES, make_result
from .embedding import BedrockEmbeddingAdapter
from .errors import EstimationError
from .repository import EstimationRepository
from .tools import EstimationToolService


LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)
TOOL_NAME_DELIMITER = "___"


def _tool_name(context: Any) -> str | None:
    custom = getattr(getattr(context, "client_context", None), "custom", None) or {}
    if not isinstance(custom, Mapping):
        return None
    full_name = custom.get("bedrockAgentCoreToolName")
    if not isinstance(full_name, str) or full_name.count(TOOL_NAME_DELIMITER) != 1:
        return None
    target, name = full_name.split(TOOL_NAME_DELIMITER)
    return name if target == os.environ.get("ESTIMATION_GATEWAY_TARGET_NAME", "EstimationTools") and name in TOOL_NAMES else None


def _default_service() -> EstimationToolService:
    region = os.environ.get("AWS_REGION", "us-east-1")
    # SDKのread timeoutをEmbeddingの1試行上限に合わせ、Lambda全体60秒内に
    # canonical errorを返す余白を残す。
    bedrock = boto3.client("bedrock-runtime", region_name=region, config=Config(connect_timeout=5, read_timeout=15, retries={"max_attempts": 1}))
    dynamodb = boto3.client("dynamodb", region_name=region, config=Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 1}))
    metrics = lambda metric: LOGGER.info(json.dumps(metric, separators=(",", ":")))
    return EstimationToolService(
        EstimationRepository(
            dynamodb,
            table_name=os.environ.get("ESTIMATION_TABLE_NAME", "OpenAiEstimationData"),
            index_name=os.environ.get("ESTIMATION_VECTOR_INDEX_NAME", "EstimationProjectVectorIndexV1"),
        ),
        BedrockEmbeddingAdapter(bedrock, metrics_sink=metrics),
    )


def lambda_handler(event: Any, context: Any, *, service: EstimationToolService | None = None) -> dict[str, Any]:
    correlation_id = getattr(context, "aws_request_id", None) or secrets.token_urlsafe(12)
    name = _tool_name(context)
    if name is None or not isinstance(event, Mapping):
        return make_result("VALIDATION_ERROR", {}, warnings=("Tool名または入力が不正です。",), correlation_id=correlation_id)
    implementation = service or _default_service()
    try:
        result = getattr(implementation, name)(event, correlation_id=correlation_id)
        LOGGER.info(json.dumps({"operation": name, "correlation_id": correlation_id, "status": result["status"]}, separators=(",", ":")))
        return result
    except EstimationError as exc:
        LOGGER.warning(json.dumps({"operation": name, "correlation_id": correlation_id, "status": exc.status}, separators=(",", ":")))
        return make_result(exc.status, {}, warnings=(str(exc),), correlation_id=correlation_id)
    except Exception:
        # 内部例外、入力本文、Vector、単価、見積金額をログへ反射しない。
        LOGGER.exception(json.dumps({"operation": name, "correlation_id": correlation_id, "status": "INTERNAL_ERROR"}, separators=(",", ":")))
        return make_result("INTERNAL_ERROR", {}, warnings=("Toolを実行できませんでした。",), correlation_id=correlation_id)
