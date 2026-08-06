"""Unit tests for remaining value objects: Task/TaskAttempt, results, and
recovery records (outbox/inbox/receipt/outcome)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ai_platform.orchestrator.domain.results import WorkflowFailure, WorkflowResult
from ai_platform.orchestrator.domain.selection import SelectionIntent
from ai_platform.orchestrator.domain.task import Task, TaskAttempt
from ai_platform.shared.identifiers import (
    AgentId,
    TaskAttemptId,
    TaskId,
    WorkflowId,
)
from ai_platform.shared.outcomes import AgentOutcome

NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)


def _selection() -> SelectionIntent:
    return SelectionIntent(
        agent_id=AgentId("test-agent"),
        capability_name="text.word-count",
        capability_version="1.0",
        implementation_identity="test-agent-impl",
        implementation_version="1.0",
        command_contract_version="1.0",
        event_contract_versions=("1.0",),
        registry_revision="rev-1",
        deployment_declaration_digest="digest-1",
        selection_policy_version="1.0",
        availability_classification="ready",
        observed_at=NOW,
        selected_at=NOW,
    )


def test_task_attempt_number_must_be_one() -> None:
    task = Task(
        task_id=TaskId("019fbdd6-ab3d-77aa-8e61-4c41f9f4f1a1"),
        workflow_id=WorkflowId("019fbdd6-ab3d-77aa-8e61-4c3bc6d53f69"),
        created_at=NOW,
    )
    with pytest.raises(ValueError, match="exactly one attempt"):
        TaskAttempt(
            task_attempt_id=TaskAttemptId("019fbdd6-ab3d-77aa-8e61-4c425fab5f4b"),
            task_id=task.task_id,
            attempt_number=2,
            selection=_selection(),
            task_result_deadline=NOW,
        )


def test_workflow_result_rejects_empty_result_data() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        WorkflowResult(result_data={})


def test_workflow_failure_holds_code_and_detail() -> None:
    failure = WorkflowFailure(code="TASK_EXECUTION_FAILED", detail="boom")
    assert failure.code == "TASK_EXECUTION_FAILED"


def test_agent_outcome_rejects_both_success_and_failure_fields() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        AgentOutcome(
            task_attempt_id=TaskAttemptId("019fbdd6-ab3d-77aa-8e61-4c425fab5f4b"),
            completed_at=NOW,
            result_data={"word_count": 9},
            failure_code="TASK_EXECUTION_FAILED",
        )


def test_agent_outcome_rejects_neither_success_nor_failure_fields() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        AgentOutcome(
            task_attempt_id=TaskAttemptId("019fbdd6-ab3d-77aa-8e61-4c425fab5f4b"),
            completed_at=NOW,
        )


def test_agent_outcome_success_only() -> None:
    outcome = AgentOutcome(
        task_attempt_id=TaskAttemptId("019fbdd6-ab3d-77aa-8e61-4c425fab5f4b"),
        completed_at=NOW,
        result_data={"word_count": 9},
    )
    assert outcome.result_data == {"word_count": 9}
    assert outcome.failure_code is None
