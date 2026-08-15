"""Tests for the `technical.review` capability identity."""

from ai_platform.agents.technical_review_agent.capability import (
    CAPABILITY_NAME,
    CAPABILITY_VERSION,
)


def test_capability_identity_matches_adr_0022() -> None:
    assert CAPABILITY_NAME == "technical.review"
    assert CAPABILITY_VERSION == "1.0"
