"""Domain exceptions for the workflow aggregate.

These are stable, transport/persistence-independent classifications. They
are not HTTP errors or Problem Details (that mapping is Phase 5, the
Workflow API's responsibility).
"""

from ai_platform.orchestrator.domain.identifiers import WorkflowId
from ai_platform.orchestrator.domain.states import WorkflowState


class WorkflowDomainError(Exception):
    """Base class for workflow domain errors."""


class IllegalTransitionError(WorkflowDomainError):
    """Raised when a transition is not a legal successor of the current state."""

    def __init__(self, from_state: WorkflowState | None, to_state: WorkflowState) -> None:
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(f"Illegal transition from {from_state} to {to_state}")


class TerminalWorkflowError(WorkflowDomainError):
    """Raised when attempting to mutate a workflow that is already terminal.

    Callers (the future Orchestrator, Phase 3) use this to implement
    idempotent duplicate/late-event handling: catching this error means the
    workflow already has a final disposition, so the caller should resolve
    and return the existing outcome rather than propagate a failure.
    """

    def __init__(self, workflow_id: WorkflowId, current_state: WorkflowState) -> None:
        self.workflow_id = workflow_id
        self.current_state = current_state
        super().__init__(
            f"Workflow {workflow_id} is already terminal at {current_state}; "
            "no further mutation is legal"
        )
