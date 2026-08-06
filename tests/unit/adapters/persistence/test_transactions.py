"""Mocked async tests proving each integrity unit uses one adapter transaction."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import cast

from ai_platform.adapters.persistence.agent import PsycopgAgentPersistence
from ai_platform.adapters.persistence.connection import AsyncDbConnection, AsyncPsycopgPool
from ai_platform.adapters.persistence.orchestrator import PsycopgOrchestratorPersistence
from ai_platform.agents.domain.outcomes import AgentCompletedReceipt, AgentEventOutboxRecord
from ai_platform.orchestrator.domain.accepted_request import (
    AcceptanceEvidence,
    AcceptedRequestKey,
)
from ai_platform.orchestrator.domain.audit import AuditRecord
from ai_platform.orchestrator.domain.recovery import OrchestratorOutboxRecord
from ai_platform.orchestrator.domain.selection import SelectionIntent
from ai_platform.orchestrator.domain.task import Task, TaskAttempt
from ai_platform.orchestrator.domain.workflow import Workflow
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

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


class _Cursor:
    def __init__(self, row: tuple[object, ...] | None = None) -> None:
        self._row = row
        self.rowcount = 1

    async def fetchone(self) -> tuple[object, ...] | None:
        return self._row

    async def fetchall(self) -> list[tuple[object, ...]]:
        return []


class _Connection:
    def __init__(self, first_row: tuple[object, ...]) -> None:
        self._first_row = first_row
        self.queries: list[str] = []

    async def execute(self, query: object, params: object = None) -> _Cursor:
        del params
        self.queries.append(str(query))
        if len(self.queries) == 1:
            return _Cursor(self._first_row)
        return _Cursor()


class _Pool:
    def __init__(self, schema: str, connection: _Connection) -> None:
        self.component_schema = schema
        self._connection = connection
        self.transaction_entries = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncDbConnection]:
        self.transaction_entries += 1
        yield cast(AsyncDbConnection, self._connection)


def _submission_intent() -> SubmissionCommitIntent:
    workflow_id = WorkflowId("workflow-1")
    task_id = TaskId("task-1")
    attempt_id = TaskAttemptId("attempt-1")
    workflow = Workflow(
        workflow_id=workflow_id,
        request_id=RequestId("request-1"),
        correlation_id=CorrelationId("correlation-1"),
    )
    workflow.receive(occurred_at=NOW)
    workflow.prepare(occurred_at=NOW)
    workflow.dispatch(occurred_at=NOW)
    evidence = AcceptanceEvidence(
        acceptance_actor_id=ActorId("actor-1"),
        accepted_owner_subject_id=OwnerSubjectId("owner-1"),
        current_owner_subject_id=OwnerSubjectId("owner-1"),
        fingerprint="fingerprint",
        fingerprint_policy_version="1",
        policy_identity="local-policy",
        policy_revision="1",
        policy_decision="allow",
        scope_mapping_revision="1",
        authorization_evidence="authorized",
        accepted_at=NOW,
    )
    selection = SelectionIntent(
        agent_id=AgentId("agent-1"),
        capability_name="text.word-count",
        capability_version="1.0",
        implementation_identity="test-agent",
        implementation_version="1.0",
        command_contract_version="1.0",
        event_contract_versions=("1.0",),
        registry_revision="1",
        deployment_declaration_digest="digest",
        selection_policy_version="1",
        availability_classification="READY",
        observed_at=NOW,
        selected_at=NOW,
    )
    return SubmissionCommitIntent(
        key=AcceptedRequestKey(
            environment="test",
            operation="workflow.submit",
            idempotency_scope_id=IdempotencyScopeId("scope-1"),
            request_id=RequestId("request-1"),
        ),
        evidence=evidence,
        workflow=workflow,
        task=Task(task_id=task_id, workflow_id=workflow_id, created_at=NOW),
        task_attempt=TaskAttempt(
            task_attempt_id=attempt_id,
            task_id=task_id,
            attempt_number=1,
            selection=selection,
            task_result_deadline=NOW + timedelta(seconds=30),
        ),
        command_outbox=OrchestratorOutboxRecord(
            message_id=MessageId("command-1"),
            workflow_id=workflow_id,
            logical_channel="task-commands",
            ordering_key=str(workflow_id),
            payload_bytes=b"{}",
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


def test_submission_writes_every_record_in_one_adapter_transaction() -> None:
    intent = _submission_intent()
    evidence = intent.evidence
    accepted_row: tuple[object, ...] = (
        intent.key.environment,
        intent.key.operation,
        intent.key.idempotency_scope_id,
        intent.key.request_id,
        intent.workflow.workflow_id,
        evidence.acceptance_actor_id,
        evidence.accepted_owner_subject_id,
        evidence.current_owner_subject_id,
        evidence.fingerprint,
        evidence.fingerprint_policy_version,
        evidence.policy_identity,
        evidence.policy_revision,
        evidence.policy_decision,
        evidence.scope_mapping_revision,
        evidence.authorization_evidence,
        evidence.accepted_at,
    )
    connection = _Connection(accepted_row)
    pool = _Pool("orchestrator", connection)
    adapter = PsycopgOrchestratorPersistence(cast(AsyncPsycopgPool, pool))

    result = asyncio.run(adapter.commit_submission(intent))

    assert result.created
    assert pool.transaction_entries == 1
    joined = "\n".join(connection.queries)
    for table in (
        "accepted_requests",
        "workflows",
        "workflow_history",
        "tasks",
        "task_attempts",
        "outbox",
        "audit",
    ):
        assert table in joined


def test_agent_receipt_outcome_event_outbox_and_audit_share_one_transaction() -> None:
    work = CompletedAgentWork(
        receipt=AgentCompletedReceipt(
            environment="test",
            agent_deployment_id=AgentId("agent-1"),
            task_attempt_id=TaskAttemptId("attempt-1"),
            command_message_id=MessageId("command-1"),
            command_digest="digest",
            terminal_event_message_id=MessageId("event-1"),
            completed_at=NOW,
        ),
        outcome=AgentOutcome(
            task_attempt_id=TaskAttemptId("attempt-1"),
            completed_at=NOW,
            result_data={"word_count": 2},
        ),
        event_outbox=AgentEventOutboxRecord(
            message_id=MessageId("event-1"),
            workflow_id=WorkflowId("workflow-1"),
            logical_channel="task-outcomes",
            ordering_key="workflow-1",
            payload_bytes=b"{}",
            headers=(),
            creation_sequence=1,
            created_at=NOW,
        ),
    )
    intent = AgentOutcomeCommitIntent(
        completed_work=work,
        audit=AuditRecord(
            kind="agent_outcome",
            workflow_id=WorkflowId("workflow-1"),
            occurred_at=NOW,
            actor_id=ActorId("agent-1"),
        ),
    )
    connection = _Connection(("event-1",))
    pool = _Pool("agent", connection)
    adapter = PsycopgAgentPersistence(cast(AsyncPsycopgPool, pool))

    result = asyncio.run(adapter.commit_outcome(intent))

    assert result.created
    assert pool.transaction_entries == 1
    joined = "\n".join(connection.queries)
    for table in ("terminal_events", "completed_receipts", "outcomes", "event_outbox", "audit"):
        assert table in joined
