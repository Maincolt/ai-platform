"""Focused reference-adapter tests for the atomic persistence ports."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from ai_platform.agents.domain.outcomes import (
    AgentCompletedReceipt,
    AgentEventOutboxRecord,
)
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
from ai_platform.orchestrator.domain.selection import SelectionIntent
from ai_platform.orchestrator.domain.states import WorkflowState
from ai_platform.orchestrator.domain.task import Task, TaskAttempt
from ai_platform.orchestrator.domain.workflow import Workflow
from ai_platform.ports.persistence.errors import PersistenceConflictError
from ai_platform.ports.persistence.transactions import (
    AgentOutcomeCommitIntent,
    CompletedAgentWork,
    DeadlinePersistenceDisposition,
    SubmissionCommitIntent,
    TerminalOutcomeIntent,
    TerminalPersistenceDisposition,
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

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


def _selection() -> SelectionIntent:
    return SelectionIntent(
        agent_id=AgentId("agent-deployment-1"),
        capability_name="text.word-count",
        capability_version="1.0",
        implementation_identity="test-agent",
        implementation_version="1.0",
        command_contract_version="1.0",
        event_contract_versions=("1.0", "1.0"),
        registry_revision="registry-1",
        deployment_declaration_digest="sha256:declaration",
        selection_policy_version="1.0",
        availability_classification="ready",
        observed_at=NOW,
        selected_at=NOW,
    )


def _submission(suffix: str = "1") -> SubmissionCommitIntent:
    workflow_id = WorkflowId(f"workflow-{suffix}")
    request_id = RequestId("request-shared")
    correlation_id = CorrelationId("correlation-1")
    workflow = Workflow(
        workflow_id=workflow_id,
        request_id=request_id,
        correlation_id=correlation_id,
    )
    workflow.receive(occurred_at=NOW)
    workflow.prepare(occurred_at=NOW)
    workflow.dispatch(occurred_at=NOW)
    task = Task(task_id=TaskId(f"task-{suffix}"), workflow_id=workflow_id, created_at=NOW)
    attempt = TaskAttempt(
        task_attempt_id=TaskAttemptId(f"attempt-{suffix}"),
        task_id=task.task_id,
        attempt_number=1,
        selection=_selection(),
        task_result_deadline=NOW + timedelta(seconds=30),
    )
    key = AcceptedRequestKey(
        environment="test",
        operation="submit-workflow",
        idempotency_scope_id=IdempotencyScopeId("scope-1"),
        request_id=request_id,
    )
    evidence = AcceptanceEvidence(
        acceptance_actor_id=ActorId("actor-1"),
        accepted_owner_subject_id=OwnerSubjectId("owner-1"),
        current_owner_subject_id=OwnerSubjectId("owner-1"),
        fingerprint="fingerprint-1",
        fingerprint_policy_version="1.0",
        policy_identity="policy",
        policy_revision="1",
        policy_decision="allow",
        scope_mapping_revision="1",
        authorization_evidence="authorized",
        accepted_at=NOW,
    )
    return SubmissionCommitIntent(
        key=key,
        evidence=evidence,
        workflow=workflow,
        task=task,
        task_attempt=attempt,
        command_outbox=OrchestratorOutboxRecord(
            message_id=MessageId(f"command-{suffix}"),
            workflow_id=workflow_id,
            logical_channel="task-commands",
            ordering_key=str(workflow_id),
            payload_bytes=b'{"payload":{"input":"one two three"}}',
            headers=(),
            creation_sequence=1,
            created_at=NOW,
        ),
        audit=AuditRecord(
            kind="workflow_accepted",
            workflow_id=workflow_id,
            occurred_at=NOW,
            actor_id=ActorId("actor-1"),
        ),
    )


def _terminal(intent: SubmissionCommitIntent, message: str = "event-1") -> TerminalOutcomeIntent:
    return TerminalOutcomeIntent(
        environment="test",
        logical_consumer_id="orchestrator-outcomes-v1",
        validated_message_id=MessageId(message),
        immutable_message_digest="sha256:event",
        workflow_id=intent.workflow.workflow_id,
        task_id=intent.task.task_id,
        task_attempt_id=intent.task_attempt.task_attempt_id,
        correlation_id=intent.workflow.correlation_id,
        causation_message_id=intent.command_outbox.message_id,
        producer_component="test-agent",
        producer_instance_id="agent-deployment-1",
        capability_name="text.word-count",
        capability_version="1.0",
        result_text="one two three",
        agent_evidence_component="test-agent",
        agent_evidence_instance_id="agent-deployment-1",
        outcome=AgentOutcome(
            task_attempt_id=intent.task_attempt.task_attempt_id,
            completed_at=NOW + timedelta(seconds=1),
            result_data={"word_count": 3},
        ),
        occurred_at=NOW + timedelta(seconds=1),
        audit=AuditRecord(
            kind="workflow_terminal_outcome",
            workflow_id=intent.workflow.workflow_id,
            occurred_at=NOW + timedelta(seconds=1),
            actor_id=ActorId("system:outcome-consumer"),
        ),
    )


def _agent_outcome(intent: SubmissionCommitIntent) -> AgentOutcomeCommitIntent:
    outcome = AgentOutcome(
        task_attempt_id=intent.task_attempt.task_attempt_id,
        completed_at=NOW,
        result_data={"word_count": 3},
    )
    event = AgentEventOutboxRecord(
        message_id=MessageId("agent-event-1"),
        workflow_id=intent.workflow.workflow_id,
        logical_channel="task-outcomes",
        ordering_key=str(intent.workflow.workflow_id),
        payload_bytes=b"outcome",
        headers=(),
        creation_sequence=1,
        created_at=NOW,
    )
    return AgentOutcomeCommitIntent(
        completed_work=CompletedAgentWork(
            receipt=AgentCompletedReceipt(
                environment="test",
                agent_deployment_id=AgentId("agent-deployment-1"),
                task_attempt_id=intent.task_attempt.task_attempt_id,
                command_message_id=intent.command_outbox.message_id,
                command_digest="sha256:command",
                terminal_event_message_id=event.message_id,
                completed_at=NOW,
            ),
            outcome=outcome,
            event_outbox=event,
        ),
        audit=AuditRecord(
            kind="agent_outcome_committed",
            workflow_id=intent.workflow.workflow_id,
            occurred_at=NOW,
            actor_id=ActorId("agent:agent-deployment-1"),
        ),
    )


def test_concurrent_submission_arbitration_commits_one_complete_unit() -> None:
    async def scenario() -> None:
        store = InMemoryOrchestratorPersistence()
        first, second = await asyncio.gather(
            store.commit_submission(_submission("1")),
            store.commit_submission(_submission("2")),
        )

        assert sorted((first.created, second.created)) == [False, True]
        assert first.resolution.workflow_id == second.resolution.workflow_id
        assert len(store.accepted_requests) == 1
        assert len(store.workflows) == 1
        assert len(store.tasks) == 1
        assert len(store.task_attempts) == 1
        assert len(store.command_outbox) == 1
        assert len(store.audit_records) == 1

    asyncio.run(scenario())


def test_submission_validation_failure_leaves_no_partial_writes() -> None:
    async def scenario() -> None:
        store = InMemoryOrchestratorPersistence()
        intent = _submission()
        invalid = replace(
            intent,
            command_outbox=replace(intent.command_outbox, ordering_key="wrong-workflow"),
        )

        with pytest.raises(PersistenceConflictError):
            await store.commit_submission(invalid)

        assert not store.accepted_requests
        assert not store.workflows
        assert not store.tasks
        assert not store.task_attempts
        assert not store.command_outbox
        assert not store.audit_records

    asyncio.run(scenario())


def test_agent_outcome_reuses_exact_winner_and_rejects_content_conflict() -> None:
    async def scenario() -> None:
        store = InMemoryAgentPersistence()
        intent = _agent_outcome(_submission())

        created = await store.commit_outcome(intent)
        competing_event = replace(
            intent.completed_work.event_outbox,
            message_id=MessageId("losing-event"),
            payload_bytes=b"equivalent outcome with losing identity",
            created_at=NOW + timedelta(milliseconds=1),
        )
        competing_work = replace(
            intent.completed_work,
            receipt=replace(
                intent.completed_work.receipt,
                terminal_event_message_id=competing_event.message_id,
                completed_at=NOW + timedelta(milliseconds=1),
            ),
            outcome=replace(
                intent.completed_work.outcome,
                completed_at=NOW + timedelta(milliseconds=1),
            ),
            event_outbox=competing_event,
        )
        reused = await store.commit_outcome(replace(intent, completed_work=competing_work))
        conflicting_work = replace(
            intent.completed_work,
            outcome=replace(intent.completed_work.outcome, result_data={"word_count": 99}),
        )
        with pytest.raises(PersistenceConflictError):
            await store.commit_outcome(replace(intent, completed_work=conflicting_work))

        assert created.created is True
        assert reused.created is False
        assert reused.completed_work == created.completed_work
        assert len(store.completed_work) == 1
        assert len(store.event_outbox) == 1
        assert len(store.audit_records) == 1

    asyncio.run(scenario())


def test_terminal_inbox_applies_once_then_deduplicates_and_detects_digest_reuse() -> None:
    async def scenario() -> None:
        store = InMemoryOrchestratorPersistence()
        submission = _submission()
        await store.commit_submission(submission)
        terminal = _terminal(submission)

        applied = await store.apply_terminal_outcome(terminal)
        duplicate = await store.apply_terminal_outcome(terminal)
        conflict = await store.apply_terminal_outcome(
            replace(terminal, immutable_message_digest="sha256:different")
        )

        assert applied.disposition is TerminalPersistenceDisposition.APPLIED
        assert duplicate.disposition is TerminalPersistenceDisposition.DUPLICATE
        assert conflict.disposition is TerminalPersistenceDisposition.PERMANENT_CONFLICT
        assert applied.workflow is not None
        assert applied.workflow.state is WorkflowState.COMPLETED
        assert applied.workflow.revision == 4
        assert len(store.audit_records) == 2

    asyncio.run(scenario())


def test_deadline_and_terminal_event_race_has_one_terminal_winner() -> None:
    async def scenario() -> None:
        store = InMemoryOrchestratorPersistence()
        submission = _submission()
        await store.commit_submission(submission)
        candidate = (await store.find_expired(now=NOW + timedelta(minutes=1), limit=1))[0]
        deadline_audit = AuditRecord(
            kind="workflow_deadline_expired",
            workflow_id=submission.workflow.workflow_id,
            occurred_at=NOW + timedelta(minutes=1),
            actor_id=ActorId("system:deadline-reconciler"),
        )

        deadline_result, terminal_result = await asyncio.gather(
            store.expire(candidate, now=NOW + timedelta(minutes=1), audit=deadline_audit),
            store.apply_terminal_outcome(_terminal(submission)),
        )
        workflow = await store.get(submission.workflow.workflow_id)

        assert workflow is not None
        assert workflow.is_terminal
        assert workflow.revision == 4
        assert len(workflow.history) == 4
        assert (
            deadline_result is DeadlinePersistenceDisposition.APPLIED
            and terminal_result.disposition is TerminalPersistenceDisposition.LATE_AFTER_TERMINAL
        ) or (
            deadline_result is DeadlinePersistenceDisposition.ALREADY_TERMINAL
            and terminal_result.disposition is TerminalPersistenceDisposition.APPLIED
        )
        expected_audits = (
            3
            if terminal_result.disposition is TerminalPersistenceDisposition.LATE_AFTER_TERMINAL
            else 2
        )
        assert len(store.audit_records) == expected_audits

    asyncio.run(scenario())


def test_workflow_query_returns_an_isolated_snapshot() -> None:
    async def scenario() -> None:
        store = InMemoryOrchestratorPersistence()
        submission = _submission()
        await store.commit_submission(submission)

        queried = await store.get(submission.workflow.workflow_id)
        assert queried is not None
        queried.history.clear()
        queried_again = await store.get(submission.workflow.workflow_id)

        assert queried_again is not None
        assert len(queried_again.history) == 3

    asyncio.run(scenario())
