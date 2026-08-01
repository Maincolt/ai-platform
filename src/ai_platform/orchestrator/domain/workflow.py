"""The workflow aggregate (vertical-slice-01.md Section 9).

Enforces the five-state transition table: illegal edges raise, terminal
states reject further mutation, every accepted transition increments the
revision and appends exactly one history record.
"""

from dataclasses import dataclass, field
from datetime import datetime

from ai_platform.orchestrator.domain.errors import IllegalTransitionError, TerminalWorkflowError
from ai_platform.orchestrator.domain.history import TransitionRecord
from ai_platform.orchestrator.domain.results import WorkflowFailure, WorkflowResult
from ai_platform.orchestrator.domain.states import WorkflowState, is_legal_transition
from ai_platform.shared.identifiers import CorrelationId, RequestId, WorkflowId


@dataclass(slots=True)
class Workflow:
    """The five-state workflow aggregate.

    `state` is `None` only before the first transition (`none -> RECEIVED`).
    Callers that need to react to a duplicate/late event on an
    already-terminal workflow should catch `TerminalWorkflowError` rather
    than checking `is_terminal` beforehand, to avoid a check-then-act race
    (the real race is arbitrated by the future persistence adapter's
    compare-and-set, not by this in-memory object).
    """

    workflow_id: WorkflowId
    request_id: RequestId
    correlation_id: CorrelationId
    state: WorkflowState | None = None
    revision: int = 0
    history: list[TransitionRecord] = field(default_factory=list)
    result: WorkflowResult | None = None
    failure: WorkflowFailure | None = None

    def _transition(self, to_state: WorkflowState, *, occurred_at: datetime, cause: str) -> None:
        if self.state is not None and self.state.is_terminal:
            raise TerminalWorkflowError(self.workflow_id, self.state)
        if not is_legal_transition(self.state, to_state):
            raise IllegalTransitionError(self.state, to_state)
        from_state = self.state
        self.revision += 1
        self.state = to_state
        self.history.append(
            TransitionRecord(
                workflow_id=self.workflow_id,
                from_state=from_state,
                to_state=to_state,
                revision=self.revision,
                occurred_at=occurred_at,
                cause=cause,
            )
        )

    def receive(self, *, occurred_at: datetime) -> None:
        """none -> RECEIVED: new authorized composite key, valid request, eligible Agent."""
        self._transition(WorkflowState.RECEIVED, occurred_at=occurred_at, cause="accepted_request")

    def prepare(self, *, occurred_at: datetime) -> None:
        """RECEIVED -> PENDING: task and attempt prepared."""
        self._transition(
            WorkflowState.PENDING, occurred_at=occurred_at, cause="task_attempt_prepared"
        )

    def dispatch(self, *, occurred_at: datetime) -> None:
        """PENDING -> DISPATCHED: immutable command durably recorded in the outbox."""
        self._transition(
            WorkflowState.DISPATCHED, occurred_at=occurred_at, cause="command_outbox_recorded"
        )

    def complete(self, result: WorkflowResult, *, occurred_at: datetime) -> None:
        """DISPATCHED -> COMPLETED: first accepted TaskCompleted."""
        self._transition(WorkflowState.COMPLETED, occurred_at=occurred_at, cause="task_completed")
        self.result = result

    def fail(
        self, failure: WorkflowFailure, *, occurred_at: datetime, cause: str = "task_failed"
    ) -> None:
        """DISPATCHED -> FAILED: first accepted TaskFailed, or deadline expiry.

        Pass `cause="deadline_expired"` for the reconciler path (Section 9,
        last row); the aggregate does not schedule or race the reconciler
        itself (Phase 3 process concern) but does enforce that only one
        terminal transition is ever accepted.
        """
        self._transition(WorkflowState.FAILED, occurred_at=occurred_at, cause=cause)
        self.failure = failure

    @property
    def is_terminal(self) -> bool:
        return self.state is not None and self.state.is_terminal
