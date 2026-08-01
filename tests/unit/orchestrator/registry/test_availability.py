"""Unit tests for bounded availability freshness (ADR-0008 Section 5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ai_platform.orchestrator.registry.availability import (
    AvailabilityClassification,
    AvailabilityObservation,
    is_fresh,
)

NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)


def _observation(
    classification: AvailabilityClassification,
    *,
    observed_at: datetime = NOW,
    ttl_seconds: float = 30.0,
) -> AvailabilityObservation:
    return AvailabilityObservation(
        classification=classification,
        observed_at=observed_at,
        ttl_seconds=ttl_seconds,
    )


def test_ready_within_ttl_is_fresh() -> None:
    observation = _observation(
        AvailabilityClassification.READY,
        observed_at=NOW - timedelta(seconds=10),
        ttl_seconds=30.0,
    )
    assert is_fresh(observation, now=NOW) is True


def test_ready_at_exact_ttl_boundary_is_fresh() -> None:
    observation = _observation(
        AvailabilityClassification.READY,
        observed_at=NOW - timedelta(seconds=30),
        ttl_seconds=30.0,
    )
    assert is_fresh(observation, now=NOW) is True


def test_ready_past_ttl_is_not_fresh() -> None:
    observation = _observation(
        AvailabilityClassification.READY,
        observed_at=NOW - timedelta(seconds=31),
        ttl_seconds=30.0,
    )
    assert is_fresh(observation, now=NOW) is False


@pytest.mark.parametrize(
    "classification",
    [
        AvailabilityClassification.STALE,
        AvailabilityClassification.UNKNOWN,
        AvailabilityClassification.UNAVAILABLE,
        AvailabilityClassification.DRAINING,
    ],
)
def test_non_ready_is_never_fresh_even_when_recent(
    classification: AvailabilityClassification,
) -> None:
    observation = _observation(classification, observed_at=NOW, ttl_seconds=30.0)
    assert is_fresh(observation, now=NOW) is False


@pytest.mark.parametrize(
    "classification",
    [
        AvailabilityClassification.STALE,
        AvailabilityClassification.UNKNOWN,
        AvailabilityClassification.UNAVAILABLE,
        AvailabilityClassification.DRAINING,
    ],
)
def test_non_ready_is_never_fresh_regardless_of_age(
    classification: AvailabilityClassification,
) -> None:
    observation = _observation(
        classification,
        observed_at=NOW - timedelta(seconds=1000),
        ttl_seconds=30.0,
    )
    assert is_fresh(observation, now=NOW) is False
