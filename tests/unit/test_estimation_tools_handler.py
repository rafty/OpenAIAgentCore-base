"""Estimation 4 ToolとLambdaハンドラーの公開契約を検証する。"""

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from lambda_tools.estimation.contracts import (
    make_result,
    validate_create_arguments,
    validate_search_arguments,
)
from lambda_tools.estimation.errors import ValidationError
from lambda_tools.estimation.handler import lambda_handler
from lambda_tools.estimation.tools import EstimationToolService


TOOLS = Path(__file__).resolve().parents[2] / "lambda_tools/estimation/tools.json"


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def __getattr__(self, name: str):
        def execute(arguments, *, correlation_id):
            self.calls.append((name, arguments))
            return make_result("OK", {"tool": name}, correlation_id=correlation_id)

        return execute


def _context(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        aws_request_id="request-1",
        client_context=SimpleNamespace(
            custom={"bedrockAgentCoreToolName": f"EstimationTools___{name}"}
        ),
    )


def test_only_four_business_tools_are_published_and_routed() -> None:
    schemas = json.loads(TOOLS.read_text(encoding="utf-8"))
    names = [item["name"] for item in schemas]
    assert names == [
        "search_similar_projects",
        "get_estimation_reference_data",
        "create_estimate_draft",
        "get_estimate_draft",
    ]
    assert not any(name.lower().startswith(("put", "update", "scan", "delete")) for name in names)
    service = FakeService()
    for name in names:
        result = lambda_handler({"value": name}, _context(name), service=service)
        assert set(result) == {"status", "data", "warnings", "correlation_id"}
        assert result["status"] == "OK"
    assert [name for name, _ in service.calls] == names


def test_unknown_tool_and_invalid_create_input_are_canonical_errors() -> None:
    result = lambda_handler({}, _context("put_item"), service=FakeService())
    assert result["status"] == "VALIDATION_ERROR"
    with pytest.raises(ValidationError):
        validate_create_arguments({"operation": "DELETE"})


def test_unknown_fields_and_invalid_dates_are_rejected_at_lambda_boundary() -> None:
    with pytest.raises(ValidationError, match="未知"):
        validate_search_arguments(
            {
                "query": "sample",
                "filters": {"arbitrary": "x"},
                "_actor_id": "actor",
                "_session_id": "session",
            }
        )
    with pytest.raises(ValidationError, match="未知"):
        validate_search_arguments(
            {
                "query": "sample",
                "filters": {},
                "unexpected": True,
                "_actor_id": "actor",
                "_session_id": "session",
            }
        )
    with pytest.raises(ValidationError, match="YYYY-MM-DD"):
        validate_create_arguments(
            {
                "operation": "PREVIEW",
                "project": {
                    "project_name": "Delta",
                    "project_type": "NEW_BUILD",
                    "architecture_summary": "EC2 and RDS",
                    "environments": ["prod"],
                    "components": [],
                    "work_scope": [],
                    "assumptions": [],
                    "exclusions": [],
                    "estimate_as_of": "2026/08/20",
                },
                "search_context_id": "context",
                "result_refs": [],
                "_actor_id": "actor",
                "_session_id": "session",
            }
        )


def test_result_size_and_forbidden_attributes_are_rejected() -> None:
    with pytest.raises(ValidationError):
        make_result("OK", {"embedding": [0.0]}, correlation_id="request")
    with pytest.raises(ValidationError):
        make_result("OK", {"text": "x" * (65 * 1024)}, correlation_id="request")


def test_dynamodb_version_is_normalized_to_public_integer() -> None:
    assert EstimationToolService._public_draft(
        {"version": Decimal("1"), "cost_jpy": Decimal("1356000.0")}
    ) == {"version": 1, "cost_jpy": Decimal("1356000.0")}
    assert EstimationToolService._public_master(
        {"version": Decimal("2"), "daily_rate_jpy": Decimal("100000")}
    ) == {"version": 2, "daily_rate_jpy": Decimal("100000")}
    with pytest.raises(ValidationError, match="version"):
        EstimationToolService._integer_version(Decimal("1.5"))


def test_oversized_save_result_is_rejected_before_write(monkeypatch: pytest.MonkeyPatch) -> None:
    saved = False

    monkeypatch.setattr(
        "lambda_tools.estimation.tools.resolve_search_context",
        lambda *_args, **_kwargs: ({"references": {}}, []),
    )
    monkeypatch.setattr(
        EstimationToolService,
        "_load_reference_data",
        lambda *_args, **_kwargs: {
            "effort_standards": [],
            "rate_cards": [],
            "pricing_policies": [],
        },
    )
    monkeypatch.setattr(
        "lambda_tools.estimation.tools.calculate_estimate",
        lambda *_args, **_kwargs: {"warnings": []},
    )

    def capture_save(*_args, **_kwargs):
        nonlocal saved
        saved = True
        return {}

    monkeypatch.setattr("lambda_tools.estimation.tools.save_draft", capture_save)
    service = EstimationToolService(object(), object())  # type: ignore[arg-type]
    components = [
        {
            "service": "EC2",
            "environment": "ALL",
            "quantity": 1,
            "unit": "INSTANCE",
            "conditions": ["x" * 100] * 20,
        }
        for _ in range(50)
    ]
    with pytest.raises(ValidationError, match="64 KiB"):
        service.create_estimate_draft(
            {
                "operation": "SAVE",
                "project": {
                    "project_name": "Delta",
                    "project_type": "NEW_BUILD",
                    "architecture_summary": "EC2",
                    "environments": ["PRODUCTION"],
                    "components": components,
                    "work_scope": ["BUILD"],
                    "assumptions": [],
                    "exclusions": [],
                    "estimate_as_of": "2026-08-20",
                },
                "search_context_id": "context",
                "result_refs": [],
                "_actor_id": "actor",
                "_session_id": "session",
                "_idempotency_key": "key",
                "_request_hash": "hash",
            },
            correlation_id="request",
        )
    assert saved is False


def test_service_exception_does_not_leak_private_message() -> None:
    class BrokenService:
        def search_similar_projects(self, *_args, **_kwargs):
            raise RuntimeError("PRIVATE-VECTOR-PRICE")

    result = lambda_handler(
        {"query": "x"},
        _context("search_similar_projects"),
        service=BrokenService(),  # type: ignore[arg-type]
    )
    assert result["status"] == "INTERNAL_ERROR"
    assert "PRIVATE" not in json.dumps(result, ensure_ascii=False)
