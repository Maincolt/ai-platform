"""Tests for the `security.review` capability identity."""

from ai_platform.agents.security_review_agent.capability import (
    CAPABILITY_NAME,
    CAPABILITY_VERSION,
)


def test_capability_identity_matches_adr_0025() -> None:
    assert CAPABILITY_NAME == "security.review"
    assert CAPABILITY_VERSION == "1.0"
