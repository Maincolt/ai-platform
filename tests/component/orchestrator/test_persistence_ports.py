"""Component tests for the cohesive asynchronous persistence boundaries."""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from ai_platform.agents.domain.outcomes import AgentCompletedReceipt, AgentEventOutboxRecord
from ai_platform.api.inmemory_ports import (
    InMemoryAgentPersistence,
    InMemoryOrchestratorPersistence,
)
from ai_platform.orchestrator.domain.accepted_request import (
    AcceptanceEvidence,
    AcceptedRequestKey,
)
from ai_platform.orchestrator.domain.audit import AuditRecord
from ai_platform.orchestrator.domain.recovery import OrchestratorOutboxRecord
from ai_platform.orchestrator.domain.results import WorkflowFailure, WorkflowResult
from ai_platform.orchestrator.domain.selection import SelectionIntent
from ai_platform.orchestrator.domain.states import WorkflowState
from ai_platform.orchestrator.domain.task import Task, TaskAttempt
from ai_platform.orchestrator.domain.workflow import Workflow
from ai_platform.ports.persistence.errors import PersistenceConflictError
from ai_platform.ports.persistence.transactions import (
    AgentOutcomeCommitIntent,
    CompletedAgentWork,
    SubmissionCommitIntent,
)
from ai_platform.shared.identifiers import (
    ActorId,
    AgentId,
    CorrelationId,
    IdempotencyScopeId,
    MessageId,
    OwnerSubjectId,
    RequestId,
    TaskAttemptId,
    TaskId,
    WorkflowId,
)
from ai_platform.shared.outcomes import AgentOutcome

NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def _key(request_id: str = "req-1", *, scope: str = "scope-1") -> AcceptedRequestKey:
    return AcceptedRequestKey(
        environment="local-development",
        operation="workflow.submit",
        idempotency_scope_id=IdempotencyScopeId(scope),
        request_id=RequestId(request_id),
    )


def _evidence(fingerprint: str = "aaa") -> AcceptanceEvidence:
    return AcceptanceEvidence(
        acceptance_actor_id=ActorId("actor-1"),
        accepted_owner_subject_id=OwnerSubjectId("owner-1"),
        current_owner_subject_id=OwnerSubjectId("owner-1"),
        fingerprint=fingerprint,
        fingerprint_policy_version="1.0",
        policy_identity="local-development-policy",
        policy_revision="rev-1",
        policy_decision="allow",
        scope_mapping_revision="rev-1",
        authorization_evidence="evidence-1",
        accepted_at=NOW,
    )


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
        availability_classification="READY",
        observed_at=NOW,
        selected_at=NOW,
    )


def _submission_intent(
    *,
    key: AcceptedRequestKey | None = None,
    workflow_id: str = "wf-1",
    task_id: str = "task-1",
    attempt_id: str = "attempt-1",
    message_id: str = "command-1",
    capability_name: str = "",
    capability_version: str = "",
    input_text: str = "",
) -> SubmissionCommitIntent:
    key = key or _key()
    workflow_identifier = WorkflowId(workflow_id)
    workflow = Workflow(
        workflow_id=workflow_identifier,
        request_id=key.request_id,
        correlation_id=CorrelationId("corr-1"),
    )
    workflow.receive(occurred_at=NOW)
    workflow.prepare(occurred_at=NOW)
    workflow.dispatch(occurred_at=NOW)
    task = Task(
        task_id=TaskId(task_id),
        workflow_id=workflow_identifier,
        created_at=NOW,
    )
    attempt = TaskAttempt(
        task_attempt_id=TaskAttemptId(attempt_id),
        task_id=task.task_id,
        attempt_number=1,
        selection=_selection(),
        task_result_deadline=NOW + timedelta(seconds=30),
    )
    outbox = OrchestratorOutboxRecord(
        message_id=MessageId(message_id),
        workflow_id=workflow_identifier,
        logical_channel="task-commands",
        ordering_key=workflow_id,
        payload_bytes=b'{"contract_name":"ExecuteTask"}',
        headers=(("content-type", b"application/json"),),
        creation_sequence=1,
        created_at=NOW,
    )
    return SubmissionCommitIntent(
        key=key,
        evidence=_evidence(),
        workflow=workflow,
        task=task,
        task_attempt=attempt,
        command_outbox=outbox,
        audit=AuditRecord(
            kind="workflow_accepted",
            workflow_id=workflow_identifier,
            occurred_at=NOW,
            actor_id=ActorId("actor-1"),
            details={},
        ),
        capability_name=capability_name,
        capability_version=capability_version,
        input_text=input_text,
    )


