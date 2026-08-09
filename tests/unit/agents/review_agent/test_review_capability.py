"""Tests for the `code.review` capability identity."""

from ai_platform.agents.review_agent.capability import CAPABILITY_NAME, CAPABILITY_VERSION


def test_capability_identity_matches_adr_0018() -> None:
    assert CAPABILITY_NAME == "code.review"
    assert CAPABILITY_VERSION == "1.0"
