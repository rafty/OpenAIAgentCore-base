"""Managed Knowledge Baseへ登録する文書とmetadataの正本契約。"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_ROOT = ROOT / "knowledge-base-s3"
EXPECTED_MARKDOWN = {
    "estimation/estimation_guideline.md",
    "projects/sample_project_alpha.md",
    "standards/aws_architecture_standard.md",
    "standards/monitoring_standard.md",
    "standards/security_standard.md",
}
EXPECTED_FILES = EXPECTED_MARKDOWN | {
    f"{path}.metadata.json" for path in EXPECTED_MARKDOWN
}
EXPECTED_DOCUMENT_TYPES = {
    "estimation/estimation_guideline.md": "estimation",
    "projects/sample_project_alpha.md": "past_project",
    "standards/aws_architecture_standard.md": "architecture",
    "standards/monitoring_standard.md": "monitoring",
    "standards/security_standard.md": "security",
}
_SECRET_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)(?:password|secret[_-]?key|access[_-]?key)\s*[:=]\s*['\"][^'\"]+"),
)


def _metadata(document_path: str) -> dict[str, Any]:
    return json.loads(
        (KNOWLEDGE_ROOT / f"{document_path}.metadata.json").read_text(
            encoding="utf-8"
        )
    )


def test_registered_files_are_exactly_five_markdown_and_five_metadata() -> None:
    actual = {
        path.relative_to(KNOWLEDGE_ROOT).as_posix()
        for path in KNOWLEDGE_ROOT.rglob("*")
        if path.is_file()
    }

    assert actual == EXPECTED_FILES
    assert len(actual) == 10
    assert {path for path in actual if path.endswith(".md")} == EXPECTED_MARKDOWN
    assert all((KNOWLEDGE_ROOT / path).read_text(encoding="utf-8") for path in actual)


def test_metadata_shape_types_and_document_pairing() -> None:
    allowed_document_types = {
        "architecture",
        "security",
        "monitoring",
        "estimation",
        "past_project",
    }
    required_fields = {
        "document_type",
        "version",
        "system_type",
        "environment",
        "service",
    }

    for document_path in EXPECTED_MARKDOWN:
        decoded = _metadata(document_path)
        assert set(decoded) == {"metadataAttributes"}
        attributes = decoded["metadataAttributes"]
        assert isinstance(attributes, dict)
        assert required_fields.issubset(attributes)
        assert attributes["document_type"] in allowed_document_types
        assert attributes["document_type"] == EXPECTED_DOCUMENT_TYPES[document_path]
        assert isinstance(attributes["version"], str) and attributes["version"]
        assert attributes["system_type"] == "aws"
        for field in ("environment", "service"):
            assert isinstance(attributes[field], list) and attributes[field]
            assert all(isinstance(item, str) and item for item in attributes[field])
        if document_path == "projects/sample_project_alpha.md":
            assert attributes["project_name"] == "sample_project_alpha"
        else:
            assert "project_name" not in attributes


def test_documents_contain_acceptance_specific_values() -> None:
    architecture = (
        KNOWLEDGE_ROOT / "standards/aws_architecture_standard.md"
    ).read_text(encoding="utf-8")
    monitoring = (KNOWLEDGE_ROOT / "standards/monitoring_standard.md").read_text(
        encoding="utf-8"
    )
    estimation = (
        KNOWLEDGE_ROOT / "estimation/estimation_guideline.md"
    ).read_text(encoding="utf-8")
    project = (KNOWLEDGE_ROOT / "projects/sample_project_alpha.md").read_text(
        encoding="utf-8"
    )

    assert "バックアップ保持期間は14日間" in architecture
    assert "本番環境のログ保持期間は90日" in monitoring
    assert "1サーバーあたり 0.5人日" in estimation
    assert "合計: 26.0人日" in project


def test_registered_files_do_not_contain_secret_material() -> None:
    for relative_path in EXPECTED_FILES:
        text = (KNOWLEDGE_ROOT / relative_path).read_text(encoding="utf-8")
        assert all(pattern.search(text) is None for pattern in _SECRET_PATTERNS)
