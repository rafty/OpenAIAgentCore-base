"""Estimation GatewayとLambdaの公開契約・入力上限を一箇所で管理する。"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, is_dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Mapping, Sequence

from .errors import ValidationError


TOOL_NAMES = (
    "search_similar_projects",
    "get_estimation_reference_data",
    "create_estimate_draft",
    "get_estimate_draft",
)
STATUSES = {
    "OK",
    "NO_RESULTS",
    "VALIDATION_ERROR",
    "CONTEXT_INVALID",
    "CONTEXT_EXPIRED",
    "NOT_FOUND",
    "DEPENDENCY_UNAVAILABLE",
    "SAVE_FAILED",
    "INTERNAL_ERROR",
}
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
FORBIDDEN_RESULT_KEYS = {"PK", "SK", "embedding", "SearchVector", "vector"}
MAX_RESULT_BYTES = 64 * 1024


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError(f"{label}はobjectで指定してください")
    return value


def reject_unknown_fields(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    """公開DTOを拡張可能な任意objectにせず、定義外入力をfail-closedにする。"""

    unknown = set(value) - allowed
    if unknown:
        raise ValidationError(f"{label}に未知のフィールドがあります")


def require_string(
    value: Any,
    label: str,
    *,
    maximum: int,
    pattern: re.Pattern[str] | None = None,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label}は空でない文字列で指定してください")
    result = value.strip()
    if len(result) > maximum:
        raise ValidationError(f"{label}は{maximum}文字以下で指定してください")
    if pattern is not None and pattern.fullmatch(result) is None:
        raise ValidationError(f"{label}の形式が不正です")
    return result


def require_string_list(
    value: Any,
    label: str,
    *,
    maximum_items: int,
    maximum_length: int,
) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValidationError(f"{label}は配列で指定してください")
    if len(value) > maximum_items:
        raise ValidationError(f"{label}は{maximum_items}件以下で指定してください")
    return [
        require_string(item, f"{label}[{index}]", maximum=maximum_length)
        for index, item in enumerate(value)
    ]


def require_decimal(value: Any, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValidationError(f"{label}は10進数で指定してください") from exc
    if not result.is_finite() or result < 0 or result > Decimal("10000"):
        raise ValidationError(f"{label}は0以上10000以下の有限値で指定してください")
    return result


def require_date(value: Any, label: str) -> str:
    result = require_string(value, label, maximum=10)
    try:
        parsed = date.fromisoformat(result)
    except ValueError as exc:
        raise ValidationError(f"{label}はYYYY-MM-DD形式で指定してください") from exc
    if parsed.isoformat() != result:
        raise ValidationError(f"{label}はYYYY-MM-DD形式で指定してください")
    return result


def require_internal_context(arguments: Mapping[str, Any]) -> tuple[str, str]:
    # actor/sessionはモデルが指定する公開値ではなく、Runtimeで検証済みの値を
    # MCPアダプターが予約引数へ上書きしたものだけを受理する。
    actor_id = require_string(arguments.get("_actor_id"), "_actor_id", maximum=128, pattern=ID_PATTERN)
    session_id = require_string(arguments.get("_session_id"), "_session_id", maximum=128, pattern=ID_PATTERN)
    return actor_id, session_id


def validate_search_arguments(arguments: Any) -> dict[str, Any]:
    value = _require_mapping(arguments, "arguments")
    reject_unknown_fields(value, {"query", "filters", "_actor_id", "_session_id"}, "arguments")
    actor_id, session_id = require_internal_context(value)
    filters = value.get("filters", {})
    filters = _require_mapping(filters, "filters")
    allowed_filters = {"project_type", "architecture_family", "outcome_quality"}
    reject_unknown_fields(filters, allowed_filters, "filters")
    return {
        "query": require_string(value.get("query"), "query", maximum=2000),
        "filters": {
            key: require_string(item, f"filters.{key}", maximum=100)
            for key, item in filters.items()
        },
        "actor_id": actor_id,
        "session_id": session_id,
    }


def validate_reference_arguments(arguments: Any) -> dict[str, Any]:
    value = _require_mapping(arguments, "arguments")
    reject_unknown_fields(
        value,
        {
            "search_context_id",
            "result_refs",
            "project_type",
            "services",
            "task_types",
            "roles",
            "estimate_as_of",
            "_actor_id",
            "_session_id",
        },
        "arguments",
    )
    actor_id, session_id = require_internal_context(value)
    refs = [
        require_string(ref, f"result_refs[{index}]", maximum=128, pattern=ID_PATTERN)
        for index, ref in enumerate(
            require_string_list(value.get("result_refs", []), "result_refs", maximum_items=3, maximum_length=128)
        )
    ]
    services = require_string_list(value.get("services", []), "services", maximum_items=20, maximum_length=50)
    task_types = require_string_list(value.get("task_types", []), "task_types", maximum_items=20, maximum_length=50)
    roles = require_string_list(value.get("roles", []), "roles", maximum_items=20, maximum_length=50)
    return {
        "search_context_id": require_string(value.get("search_context_id"), "search_context_id", maximum=128, pattern=ID_PATTERN),
        "result_refs": refs,
        "project_type": require_string(value.get("project_type"), "project_type", maximum=50),
        "services": services,
        "task_types": task_types,
        "roles": roles,
        "estimate_as_of": require_date(value.get("estimate_as_of"), "estimate_as_of"),
        "actor_id": actor_id,
        "session_id": session_id,
    }


def validate_project_input(value: Any) -> dict[str, Any]:
    project = _require_mapping(value, "project")
    reject_unknown_fields(
        project,
        {
            "project_name",
            "project_type",
            "architecture_summary",
            "environments",
            "components",
            "work_scope",
            "assumptions",
            "exclusions",
            "estimate_as_of",
        },
        "project",
    )
    components = project.get("components", [])
    if not isinstance(components, list) or len(components) > 50:
        raise ValidationError("componentsは50件以下の配列で指定してください")
    normalized_components = []
    for index, component_value in enumerate(components):
        component = _require_mapping(component_value, f"components[{index}]")
        reject_unknown_fields(
            component,
            {"service", "environment", "quantity", "unit", "conditions"},
            f"components[{index}]",
        )
        normalized_components.append(
            {
                "service": require_string(component.get("service"), f"components[{index}].service", maximum=50),
                "environment": require_string(component.get("environment", "ALL"), f"components[{index}].environment", maximum=50),
                "quantity": require_decimal(component.get("quantity"), f"components[{index}].quantity"),
                "unit": require_string(component.get("unit"), f"components[{index}].unit", maximum=50),
                "conditions": require_string_list(component.get("conditions", []), f"components[{index}].conditions", maximum_items=20, maximum_length=100),
            }
        )
    return {
        "project_name": require_string(project.get("project_name"), "project_name", maximum=200),
        "project_type": require_string(project.get("project_type"), "project_type", maximum=50),
        "architecture_summary": require_string(project.get("architecture_summary"), "architecture_summary", maximum=2000),
        "environments": require_string_list(project.get("environments", []), "environments", maximum_items=20, maximum_length=100),
        "components": normalized_components,
        "work_scope": require_string_list(project.get("work_scope", []), "work_scope", maximum_items=20, maximum_length=100),
        "assumptions": require_string_list(project.get("assumptions", []), "assumptions", maximum_items=20, maximum_length=500),
        "exclusions": require_string_list(project.get("exclusions", []), "exclusions", maximum_items=20, maximum_length=500),
        "estimate_as_of": require_date(project.get("estimate_as_of"), "estimate_as_of"),
    }


def validate_create_arguments(arguments: Any) -> dict[str, Any]:
    value = _require_mapping(arguments, "arguments")
    reject_unknown_fields(
        value,
        {
            "operation",
            "project",
            "search_context_id",
            "result_refs",
            "_actor_id",
            "_session_id",
            "_idempotency_key",
            "_request_hash",
        },
        "arguments",
    )
    actor_id, session_id = require_internal_context(value)
    operation = require_string(value.get("operation"), "operation", maximum=10)
    if operation not in {"PREVIEW", "SAVE"}:
        raise ValidationError("operationはPREVIEWまたはSAVEで指定してください")
    result = {
        "operation": operation,
        "project": validate_project_input(value.get("project")),
        "search_context_id": require_string(value.get("search_context_id"), "search_context_id", maximum=128, pattern=ID_PATTERN),
        "result_refs": [
            require_string(ref, f"result_refs[{index}]", maximum=128, pattern=ID_PATTERN)
            for index, ref in enumerate(
                require_string_list(value.get("result_refs", []), "result_refs", maximum_items=3, maximum_length=128)
            )
        ],
        "actor_id": actor_id,
        "session_id": session_id,
    }
    if operation == "SAVE":
        result["idempotency_key"] = require_string(value.get("_idempotency_key"), "_idempotency_key", maximum=128, pattern=ID_PATTERN)
        result["request_hash"] = require_string(value.get("_request_hash"), "_request_hash", maximum=128, pattern=ID_PATTERN)
    return result


def validate_get_arguments(arguments: Any) -> dict[str, Any]:
    value = _require_mapping(arguments, "arguments")
    reject_unknown_fields(
        value,
        {"project_id", "estimate_id", "version", "_actor_id", "_session_id"},
        "arguments",
    )
    actor_id, session_id = require_internal_context(value)
    version = value.get("version")
    if not isinstance(version, int) or version < 1:
        raise ValidationError("versionは1以上の整数で指定してください")
    return {
        "project_id": require_string(value.get("project_id"), "project_id", maximum=200, pattern=UUID_PATTERN),
        "estimate_id": require_string(value.get("estimate_id"), "estimate_id", maximum=200, pattern=UUID_PATTERN),
        "version": version,
        "actor_id": actor_id,
        "session_id": session_id,
    }


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Mapping):
        return {str(key): _json_safe(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(child) for child in value]
    return value


def _reject_forbidden_result(value: Any, path: str = "data") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key) in FORBIDDEN_RESULT_KEYS:
                raise ValidationError(f"Tool結果の禁止属性です: {path}.{key}")
            _reject_forbidden_result(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_result(child, f"{path}[{index}]")


def make_result(
    status: str,
    data: Any,
    *,
    warnings: Sequence[str] = (),
    correlation_id: str,
) -> dict[str, Any]:
    if status not in STATUSES:
        raise ValidationError("未定義のcanonical statusです")
    safe_data = _json_safe(data)
    _reject_forbidden_result(safe_data)
    result = {
        "status": status,
        "data": safe_data,
        "warnings": require_string_list(list(warnings), "warnings", maximum_items=20, maximum_length=500),
        "correlation_id": require_string(correlation_id, "correlation_id", maximum=128, pattern=ID_PATTERN),
    }
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_RESULT_BYTES:
        raise ValidationError("Tool結果が64 KiBを超えています")
    return result
