"""Tests for `crypto_market_agent.agent._parse_findings` -- turning the AI
Router's raw text response into a structured, schema-valid findings list,
or `None` (never a partial/best-effort result) on any shape mismatch.
"""

import json

from ai_platform.agents.crypto_market_agent.agent import (
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
                "symbol": "BTCUSDT",
                "summary": "Up 8% in 24h, a notable move.",
                "severity": "medium",
            },
        ]
    )

    assert _parse_findings(raw) == [
        {"symbol": "BTCUSDT", "summary": "Up 8% in 24h, a notable move.", "severity": "medium"}
    ]


def test_response_wrapped_in_a_json_markdown_fence_still_parses() -> None:
    raw = "```json\n" + _findings_json([]) + "\n```"
    assert _parse_findings(raw) == []


def test_not_a_json_array_is_rejected() -> None:
    assert _parse_findings('{"symbol": "BTCUSDT"}') is None


def test_malformed_json_is_rejected() -> None:
    assert _parse_findings("not json") is None


def test_missing_required_key_is_rejected() -> None:
    raw = _findings_json([{"symbol": "BTCUSDT", "summary": "..."}])
    assert _parse_findings(raw) is None


def test_extra_key_is_rejected() -> None:
    raw = _findings_json(
        [{"symbol": "BTCUSDT", "summary": "...", "severity": "low", "extra": "nope"}]
    )
    assert _parse_findings(raw) is None


def test_invalid_severity_is_rejected() -> None:
    raw = _findings_json([{"symbol": "BTCUSDT", "summary": "...", "severity": "critical"}])
    assert _parse_findings(raw) is None


def test_empty_symbol_is_rejected() -> None:
    raw = _findings_json([{"symbol": "", "summary": "...", "severity": "low"}])
    assert _parse_findings(raw) is None