def _agent_intent(
    *,
    word_count: int = 9,
    event_message_id: str = "event-1",
) -> AgentOutcomeCommitIntent:
    attempt_id = TaskAttemptId("attempt-1")
    event_id = MessageId(event_message_id)
    work = CompletedAgentWork(
        receipt=AgentCompletedReceipt(
            environment="local-development",
            agent_deployment_id=AgentId("test-agent"),
            task_attempt_id=attempt_id,
            command_message_id=MessageId("command-1"),
            command_digest="digest-1",
            terminal_event_message_id=event_id,
            completed_at=NOW,
        ),
        outcome=AgentOutcome(
            task_attempt_id=attempt_id,
            completed_at=NOW,
            result_data={"word_count": word_count},
        ),
        event_outbox=AgentEventOutboxRecord(
            message_id=event_id,
            workflow_id=WorkflowId("wf-1"),
            logical_channel="task-outcomes",
            ordering_key="wf-1",
            payload_bytes=b'{"contract_name":"TaskCompleted"}',
            headers=(("content-type", b"application/json"),),
            creation_sequence=1,
            created_at=NOW,
        ),
    )
    return AgentOutcomeCommitIntent(
        completed_work=work,
        audit=AuditRecord(
            kind="agent_outcome_committed",
            workflow_id=WorkflowId("wf-1"),
            occurred_at=NOW,
            actor_id=ActorId("agent:test-agent"),
            details={},
        ),
    )


def test_accepted_request_first_atomic_submission_is_new() -> None:
    persistence = InMemoryOrchestratorPersistence()

    result = _run(persistence.commit_submission(_submission_intent()))

    assert result.created is True
    assert result.resolution.workflow_id == WorkflowId("wf-1")
    assert result.resolution.evidence.fingerprint == "aaa"
    assert len(persistence.workflows) == 1
    assert len(persistence.command_outbox) == 1
    assert len(persistence.audit_records) == 1


def test_accepted_request_concurrent_duplicate_resolves_one_winner() -> None:
    persistence = InMemoryOrchestratorPersistence()
    first = _run(persistence.commit_submission(_submission_intent()))
    second = _run(
        persistence.commit_submission(
            _submission_intent(
                workflow_id="wf-2",
                task_id="task-2",
                attempt_id="attempt-2",
                message_id="command-2",
            )
        )
    )

    assert first.created is True
    assert second.created is False
    assert second.resolution.workflow_id == WorkflowId("wf-1")
    assert len(persistence.workflows) == 1
    assert len(persistence.command_outbox) == 1


def test_same_request_id_different_scope_is_independent() -> None:
    persistence = InMemoryOrchestratorPersistence()
    first = _run(persistence.commit_submission(_submission_intent()))
    second = _run(
        persistence.commit_submission(
            _submission_intent(
                key=_key(scope="scope-2"),
                workflow_id="wf-2",
                task_id="task-2",
                attempt_id="attempt-2",
                message_id="command-2",
            )
        )
    )

    assert first.created is True and second.created is True
    assert len(persistence.accepted_requests) == 2
    assert len(persistence.workflows) == 2


def test_agent_outcome_transaction_same_work_returns_stored_winner() -> None:
    persistence = InMemoryAgentPersistence()
    intent = _agent_intent()

    first = _run(persistence.commit_outcome(intent))
    second = _run(persistence.commit_outcome(intent))

    assert first.created is True
    assert second.created is False
    assert second.completed_work == first.completed_work
    assert len(persistence.event_outbox) == 1
    assert len(persistence.audit_records) == 1


def test_agent_outcome_transaction_rejects_different_outcome_for_attempt() -> None:
    persistence = InMemoryAgentPersistence()
    _run(persistence.commit_outcome(_agent_intent(word_count=9)))

    with pytest.raises(PersistenceConflictError, match="different completed Agent outcome"):
        _run(persistence.commit_outcome(_agent_intent(word_count=1, event_message_id="event-2")))

    stored = _run(persistence.get_completed(TaskAttemptId("attempt-1")))
    assert stored is not None and stored.outcome.result_data == {"word_count": 9}


