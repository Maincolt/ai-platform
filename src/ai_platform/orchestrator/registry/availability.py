"""Bounded availability observations and freshness (ADR-0008 Sections 2, 5).

Static declarations supply permission and compatibility; a technology-neutral
readiness port supplies volatile availability. An observation is only
*fresh* when it is a `READY` classification observed within its TTL window.
Every other classification, and any expired `READY` observation, is treated
as not fresh and therefore fail-closed for selection (ADR-0008 Section 5).

`now` is always an explicit parameter so freshness is deterministic and
testable (see docs/sprint-3/consilium.md, disagreement 2).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from ai_platform.orchestrator.domain.identifiers import AgentId


class AvailabilityClassification(Enum):
    """Bounded readiness classifications for an Agent deployment."""

    READY = "READY"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"
    DRAINING = "DRAINING"


@dataclass(frozen=True, slots=True)
class AvailabilityObservation:
    """A single bounded readiness observation with its own freshness window."""

    classification: AvailabilityClassification
    observed_at: datetime
    ttl_seconds: float


class AvailabilityPort(Protocol):
    """Technology-neutral source of volatile Agent readiness observations."""

    def observe(
        self, agent_id: AgentId, capability_name: str, capability_version: str
    ) -> AvailabilityObservation:
        """Return the current readiness observation for one deployment."""
        ...


def is_fresh(observation: AvailabilityObservation, *, now: datetime) -> bool:
    """Return True only for a `READY` observation still within its TTL.

    Any non-`READY` classification, or a `READY` observation whose age
    exceeds `ttl_seconds`, is not fresh (fail-closed).
    """
    if observation.classification is not AvailabilityClassification.READY:
        return False
    age_seconds = (now - observation.observed_at).total_seconds()
    return age_seconds <= observation.ttl_seconds
