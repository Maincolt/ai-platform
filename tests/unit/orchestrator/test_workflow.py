"""Unit tests for the Workflow aggregate's state machine (Section 9)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ai_platform.orchestrator.domain.errors import IllegalTransitionError, TerminalWorkflowError
from ai_platform.orchestrator.domain.results import WorkflowFailure, WorkflowResult
from ai_platform.orchestrator.domain.states import WorkflowState
from ai_platform.orchestrator.domain.workflow import Workflow
from ai_platform.shared.identifiers import CorrelationId, RequestId, WorkflowId

NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)


def _new_workflow() -> Workflow:
    return Workflow(
        workflow_id=WorkflowId("019fbdd6-ab3d-77aa-8e61-4c3bc6d53f69"),
        request_id=RequestId("019fbdd6-ab3d-77aa-8e61-4c3903e582ad"),
        correlation_id=CorrelationId("019fbdd6-ab3d-77aa-8e61-4c3a4e21ad64"),
    )


def test_full_happy_path_to_completed() -> None:
    workflow = _new_workflow()

    workflow.receive(occurred_at=NOW)
    workflow.prepare(occurred_at=NOW)
    workflow.dispatch(occurred_at=NOW)
    workflow.complete(WorkflowResult(word_count=9), occurred_at=NOW)

    assert workflow.state == WorkflowState.COMPLETED
    assert workflow.revision == 4
    assert workflow.is_terminal
    assert workflow.result == WorkflowResult(word_count=9)
    assert [t.to_state for t in workflow.history] == [
        WorkflowState.RECEIVED,
        WorkflowState.PENDING,
        WorkflowState.DISPATCHED,
        WorkflowState.COMPLETED,
    ]
    assert [t.revision for t in workflow.history] == [1, 2, 3, 4]
    assert workflow.history[0].from_state is None
    assert workflow.history[-1].cause == "task_completed"


def test_full_path_to_failed() -> None:
    workflow = _new_workflow()
    workflow.receive(occurred_at=NOW)
    workflow.prepare(occurred_at=NOW)
    workflow.dispatch(occurred_at=NOW)

    workflow.fail(WorkflowFailure(code="TASK_EXECUTION_FAILED", detail="boom"), occurred_at=NOW)

    assert workflow.state == WorkflowState.FAILED
    assert workflow.is_terminal
    assert workflow.failure == WorkflowFailure(code="TASK_EXECUTION_FAILED", detail="boom")


@pytest.mark.parametrize(
    ("setup_steps", "illegal_call"),
    [
        ([], "prepare"),  # none -> PENDING is illegal; must receive() first
        ([], "dispatch"),  # none -> DISPATCHED is illegal
        (["receive"], "dispatch"),  # RECEIVED -> DISPATCHED is illegal
        (["receive"], "complete"),  # RECEIVED -> COMPLETED is illegal
        (["receive", "prepare"], "receive"),  # PENDING -> RECEIVED is illegal
        (["receive", "prepare"], "complete"),  # PENDING -> COMPLETED is illegal
    ],
)
def test_illegal_transitions_raise(setup_steps: list[str], illegal_call: str) -> None:
    workflow = _new_workflow()
    for step in setup_steps:
        getattr(workflow, step)(occurred_at=NOW)

    with pytest.raises(IllegalTransitionError):
        if illegal_call == "complete":
            workflow.complete(WorkflowResult(word_count=1), occurred_at=NOW)
        else:
            getattr(workflow, illegal_call)(occurred_at=NOW)


def test_illegal_transition_appends_no_history() -> None:
    workflow = _new_workflow()

    with pytest.raises(IllegalTransitionError):
        workflow.dispatch(occurred_at=NOW)

    assert workflow.history == []
    assert workflow.revision == 0
    assert workflow.state is None


def test_duplicate_completion_after_terminal_raises_and_does_not_mutate() -> None:
    workflow = _new_workflow()
    workflow.receive(occurred_at=NOW)
    workflow.prepare(occurred_at=NOW)
    workflow.dispatch(occurred_at=NOW)
    workflow.complete(WorkflowResult(word_count=9), occurred_at=NOW)

    with pytest.raises(TerminalWorkflowError):
        workflow.complete(WorkflowResult(word_count=999), occurred_at=NOW)

    # The original result and history are unchanged by the rejected duplicate.
    assert workflow.result == WorkflowResult(word_count=9)
    assert len(workflow.history) == 4
    assert workflow.revision == 4


def test_late_failure_after_completion_raises_and_does_not_mutate() -> None:
    workflow = _new_workflow()
    workflow.receive(occurred_at=NOW)
    workflow.prepare(occurred_at=NOW)
    workflow.dispatch(occurred_at=NOW)
    workflow.complete(WorkflowResult(word_count=9), occurred_at=NOW)

    with pytest.raises(TerminalWorkflowError):
        workflow.fail(WorkflowFailure(code="LATE", detail="too late"), occurred_at=NOW)

    assert workflow.state == WorkflowState.COMPLETED
    assert workflow.failure is None


def test_deadline_expiry_cause_is_recorded_but_still_exclusive() -> None:
    workflow = _new_workflow()
    workflow.receive(occurred_at=NOW)
    workflow.prepare(occurred_at=NOW)
    workflow.dispatch(occurred_at=NOW)

    workflow.fail(
        WorkflowFailure(code="TASK_RESULT_DEADLINE_EXCEEDED", detail="no outcome in time"),
        occurred_at=NOW,
        cause="deadline_expired",
    )

    assert workflow.history[-1].cause == "deadline_expired"
    # A subsequent (late) TaskCompleted must still be rejected.
    with pytest.raises(TerminalWorkflowError):
        workflow.complete(WorkflowResult(word_count=9), occurred_at=NOW)
