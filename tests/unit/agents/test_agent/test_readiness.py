"""Unit tests for the Agent-owned readiness boundary (ADR-0008 Section 7)."""

from __future__ import annotations

from datetime import UTC, datetime

from ai_platform.agents.test_agent.readiness import ReadinessClassification, evaluate_readiness

NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)


def test_matching_declaration_and_not_draining_is_ready() -> None:
    readiness = evaluate_readiness(
        loaded_declaration_digest="sha256:abc",
        expected_declaration_digest="sha256:abc",
        is_draining=False,
        now=NOW,
    )
    assert readiness.classification == ReadinessClassification.READY
    assert readiness.loaded_declaration_digest == "sha256:abc"
    assert readiness.checked_at == NOW


def test_mismatched_declaration_is_not_ready() -> None:
    readiness = evaluate_readiness(
        loaded_declaration_digest="sha256:stale",
        expected_declaration_digest="sha256:abc",
        is_draining=False,
        now=NOW,
    )
    assert readiness.classification == ReadinessClassification.DECLARATION_MISMATCH


def test_draining_takes_precedence_over_a_matching_declaration() -> None:
    readiness = evaluate_readiness(
        loaded_declaration_digest="sha256:abc",
        expected_declaration_digest="sha256:abc",
        is_draining=True,
        now=NOW,
    )
    assert readiness.classification == ReadinessClassification.DRAINING
