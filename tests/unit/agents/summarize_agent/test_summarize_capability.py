"""Tests for the `text.summarize` capability identity."""

from ai_platform.agents.summarize_agent.capability import CAPABILITY_NAME, CAPABILITY_VERSION


def test_capability_identity_matches_adr_0014() -> None:
    assert CAPABILITY_NAME == "text.summarize"
    assert CAPABILITY_VERSION == "1.0"
