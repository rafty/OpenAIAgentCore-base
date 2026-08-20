"""レビュー可能なSample Dataを検証し、計算用の値へ変換する。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .errors import ValidationError


DATA_FILES = {
    "project_summaries": ("projects/project-summaries.json", "project-summaries.schema.json"),
    "project_actuals": ("projects/project-actuals.json", "project-actuals.schema.json"),
    "effort_standards": ("masters/effort-standards.json", "effort-standards.schema.json"),
    "rate_cards": ("masters/rate-cards.json", "rate-cards.schema.json"),
    "pricing_policies": ("masters/pricing-policies.json", "pricing-policies.schema.json"),
    "search_quality_cases": ("evaluation/search-quality-cases.json", "search-quality-cases.schema.json"),
    "sample_project_delta": ("sample-inputs/sample-project-delta.json", "sample-project.schema.json"),
}

DECIMAL_FIELDS = {
    "estimated_person_days",
    "actual_person_days",
    "person_days",
    "person_days_per_unit",
    "risk_rate",
    "target_gross_margin_rate",
    "quantity",
}

# 正本JSONへ生成Vectorや認証情報が混入すると、レビュー対象と実行時生成値の境界が
# 崩れるため、SchemaのadditionalPropertiesだけに頼らず全階層を検査する。
FORBIDDEN_KEYS = {
    "embedding",
    "vector",
    "authorization",
    "access_key",
    "secret_key",
    "session_token",
    "password",
}


@dataclass(frozen=True)
class SeedBundle:
    """検証済みSample Data一式。数値文字列はDecimalへ変換済み。"""

    project_summaries: list[dict[str, Any]]
    project_actuals: list[dict[str, Any]]
    effort_standards: list[dict[str, Any]]
    rate_cards: list[dict[str, Any]]
    pricing_policies: list[dict[str, Any]]
    search_quality_cases: list[dict[str, Any]]
    sample_project_delta: dict[str, Any]


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"Sample Dataを読み込めません: {path}") from exc


def _validate_schema(data: Any, schema: dict[str, Any], source: Path) -> None:
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(data), key=lambda error: list(error.path))
    if not errors:
        return
    error = errors[0]
    location = "/".join(str(part) for part in error.absolute_path) or "<root>"
    raise ValidationError(f"Sample DataのSchema違反: {source}:{location}: {error.message}")


def _check_forbidden_keys(value: Any, *, path: str = "<root>") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = key.lower()
            if normalized in FORBIDDEN_KEYS or normalized.endswith("_arn"):
                raise ValidationError(f"Sample Dataの禁止属性です: {path}/{key}")
            _check_forbidden_keys(child, path=f"{path}/{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _check_forbidden_keys(child, path=f"{path}/{index}")


def _convert_decimals(value: Any, *, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {name: _convert_decimals(child, key=name) for name, child in value.items()}
    if isinstance(value, list):
        return [_convert_decimals(child, key=key) for child in value]
    if key in DECIMAL_FIELDS and isinstance(value, (str, int, Decimal)):
        try:
            converted = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValidationError(f"10進数へ変換できません: {key}") from exc
        if not converted.is_finite():
            raise ValidationError(f"有限の10進数ではありません: {key}")
        return converted
    return value


def _assert_unique(items: list[dict[str, Any]], key: str, label: str) -> set[str]:
    values = [str(item[key]) for item in items]
    if len(values) != len(set(values)):
        raise ValidationError(f"{label}の{key}が重複しています")
    return set(values)


def _validate_references(data: dict[str, Any]) -> None:
    summary_ids = _assert_unique(data["project_summaries"], "project_id", "案件サマリー")
    actual_ids = _assert_unique(data["project_actuals"], "project_id", "案件実績")
    if summary_ids != {"HIST-001", "HIST-002", "HIST-003"} or actual_ids != summary_ids:
        raise ValidationError("案件サマリーと正式実績のproject_idが一致しません")

    for key, unique_key in (
        ("effort_standards", "master_id"),
        ("rate_cards", "master_id"),
        ("pricing_policies", "policy_id"),
        ("search_quality_cases", "case_id"),
    ):
        _assert_unique(data[key], unique_key, key)

    expected_counts = {project_id: 0 for project_id in summary_ids}
    for case in data["search_quality_cases"]:
        expected = case["expected_top1_project_id"]
        if expected not in summary_ids:
            raise ValidationError(f"検索品質ケースが未知の案件を参照しています: {expected}")
        expected_counts[expected] += 1
    if any(count < 2 for count in expected_counts.values()):
        raise ValidationError("各過去案件を期待第1位とする検索品質ケースが2件以上必要です")

    delta = data["sample_project_delta"]["normalized_input"]
    if delta["save_intent"] != "EXPLICIT_SAVE" or delta["estimate_as_of"] != "2026-08-19":
        raise ValidationError("Sample Project Deltaの保存意思または基準日が仕様と一致しません")


def load_seed_bundle(source: str | Path) -> SeedBundle:
    """正本JSONをSchema・相互参照検証後に計算用の値へ変換する。"""

    root = Path(source)
    loaded: dict[str, Any] = {}
    for name, (relative_path, schema_name) in DATA_FILES.items():
        data_path = root / relative_path
        schema_path = root / "schemas" / schema_name
        data = _read_json(data_path)
        schema = _read_json(schema_path)
        _validate_schema(data, schema, data_path)
        _check_forbidden_keys(data)
        loaded[name] = data

    _validate_references(loaded)
    converted = {name: _convert_decimals(value) for name, value in loaded.items()}
    return SeedBundle(**converted)
