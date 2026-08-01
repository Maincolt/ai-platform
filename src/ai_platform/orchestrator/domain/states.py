"""Workflow state model (vertical-slice-01.md Section 9).

Only these five states exist: RECEIVED -> PENDING -> DISPATCHED ->
COMPLETED | FAILED. COMPLETED and FAILED are terminal.
"""

from enum import Enum


class WorkflowState(Enum):
    """The five legal workflow states."""

    RECEIVED = "RECEIVED"
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

    @property
    def is_terminal(self) -> bool:
        """COMPLETED and FAILED are the only terminal states."""
        return self in (WorkflowState.COMPLETED, WorkflowState.FAILED)


# The legal transition table from Section 9. `None` represents "no workflow
# yet" (the initial none -> RECEIVED transition).
_LEGAL_TRANSITIONS: dict[WorkflowState | None, frozenset[WorkflowState]] = {
    None: frozenset({WorkflowState.RECEIVED}),
    WorkflowState.RECEIVED: frozenset({WorkflowState.PENDING}),
    WorkflowState.PENDING: frozenset({WorkflowState.DISPATCHED}),
    WorkflowState.DISPATCHED: frozenset({WorkflowState.COMPLETED, WorkflowState.FAILED}),
    WorkflowState.COMPLETED: frozenset(),
    WorkflowState.FAILED: frozenset(),
}


def is_legal_transition(from_state: WorkflowState | None, to_state: WorkflowState) -> bool:
    """Return True only if `to_state` is a legal successor of `from_state`."""
    return to_state in _LEGAL_TRANSITIONS[from_state]
