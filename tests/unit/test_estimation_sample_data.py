"""Estimation Sample Dataの正本契約を検証する。"""

import json
import shutil
from pathlib import Path

import pytest

from lambda_tools.estimation.errors import ValidationError
from lambda_tools.estimation.sample_data import load_seed_bundle


SOURCE = Path(__file__).resolve().parents[2] / "dynamodb-seed"


def test_sample_data_is_complete_and_cross_referenced() -> None:
    bundle = load_seed_bundle(SOURCE)
    assert [item["project_id"] for item in bundle.project_summaries] == [
        "HIST-001",
        "HIST-002",
        "HIST-003",
    ]
    assert len(bundle.search_quality_cases) == 6
    assert {item["expected_top1_project_id"] for item in bundle.search_quality_cases} == {
        "HIST-001",
        "HIST-002",
        "HIST-003",
    }
    delta = bundle.sample_project_delta["normalized_input"]
    assert delta["project_name"] == "Sample Project Delta"
    assert delta["save_intent"] == "EXPLICIT_SAVE"
    assert all("embedding" not in item for item in bundle.project_summaries)


@pytest.mark.parametrize(
    ("relative", "mutation"),
    [
        ("projects/project-summaries.json", lambda data: data[0].pop("search_summary")),
        ("projects/project-summaries.json", lambda data: data.append(dict(data[0]))),
        (
            "evaluation/search-quality-cases.json",
            lambda data: data[0].update(expected_top1_project_id="HIST-999"),
        ),
        ("projects/project-summaries.json", lambda data: data[0].update(embedding=[0.1])),
    ],
)
def test_invalid_sample_data_is_rejected(
    tmp_path: Path,
    relative: str,
    mutation: object,
) -> None:
    copied = tmp_path / "seed"
    shutil.copytree(SOURCE, copied)
    target = copied / relative
    data = json.loads(target.read_text(encoding="utf-8"))
    mutation(data)  # type: ignore[operator]
    target.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_seed_bundle(copied)
