"""Tests for the `assignment.route` capability identity."""

from ai_platform.agents.assignment_route_agent.capability import (
    CAPABILITY_NAME,
    CAPABILITY_VERSION,
)


def test_capability_identity_matches_adr_0023() -> None:
    assert CAPABILITY_NAME == "assignment.route"
    assert CAPABILITY_VERSION == "1.0"
