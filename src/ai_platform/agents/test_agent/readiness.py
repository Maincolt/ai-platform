"""Agent-owned readiness boundary (ADR-0008 Section 7).

Deliberately not shared with ai_platform.orchestrator.registry.availability:
the Agent exposes its *own* loaded-declaration identity and draining state
through its readiness boundary; it does not consume or interpret the
Orchestrator's Registry snapshot. Duplicating a small enum here is the
correct trade-off for genuine deployable independence (see
docs/sprint-4/consilium.md).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ReadinessClassification(Enum):
    READY = "READY"
    DECLARATION_MISMATCH = "DECLARATION_MISMATCH"
    DRAINING = "DRAINING"


@dataclass(frozen=True, slots=True)
class AgentReadiness:
    classification: ReadinessClassification
    loaded_declaration_digest: str
    checked_at: datetime


def evaluate_readiness(
    *,
    loaded_declaration_digest: str,
    expected_declaration_digest: str,
    is_draining: bool,
    now: datetime,
) -> AgentReadiness:
    """Evaluate readiness from the Agent's own perspective only.

    An unrelated Registry change elsewhere does not affect this: only a
    mismatch between the code-owned capability metadata and this
    deployment's own configuration (or an explicit draining state) can
    make the Agent unready (ADR-0008 Section 7).
    """
    if is_draining:
        classification = ReadinessClassification.DRAINING
    elif loaded_declaration_digest != expected_declaration_digest:
        classification = ReadinessClassification.DECLARATION_MISMATCH
    else:
        classification = ReadinessClassification.READY

    return AgentReadiness(
        classification=classification,
        loaded_declaration_digest=loaded_declaration_digest,
        checked_at=now,
    )
