"""Append-only transition history (vertical-slice-01.md Section 9).

Every accepted logical state transition and its cause. History entries are
immutable and never rewritten; duplicate or late events do not append
duplicate history (enforced by the Workflow aggregate, not this type).
"""

from dataclasses import dataclass
from datetime import datetime

from ai_platform.orchestrator.domain.identifiers import WorkflowId
from ai_platform.orchestrator.domain.states import WorkflowState


@dataclass(frozen=True, slots=True)
class TransitionRecord:
    """One immutable, append-only workflow transition."""

    workflow_id: WorkflowId
    from_state: WorkflowState | None
    to_state: WorkflowState
    revision: int
    occurred_at: datetime
    cause: str
