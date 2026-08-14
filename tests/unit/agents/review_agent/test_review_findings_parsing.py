"""Tests for `review_agent.agent._parse_findings` -- the one piece of logic
`code.review` needs beyond what `text.summarize`'s template already
provides: turning the AI Router's raw text response into a structured,
schema-valid findings list, or `None` (never a partial/best-effort
result) on any shape mismatch.
"""

import json

from ai_platform.agents.review_agent.agent import (
    _parse_findings,  # pyright: ignore[reportPrivateUsage]
)


def _findings_json(findings: list[dict[str, object]]) -> str:
    return json.dumps(findings)


def test_empty_array_is_a_valid_empty_findings_list() -> None:
    assert _parse_findings("[]") == []


def test_response_wrapped_in_a_json_markdown_fence_still_parses() -> None:
    """Regression: a real Anthropic model wrapped its response in a
    ```json ... ``` fence despite the prompt asking for ONLY a JSON array
    -- observed live, not a hypothetical. Fence-stripping is a
    presentation-format tolerance, not a laxer parse; malformed content
    inside the fence must still be rejected (see the next two tests)."""
    raw = "```json\n" + _findings_json([]) + "\n```"
    assert _parse_findings(raw) == []


def test_response_wrapped_in_a_plain_markdown_fence_still_parses() -> None:
    raw = "```\n" + _findings_json([]) + "\n```"
    assert _parse_findings(raw) == []


def test_malformed_content_inside_a_markdown_fence_is_still_rejected() -> None:
    raw = "```json\nnot valid json\n```"
    assert _parse_findings(raw) is None


def test_an_unclosed_markdown_fence_is_not_stripped_and_fails_to_parse() -> None:
    raw = "```json\n" + _findings_json([])
    assert _parse_findings(raw) is None


def test_well_formed_findings_parse_correctly() -> None:
    raw = _findings_json(
        [
            {"file": "src/a.py", "line": 12, "summary": "Unused import.", "severity": "low"},
            {"file": "src/b.py", "line": None, "summary": "Missing test.", "severity": "medium"},
        ]
    )

    findings = _parse_findings(raw)

    assert findings == [
        {"file": "src/a.py", "line": 12, "summary": "Unused import.", "severity": "low"},
        {"file": "src/b.py", "line": None, "summary": "Missing test.", "severity": "medium"},
    ]


def test_non_json_text_is_rejected() -> None:
    assert _parse_findings("here are my thoughts on your diff...") is None


def test_json_object_instead_of_array_is_rejected() -> None:
    assert _parse_findings(json.dumps({"file": "a.py"})) is None


def test_finding_missing_a_required_key_is_rejected() -> None:
    raw = json.dumps([{"file": "a.py", "line": 1, "summary": "x"}])  # no severity
    assert _parse_findings(raw) is None


def test_finding_with_an_extra_key_is_rejected() -> None:
    raw = json.dumps(
        [{"file": "a.py", "line": 1, "summary": "x", "severity": "low", "confidence": 0.9}]
    )
    assert _parse_findings(raw) is None


def test_finding_with_an_invalid_severity_is_rejected() -> None:
    raw = json.dumps([{"file": "a.py", "line": 1, "summary": "x", "severity": "critical"}])
    assert _parse_findings(raw) is None


def test_finding_with_an_empty_file_is_rejected() -> None:
    raw = json.dumps([{"file": "", "line": 1, "summary": "x", "severity": "low"}])
    assert _parse_findings(raw) is None


def test_finding_with_a_negative_line_is_rejected() -> None:
    raw = json.dumps([{"file": "a.py", "line": -1, "summary": "x", "severity": "low"}])
    assert _parse_findings(raw) is None


def test_finding_with_a_boolean_line_is_rejected() -> None:
    """`bool` is a subclass of `int` in Python -- `True`/`False` must not
    silently pass as a line number."""
    raw = json.dumps([{"file": "a.py", "line": True, "summary": "x", "severity": "low"}])
    assert _parse_findings(raw) is None


def test_finding_with_an_empty_summary_is_rejected() -> None:
    raw = json.dumps([{"file": "a.py", "line": 1, "summary": "", "severity": "low"}])
    assert _parse_findings(raw) is None


def test_a_non_object_array_item_is_rejected() -> None:
    raw = json.dumps(["not an object"])
    assert _parse_findings(raw) is None


def test_too_many_findings_is_rejected() -> None:
    raw = _findings_json(
        [{"file": "a.py", "line": i, "summary": "x", "severity": "low"} for i in range(101)]
    )
    assert _parse_findings(raw) is None
