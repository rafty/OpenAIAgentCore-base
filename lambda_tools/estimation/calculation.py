"""LLMから独立したDecimalベースの見積計算。"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable

from .errors import ValidationError


def _active(items: Iterable[dict[str, Any]], as_of: date, label: str) -> list[dict[str, Any]]:
    result = [
        item
        for item in items
        if item.get("approval_status") == "APPROVED"
        and date.fromisoformat(str(item["valid_from"])) <= as_of <= date.fromisoformat(str(item["valid_to"]))
    ]
    if not result:
        raise ValidationError(f"有効な承認済み{label}がありません")
    return result


def _quantity(project: dict[str, Any], service: str, unit: str) -> Decimal:
    components = [component for component in project["components"] if component["service"] == service]
    if unit == "SERVICE":
        return Decimal("1") if components else Decimal("0")
    expected_unit = {"INSTANCE": "INSTANCE", "DATABASE": "DATABASE", "ALARM": "ALARM"}[unit]
    return sum(
        (Decimal(str(component["quantity"])) for component in components if component["unit"] == expected_unit),
        Decimal("0"),
    )


def calculate_estimate(
    project: dict[str, Any],
    effort_standards: list[dict[str, Any]],
    rate_cards: list[dict[str, Any]],
    pricing_policies: list[dict[str, Any]],
) -> dict[str, Any]:
    as_of = date.fromisoformat(project["estimate_as_of"])
    efforts = _active(effort_standards, as_of, "標準工数")
    rates = _active(rate_cards, as_of, "単価")
    policies = _active(pricing_policies, as_of, "価格ポリシー")
    if len(policies) != 1:
        raise ValidationError("有効な価格ポリシーが一意ではありません")

    # サービスと作業ごとに複数の承認済みマスターを推測選択しない。
    effort_keys = [(item["service"], item["task_type"]) for item in efforts]
    if len(effort_keys) != len(set(effort_keys)):
        raise ValidationError("有効な標準工数マスターが重複しています")
    rate_by_role: dict[str, dict[str, Any]] = {}
    for rate in rates:
        role = rate["role"]
        if role in rate_by_role:
            raise ValidationError("有効な役割別単価が重複しています")
        rate_by_role[role] = rate

    lines: list[dict[str, Any]] = []
    role_days: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for standard in efforts:
        service = standard["service"]
        task_type = standard["task_type"]
        if service not in {component["service"] for component in project["components"]}:
            continue
        if service != "CLOUDWATCH" and task_type not in project["work_scope"]:
            continue
        quantity = _quantity(project, service, standard["unit"])
        if quantity == 0:
            continue
        person_days = Decimal(str(standard["person_days_per_unit"])) * quantity
        role_days[standard["role"]] += person_days
        lines.append(
            {
                "master_id": standard["master_id"],
                "master_version": standard["version"],
                "service": service,
                "task_type": task_type,
                "unit": standard["unit"],
                "quantity": quantity,
                "person_days_per_unit": Decimal(str(standard["person_days_per_unit"])),
                "person_days": person_days,
                "role": standard["role"],
            }
        )
    if not lines:
        raise ValidationError("計算対象となる標準工数がありません")

    role_costs: dict[str, Decimal] = {}
    for role, person_days in role_days.items():
        if role not in rate_by_role:
            raise ValidationError(f"役割別単価がありません: {role}")
        role_costs[role] = person_days * Decimal(str(rate_by_role[role]["daily_rate_jpy"]))
    total_days = sum(role_days.values(), Decimal("0"))
    cost = sum(role_costs.values(), Decimal("0"))
    policy = policies[0]
    risk_adjusted_cost = cost * (Decimal("1") + Decimal(str(policy["risk_rate"])))
    margin = Decimal(str(policy["target_gross_margin_rate"]))
    if margin < 0 or margin >= 1:
        raise ValidationError("目標粗利率は0以上1未満で指定してください")
    raw_price = risk_adjusted_cost / (Decimal("1") - margin)
    unit = Decimal(str(policy["rounding_unit_jpy"]))
    # 途中で丸めると役割別金額と合計がずれるため、粗利率適用後の最終価格だけを
    # HALF_UPで指定単位へ丸める。
    proposed_price = (raw_price / unit).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * unit
    warnings = ["類似案件の実績工数は今回見積の自動補正に使用していません。"]
    if any("MULTI_AZ" in component.get("conditions", []) for component in project["components"]):
        warnings.append("Multi-AZの追加工数はサンプル標準工数に未定義のため未反映です。")
    warnings.append("過去案件と今回見積の対象範囲が同一とは限りません。")
    return {
        "lines": lines,
        "total_person_days": total_days,
        "role_person_days": dict(role_days),
        "role_costs_jpy": role_costs,
        "cost_jpy": cost,
        "risk_adjusted_cost_jpy": risk_adjusted_cost,
        "proposed_price_jpy": proposed_price,
        "currency": "JPY",
        "pricing_policy": {"policy_id": policy["policy_id"], "version": policy["version"]},
        "rate_versions": {role: rate_by_role[role]["version"] for role in role_days},
        "warnings": warnings,
    }
