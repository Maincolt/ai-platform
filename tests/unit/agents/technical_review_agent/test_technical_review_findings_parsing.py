"""Tests for `technical_review_agent.agent._parse_findings` -- turning the
AI Router's raw text response into a structured, schema-valid findings
list, or `None` (never a partial/best-effort result) on any shape
mismatch. Findings differ from `data_analysis_agent`'s only in key set:
`component` (free-text locator) replaces `metric`, since a reviewed
technical design has no metric concept -- the same adaptation
`data_analysis_agent`'s `metric` made from `architecture_review_agent`'s
`section`.
"""

import json

from ai_platform.agents.technical_review_agent.agent import (
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
                "component": "users table",
                "summary": "No unique constraint on email despite being used as a lookup key.",
                "severity": "high",
            },
            {
                "component": "POST /api/v1/workflows",
                "summary": "Missing idempotency key in the request contract.",
                "severity": "medium",
            },
        ]
    )

    findings = _parse_findings(raw)

    assert findings == [
        {
            "component": "users table",
            "summary": "No unique constraint on email despite being used as a lookup key.",
            "severity": "high",
        },
        {
            "component": "POST /api/v1/workflows",
            "summary": "Missing idempotency key in the request contract.",
            "severity": "medium",
        },
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
    assert _parse_findings("here are my thoughts on your design...") is None


def test_json_object_instead_of_array_is_rejected() -> None:
    assert _parse_findings(json.dumps({"component": "users table"})) is None


def test_finding_missing_a_required_key_is_rejected() -> None:
    raw = json.dumps([{"component": "users table", "summary": "x"}])  # no severity
    assert _parse_findings(raw) is None


def test_finding_with_an_extra_key_is_rejected() -> None:
    raw = json.dumps(
        [{"component": "users table", "summary": "x", "severity": "low", "confidence": 0.9}]
    )
    assert _parse_findings(raw) is None


def test_finding_with_a_data_analysis_metric_key_is_rejected() -> None:
    raw = json.dumps([{"metric": "p95 latency", "summary": "x", "severity": "low"}])
    assert _parse_findings(raw) is None


def test_finding_with_an_invalid_severity_is_rejected() -> None:
    raw = json.dumps([{"component": "users table", "summary": "x", "severity": "critical"}])
    assert _parse_findings(raw) is None


def test_finding_with_an_empty_component_is_rejected() -> None:
    raw = json.dumps([{"component": "", "summary": "x", "severity": "low"}])
    assert _parse_findings(raw) is None


def test_finding_with_an_oversized_component_is_rejected() -> None:
    raw = json.dumps([{"component": "x" * 201, "summary": "x", "severity": "low"}])
    assert _parse_findings(raw) is None


def test_finding_with_an_empty_summary_is_rejected() -> None:
    raw = json.dumps([{"component": "users table", "summary": "", "severity": "low"}])
    assert _parse_findings(raw) is None


def test_a_non_object_array_item_is_rejected() -> None:
    raw = json.dumps(["not an object"])
    assert _parse_findings(raw) is None


def test_too_many_findings_is_rejected() -> None:
    raw = _findings_json(
        [{"component": "users table", "summary": "x", "severity": "low"} for _ in range(101)]
    )
    assert _parse_findings(raw) is None
