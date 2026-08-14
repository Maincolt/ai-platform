"""Tests for the `ui.review` capability identity."""

from ai_platform.agents.ui_review_agent.capability import CAPABILITY_NAME, CAPABILITY_VERSION


def test_capability_identity_matches_adr_0019() -> None:
    assert CAPABILITY_NAME == "ui.review"
    assert CAPABILITY_VERSION == "1.0"
