"""Verify TaskCompleted's `payload.result` discrimination (ADR-0015 Section 1).

`task_completed.schema.json` validates `payload.result`'s internal shape via
an `allOf`/`if`/`then` pair keyed on `payload.capability`: `text.word-count`
requires `{"word_count": integer}`, `text.summarize` requires
`{"summary": string}`, `code.review` requires `{"findings": [...]}`
(ADR-0018), and each capability's result must not accidentally validate
against another's branch (ADR-0015 Testing Strategy).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, ValidationError

CONTRACTS_ROOT = Path(__file__).resolve().parents[2] / "contracts"
JSON_SCHEMA_DIR = CONTRACTS_ROOT / "json-schema" / "v1"
EXAMPLES_DIR = CONTRACTS_ROOT / "examples" / "v1"

TASK_COMPLETED_SCHEMA = json.loads(
    (JSON_SCHEMA_DIR / "task_completed.schema.json").read_text(encoding="utf-8")
)
BASE_EXAMPLE: dict[str, Any] = json.loads(
    (EXAMPLES_DIR / "task_completed.example.json").read_text(encoding="utf-8")
)


def _validator() -> Draft202012Validator:
    return Draft202012Validator(TASK_COMPLETED_SCHEMA)


def _message(*, capability: str, result: dict[str, object]) -> dict[str, Any]:
    message = copy.deepcopy(BASE_EXAMPLE)
    message["payload"]["capability"] = capability
    message["payload"]["result"] = result
    return message


def test_word_count_result_validates_against_word_count_branch() -> None:
    message = _message(capability="text.word-count", result={"word_count": 9})
    _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_summarize_result_validates_against_summarize_branch() -> None:
    message = _message(capability="text.summarize", result={"summary": "a short summary"})
    _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_word_count_capability_missing_word_count_is_rejected() -> None:
    message = _message(capability="text.word-count", result={"summary": "not a word count"})
    with pytest.raises(ValidationError):
        _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_summarize_capability_missing_summary_is_rejected() -> None:
    message = _message(capability="text.summarize", result={"word_count": 9})
    with pytest.raises(ValidationError):
        _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_word_count_result_does_not_accept_the_other_capabilitys_extra_field() -> None:
    message = _message(capability="text.word-count", result={"word_count": 9, "summary": "extra"})
    with pytest.raises(ValidationError):
        _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_summarize_result_does_not_accept_the_other_capabilitys_extra_field() -> None:
    message = _message(capability="text.summarize", result={"summary": "ok", "word_count": 9})
    with pytest.raises(ValidationError):
        _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_unrecognized_capability_is_rejected() -> None:
    message = _message(capability="text.unknown", result={"word_count": 9})
    with pytest.raises(ValidationError):
        _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_code_review_result_validates_against_the_findings_branch() -> None:
    message = _message(
        capability="code.review",
        result={
            "findings": [
                {"file": "a.py", "line": 3, "summary": "Missing null check.", "severity": "medium"},
                {"file": "b.py", "line": None, "summary": "No tests for this.", "severity": "low"},
            ]
        },
    )
    _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_code_review_capability_missing_findings_is_rejected() -> None:
    message = _message(capability="code.review", result={"summary": "not a findings list"})
    with pytest.raises(ValidationError):
        _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_code_review_finding_with_an_invalid_severity_is_rejected() -> None:
    message = _message(
        capability="code.review",
        result={"findings": [{"file": "a.py", "line": 1, "summary": "x", "severity": "critical"}]},
    )
    with pytest.raises(ValidationError):
        _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_code_review_finding_with_an_extra_field_is_rejected() -> None:
    message = _message(
        capability="code.review",
        result={
            "findings": [
                {
                    "file": "a.py",
                    "line": 1,
                    "summary": "x",
                    "severity": "low",
                    "confidence": 0.9,
                }
            ]
        },
    )
    with pytest.raises(ValidationError):
        _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_code_review_result_does_not_accept_the_summarize_capabilitys_field() -> None:
    message = _message(capability="code.review", result={"findings": [], "summary": "extra"})
    with pytest.raises(ValidationError):
        _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_ui_review_result_validates_against_the_findings_branch() -> None:
    message = _message(
        capability="ui.review",
        result={
            "findings": [
                {"area": "header navigation", "summary": "Missing alt text.", "severity": "low"},
                {"area": "console", "summary": "Uncaught TypeError.", "severity": "high"},
            ]
        },
    )
    _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_ui_review_capability_missing_findings_is_rejected() -> None:
    message = _message(capability="ui.review", result={"summary": "not a findings list"})
    with pytest.raises(ValidationError):
        _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_ui_review_finding_with_a_code_review_file_line_key_is_rejected() -> None:
    """`ui.review`'s findings shape has no `file`/`line` concept -- it must
    not accidentally validate against `code.review`'s branch."""
    message = _message(
        capability="ui.review",
        result={
            "findings": [
                {"file": "a.py", "line": 1, "summary": "x", "severity": "low"},
            ]
        },
    )
    with pytest.raises(ValidationError):
        _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_ui_review_finding_with_an_invalid_severity_is_rejected() -> None:
    message = _message(
        capability="ui.review",
        result={"findings": [{"area": "console", "summary": "x", "severity": "critical"}]},
    )
    with pytest.raises(ValidationError):
        _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_ui_review_finding_with_an_extra_field_is_rejected() -> None:
    message = _message(
        capability="ui.review",
        result={
            "findings": [
                {"area": "console", "summary": "x", "severity": "low", "confidence": 0.9},
            ]
        },
    )
    with pytest.raises(ValidationError):
        _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_ui_review_result_does_not_accept_the_summarize_capabilitys_field() -> None:
    message = _message(capability="ui.review", result={"findings": [], "summary": "extra"})
    with pytest.raises(ValidationError):
        _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_architecture_review_result_validates_against_the_findings_branch() -> None:
    message = _message(
        capability="architecture.review",
        result={
            "findings": [
                {
                    "section": "Decision 2",
                    "summary": "Missing rollback plan.",
                    "severity": "medium",
                },
                {"section": "Security", "summary": "No threat model provided.", "severity": "high"},
            ]
        },
    )
    _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_architecture_review_capability_missing_findings_is_rejected() -> None:
    message = _message(capability="architecture.review", result={"summary": "not a findings list"})
    with pytest.raises(ValidationError):
        _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_architecture_review_finding_with_a_ui_review_area_key_is_rejected() -> None:
    """`architecture.review`'s findings shape has no `area` concept -- it
    must not accidentally validate against `ui.review`'s branch."""
    message = _message(
        capability="architecture.review",
        result={"findings": [{"area": "console", "summary": "x", "severity": "low"}]},
    )
    with pytest.raises(ValidationError):
        _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_architecture_review_finding_with_an_invalid_severity_is_rejected() -> None:
    message = _message(
        capability="architecture.review",
        result={"findings": [{"section": "Decision 2", "summary": "x", "severity": "critical"}]},
    )
    with pytest.raises(ValidationError):
        _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_architecture_review_finding_with_an_extra_field_is_rejected() -> None:
    message = _message(
        capability="architecture.review",
        result={
            "findings": [
                {"section": "Decision 2", "summary": "x", "severity": "low", "confidence": 0.9}
            ]
        },
    )
    with pytest.raises(ValidationError):
        _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_architecture_review_result_does_not_accept_the_summarize_capabilitys_field() -> None:
    message = _message(
        capability="architecture.review", result={"findings": [], "summary": "extra"}
    )
    with pytest.raises(ValidationError):
        _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_data_analysis_result_validates_against_the_findings_branch() -> None:
    message = _message(
        capability="data.analysis",
        result={
            "findings": [
                {
                    "metric": "p95 latency",
                    "summary": "p95 latency doubled week-over-week.",
                    "severity": "medium",
                },
                {"metric": "AI provider cost", "summary": "Cost spiked 3x.", "severity": "high"},
            ]
        },
    )
    _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_data_analysis_capability_missing_findings_is_rejected() -> None:
    message = _message(capability="data.analysis", result={"summary": "not a findings list"})
    with pytest.raises(ValidationError):
        _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_data_analysis_finding_with_an_architecture_review_section_key_is_rejected() -> None:
    """`data.analysis`'s findings shape has no `section` concept -- it must
    not accidentally validate against `architecture.review`'s branch."""
    message = _message(
        capability="data.analysis",
        result={"findings": [{"section": "Decision 2", "summary": "x", "severity": "low"}]},
    )
    with pytest.raises(ValidationError):
        _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_data_analysis_finding_with_an_invalid_severity_is_rejected() -> None:
    message = _message(
        capability="data.analysis",
        result={"findings": [{"metric": "p95 latency", "summary": "x", "severity": "critical"}]},
    )
    with pytest.raises(ValidationError):
        _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_data_analysis_finding_with_an_extra_field_is_rejected() -> None:
    message = _message(
        capability="data.analysis",
        result={
            "findings": [
                {"metric": "p95 latency", "summary": "x", "severity": "low", "confidence": 0.9}
            ]
        },
    )
    with pytest.raises(ValidationError):
        _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]


def test_data_analysis_result_does_not_accept_the_summarize_capabilitys_field() -> None:
    message = _message(capability="data.analysis", result={"findings": [], "summary": "extra"})
    with pytest.raises(ValidationError):
        _validator().validate(message)  # pyright: ignore[reportUnknownMemberType]
