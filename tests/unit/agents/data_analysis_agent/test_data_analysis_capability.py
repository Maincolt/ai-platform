"""Tests for the `data.analysis` capability identity."""

from ai_platform.agents.data_analysis_agent.capability import (
    CAPABILITY_NAME,
    CAPABILITY_VERSION,
)


def test_capability_identity_matches_adr_0021() -> None:
    assert CAPABILITY_NAME == "data.analysis"
    assert CAPABILITY_VERSION == "1.0"
