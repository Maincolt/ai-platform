"""Tests for `architecture_review_agent.agent._parse_findings` -- turning
the AI Router's raw text response into a structured, schema-valid findings
list, or `None` (never a partial/best-effort result) on any shape
mismatch. Findings differ from `code.review`'s only in key set: `section`
(free-text locator) replaces `file`/`line`, since a reviewed document has
no file/line concept -- the same adaptation `ui.review`'s `area` made.
"""

import json

from ai_platform.agents.architecture_review_agent.agent import (
    _parse_findings,  # pyright: ignore[reportPrivateUsage]
)


def _findings_json(findings: list[dict[str, object]]) -> str:
    return json.dumps(findings)


def test_empty_array_is_a_valid_empty_findings_list() -> None:
    assert _parse_findings("[]") == []


def test_well_formed_findings_parse_correctly() -> None:
    raw = _findings_json(
        [
            {
                "section": "Decision 2",
                "summary": "Conflicts with ADR-0014's single-shot AI Router contract.",
                "severity": "high",
            },
            {
                "section": "Consequences",
                "summary": "Missing negative consequences.",
                "severity": "low",
            },
        ]
    )

    findings = _parse_findings(raw)

    assert findings == [
        {
            "section": "Decision 2",
            "summary": "Conflicts with ADR-0014's single-shot AI Router contract.",
            "severity": "high",
        },
        {"section": "Consequences", "summary": "Missing negative consequences.", "severity": "low"},
    ]


def test_response_wrapped_in_a_json_markdown_fence_still_parses() -> None:
    raw = "```json\n" + _findings_json([]) + "\n```"
    assert _parse_findings(raw) == []


def test_response_wrapped_in_a_plain_markdown_fence_still_parses() -> None:
    raw = "```\n" + _findings_json([]) + "\n```"
    assert _parse_findings(raw) == []


def test_malformed_content_inside_a_markdown_fence_is_still_rejected() -> None:
    raw = "```json\nnot valid json\n```"
    assert _parse_findings(raw) is None


def test_non_json_text_is_rejected() -> None:
    assert _parse_findings("here are my thoughts on your proposal...") is None


def test_json_object_instead_of_array_is_rejected() -> None:
    assert _parse_findings(json.dumps({"section": "Decision 2"})) is None


def test_finding_missing_a_required_key_is_rejected() -> None:
    raw = json.dumps([{"section": "Decision 2", "summary": "x"}])  # no severity
    assert _parse_findings(raw) is None


def test_finding_with_an_extra_key_is_rejected() -> None:
    raw = json.dumps(
        [{"section": "Decision 2", "summary": "x", "severity": "low", "confidence": 0.9}]
    )
    assert _parse_findings(raw) is None


def test_finding_with_a_code_review_file_line_key_is_rejected() -> None:
    raw = json.dumps([{"file": "a.py", "line": 1, "summary": "x", "severity": "low"}])
    assert _parse_findings(raw) is None


def test_finding_with_an_invalid_severity_is_rejected() -> None:
    raw = json.dumps([{"section": "Decision 2", "summary": "x", "severity": "critical"}])
    assert _parse_findings(raw) is None


def test_finding_with_an_empty_section_is_rejected() -> None:
    raw = json.dumps([{"section": "", "summary": "x", "severity": "low"}])
    assert _parse_findings(raw) is None


def test_finding_with_an_oversized_section_is_rejected() -> None:
    raw = json.dumps([{"section": "x" * 201, "summary": "x", "severity": "low"}])
    assert _parse_findings(raw) is None


def test_finding_with_an_empty_summary_is_rejected() -> None:
    raw = json.dumps([{"section": "Decision 2", "summary": "", "severity": "low"}])
    assert _parse_findings(raw) is None


def test_a_non_object_array_item_is_rejected() -> None:
    raw = json.dumps(["not an object"])
    assert _parse_findings(raw) is None


def test_too_many_findings_is_rejected() -> None:
    raw = _findings_json(
        [{"section": "Decision 2", "summary": "x", "severity": "low"} for _ in range(101)]
    )
    assert _parse_findings(raw) is None
