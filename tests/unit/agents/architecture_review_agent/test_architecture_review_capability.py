"""Tests for the `architecture.review` capability identity."""

from ai_platform.agents.architecture_review_agent.capability import (
    CAPABILITY_NAME,
    CAPABILITY_VERSION,
)


def test_capability_identity_matches_adr_0020() -> None:
    assert CAPABILITY_NAME == "architecture.review"
    assert CAPABILITY_VERSION == "1.0"