def test_workflow_query_returns_an_immutable_snapshot_copy() -> None:
    persistence = InMemoryOrchestratorPersistence()
    committed = _run(persistence.commit_submission(_submission_intent()))

    retrieved = _run(persistence.get(committed.workflow.workflow_id))
    assert retrieved is not None
    retrieved.fail(
        failure=WorkflowFailure(code="LOCAL", detail="not durable"),
        occurred_at=NOW,
    )

    stored = _run(persistence.get(committed.workflow.workflow_id))
    assert stored is not None and stored.state is not None
    assert stored.state.value == "DISPATCHED"


def test_workflow_query_enforces_current_owner_and_environment() -> None:
    persistence = InMemoryOrchestratorPersistence()
    committed = _run(persistence.commit_submission(_submission_intent()))

    authorized = _run(
        persistence.get_authorized(
            committed.workflow.workflow_id,
            environment="local-development",
            current_owner_subject_id=OwnerSubjectId("owner-1"),
        )
    )
    wrong_owner = _run(
        persistence.get_authorized(
            committed.workflow.workflow_id,
            environment="local-development",
            current_owner_subject_id=OwnerSubjectId("owner-2"),
        )
    )

    assert authorized is not None
    assert wrong_owner is None


def test_submission_transaction_stores_task_and_attempt_together() -> None:
    persistence = InMemoryOrchestratorPersistence()
    intent = _submission_intent()

    _run(persistence.commit_submission(intent))

    assert persistence.tasks[intent.task.task_id] == intent.task
    assert persistence.task_attempts[intent.task_attempt.task_attempt_id] == intent.task_attempt


def test_submission_transaction_rejects_cross_workflow_outbox() -> None:
    persistence = InMemoryOrchestratorPersistence()
    intent = _submission_intent()
    invalid_outbox = dataclasses.replace(
        intent.command_outbox,
        workflow_id=WorkflowId("wrong-workflow"),
    )

    with pytest.raises(PersistenceConflictError, match="Command outbox workflow"):
        _run(
            persistence.commit_submission(
                dataclasses.replace(intent, command_outbox=invalid_outbox)
            )
        )

    assert persistence.accepted_requests == {}
    assert persistence.workflows == {}
    assert persistence.command_outbox == {}


def test_orchestrator_outbox_preserves_immutable_transport_metadata() -> None:
    persistence = InMemoryOrchestratorPersistence()
    intent = _submission_intent()

    _run(persistence.commit_submission(intent))

    stored = persistence.command_outbox[intent.command_outbox.message_id]
    assert stored.payload_bytes == b'{"contract_name":"ExecuteTask"}'
    assert stored.headers == (("content-type", b"application/json"),)
    assert stored.logical_channel == "task-commands"
    assert stored.ordering_key == "wf-1"
    assert stored.creation_sequence == 1


def test_agent_event_outbox_preserves_immutable_transport_metadata() -> None:
    persistence = InMemoryAgentPersistence()
    intent = _agent_intent()

    result = _run(persistence.commit_outcome(intent))

    stored = persistence.event_outbox[result.completed_work.event_outbox.message_id]
    assert stored.payload_bytes == b'{"contract_name":"TaskCompleted"}'
    assert stored.headers == (("content-type", b"application/json"),)
    assert stored.logical_channel == "task-outcomes"
    assert stored.ordering_key == "wf-1"
    assert stored.creation_sequence == 1


def test_submission_history_records_capability_and_input_on_new_submission() -> None:
    """ADR-0024: written in the same atomic commit, only on the
    `created=True` path."""
    persistence = InMemoryOrchestratorPersistence()
    intent = _submission_intent(
        capability_name="architecture.review",
        capability_version="1.0",
        input_text="review this design",
    )

    _run(persistence.commit_submission(intent))
    entries = _run(persistence.list_recent(capability_name=None, limit=10, before=None))

    assert len(entries) == 1
    assert entries[0].workflow_id == WorkflowId("wf-1")
    assert entries[0].capability_name == "architecture.review"
    assert entries[0].capability_version == "1.0"
    assert entries[0].input_text == "review this design"
    assert entries[0].state == WorkflowState.DISPATCHED


def test_submission_history_replay_does_not_duplicate_entry() -> None:
    persistence = InMemoryOrchestratorPersistence()
    intent = _submission_intent(capability_name="code.review")

    _run(persistence.commit_submission(intent))
    _run(persistence.commit_submission(intent))  # Same key -> EQUIVALENT_REPLAY, no new commit.
    entries = _run(persistence.list_recent(capability_name=None, limit=10, before=None))

    assert len(entries) == 1


