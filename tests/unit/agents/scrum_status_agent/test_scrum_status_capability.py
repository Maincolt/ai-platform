"""Tests for the `scrum.status` capability identity."""

from ai_platform.agents.scrum_status_agent.capability import (
    CAPABILITY_NAME,
    CAPABILITY_VERSION,
)


def test_capability_identity_matches_adr_0027() -> None:
    assert CAPABILITY_NAME == "scrum.status"
    assert CAPABILITY_VERSION == "1.0"
