"""Sample Project Deltaの決定的なDecimal見積計算を検証する。"""

from copy import deepcopy
from pathlib import Path

import pytest

from lambda_tools.estimation.calculation import calculate_estimate
from lambda_tools.estimation.errors import ValidationError
from lambda_tools.estimation.sample_data import load_seed_bundle


SOURCE = Path(__file__).resolve().parents[2] / "dynamodb-seed"


def _inputs():
    bundle = load_seed_bundle(SOURCE)
    return (
        bundle.sample_project_delta["normalized_input"],
        bundle.effort_standards,
        bundle.rate_cards,
        bundle.pricing_policies,
    )


def test_delta_expected_days_cost_price_and_warnings() -> None:
    result = calculate_estimate(*_inputs())
    assert str(result["total_person_days"]) == "15.7"
    assert {key: str(value) for key, value in result["role_person_days"].items()} == {
        "AWS_ARCHITECT": "5.0",
        "INFRA_ENGINEER": "10.7",
    }
    assert str(result["cost_jpy"]) == "1356000.0"
    assert str(result["proposed_price_jpy"]) == "1695000"
    assert any("Multi-AZ" in item for item in result["warnings"])
    assert any("自動補正" in item for item in result["warnings"])


def test_duplicate_missing_and_invalid_master_are_not_guessed() -> None:
    project, efforts, rates, policies = _inputs()
    with pytest.raises(ValidationError):
        calculate_estimate(project, [*efforts, deepcopy(efforts[0])], rates, policies)
    with pytest.raises(ValidationError):
        calculate_estimate(project, efforts, [item for item in rates if item["role"] != "INFRA_ENGINEER"], policies)
    with pytest.raises(ValidationError):
        calculate_estimate(project, efforts, rates, [])
    invalid = deepcopy(policies)
    invalid[0]["target_gross_margin_rate"] = "1.0"
    with pytest.raises(ValidationError):
        calculate_estimate(project, efforts, rates, invalid)