def test_submission_history_filters_by_capability() -> None:
    persistence = InMemoryOrchestratorPersistence()
    _run(
        persistence.commit_submission(
            _submission_intent(
                key=_key("req-a"),
                workflow_id="wf-a",
                task_id="task-a",
                attempt_id="attempt-a",
                message_id="command-a",
                capability_name="code.review",
            )
        )
    )
    _run(
        persistence.commit_submission(
            _submission_intent(
                key=_key("req-b"),
                workflow_id="wf-b",
                task_id="task-b",
                attempt_id="attempt-b",
                message_id="command-b",
                capability_name="data.analysis",
            )
        )
    )

    entries = _run(persistence.list_recent(capability_name="code.review", limit=10, before=None))

    assert {entry.workflow_id for entry in entries} == {WorkflowId("wf-a")}


def test_submission_history_respects_limit_and_orders_newest_first() -> None:
    persistence = InMemoryOrchestratorPersistence()
    for index in range(3):
        _run(
            persistence.commit_submission(
                _submission_intent(
                    key=_key(f"req-{index}"),
                    workflow_id=f"wf-{index}",
                    task_id=f"task-{index}",
                    attempt_id=f"attempt-{index}",
                    message_id=f"command-{index}",
                    capability_name="code.review",
                )
            )
        )
        # Distinguish submitted_at ordering deterministically, since the
        # in-memory intents above all share NOW's history[0].occurred_at.
        persistence.submission_history[WorkflowId(f"wf-{index}")] = (
            "code.review",
            "1.0",
            "",
            NOW + timedelta(seconds=index),
        )

    entries = _run(persistence.list_recent(capability_name=None, limit=2, before=None))

    assert [entry.workflow_id for entry in entries] == [WorkflowId("wf-2"), WorkflowId("wf-1")]


def test_submission_history_before_cursor_excludes_at_or_after() -> None:
    persistence = InMemoryOrchestratorPersistence()
    _run(persistence.commit_submission(_submission_intent(capability_name="code.review")))

    entries = _run(persistence.list_recent(capability_name=None, limit=10, before=NOW))

    assert entries == []


def test_in_flight_count_reports_dispatched_attempt_by_agent() -> None:
    """The new submission commit leaves the workflow in DISPATCHED state
    with one attempt selected onto `_selection()`'s agent -- exactly the
    "claimed, no terminal outcome yet" shape `count_in_flight_by_agent`
    treats as busy."""
    persistence = InMemoryOrchestratorPersistence()
    _run(persistence.commit_submission(_submission_intent()))

    counts = _run(persistence.count_in_flight_by_agent())

    assert counts == {AgentId("test-agent"): 1}


def test_in_flight_count_is_empty_when_no_submissions_exist() -> None:
    persistence = InMemoryOrchestratorPersistence()

    counts = _run(persistence.count_in_flight_by_agent())

    assert counts == {}


def test_in_flight_count_aggregates_multiple_dispatched_attempts_per_agent() -> None:
    persistence = InMemoryOrchestratorPersistence()
    for index in range(2):
        _run(
            persistence.commit_submission(
                _submission_intent(
                    key=_key(f"req-{index}"),
                    workflow_id=f"wf-{index}",
                    task_id=f"task-{index}",
                    attempt_id=f"attempt-{index}",
                    message_id=f"command-{index}",
                )
            )
        )

    counts = _run(persistence.count_in_flight_by_agent())

    assert counts == {AgentId("test-agent"): 2}


def test_in_flight_count_excludes_attempts_once_workflow_reaches_terminal_state() -> None:
    """A COMPLETED/FAILED workflow's attempt is no longer "outstanding" --
    the count must be read fresh against current workflow state, not the
    attempt's own (durably DISPATCHED) record."""
    persistence = InMemoryOrchestratorPersistence()
    committed = _run(persistence.commit_submission(_submission_intent()))
    workflow = committed.workflow
    workflow.complete(result=WorkflowResult(result_data={"word_count": 1}), occurred_at=NOW)
    persistence.workflows[workflow.workflow_id] = workflow

    counts = _run(persistence.count_in_flight_by_agent())

    assert counts == {}
