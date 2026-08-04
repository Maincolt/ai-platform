"""External-service Concurrency guarantees against the real PostgreSQL database.

These tests exercise `PsycopgAgentPersistence`/`PsycopgOrchestratorPersistence`
directly against the real local PostgreSQL topology (see
`tests/integration/conftest.py`), proving three rows from Section 19's
"Critical Executable Scenarios" table that the mocked unit tests under
`tests/unit/adapters/persistence/` cannot: duplicate command (Agent-side
idempotent commit), duplicate result (Orchestrator-side idempotent terminal
outcome), and the deadline race (real transaction serialization deciding
exactly one terminal winner).

Every test builds its own workflow/task/attempt (or Agent outcome) with fresh
UUIDv7 identifiers, so concurrent or repeated runs never collide with other
data in the shared database.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from ai_platform.adapters.persistence.agent import PsycopgAgentPersistence
from ai_platform.adapters.persistence.connection import AsyncPsycopgPool
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
    AgentOutcomeCommitResult,
    CompletedAgentWork,
    DeadlinePersistenceDisposition,
    ExpiredAttempt,
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

pytestmark = pytest.mark.external_service

_CAPABILITY_NAME = "text.word-count"
_CAPABILITY_VERSION = "1.0"


def _new_id() -> str:
    return str(uuid.uuid7())


async def _open_orchestrator_pool(dsn: str) -> AsyncPsycopgPool:
    pool = AsyncPsycopgPool(dsn, component_schema="orchestrator", min_size=1, max_size=3)
    await pool.open()
    return pool


async def _open_agent_pool(dsn: str) -> AsyncPsycopgPool:
    pool = AsyncPsycopgPool(dsn, component_schema="agent", min_size=1, max_size=3)
    await pool.open()
    return pool


class _DispatchedFixture:
    def __init__(
        self,
        *,
        workflow_id: WorkflowId,
        task_id: TaskId,
        task_attempt_id: TaskAttemptId,
        correlation_id: CorrelationId,
        causation_message_id: MessageId,
        producer_component: str,
        producer_instance_id: str,
        input_text: str,
    ) -> None:
        self.workflow_id = workflow_id
        self.task_id = task_id
        self.task_attempt_id = task_attempt_id
        self.correlation_id = correlation_id
        self.causation_message_id = causation_message_id
        self.producer_component = producer_component
        self.producer_instance_id = producer_instance_id
        self.input_text = input_text


async def _submit_dispatched_workflow(
    persistence: PsycopgOrchestratorPersistence,
    *,
    now: datetime,
    task_result_deadline: datetime,
    input_text: str = "sprint seven integration words",
) -> _DispatchedFixture:
    """Commit a real, durably DISPATCHED workflow/task/attempt/outbox unit.

    Mirrors the shape `tests/component/orchestrator/test_persistence_ports.py`
    uses for the in-memory adapter, but against the real Postgres adapter with
    fresh identifiers so it is safe to run repeatedly against the shared
    database.
    """
    workflow_id = WorkflowId(_new_id())
    task_id = TaskId(_new_id())
    attempt_id = TaskAttemptId(_new_id())
    message_id = MessageId(_new_id())
    request_id = RequestId(_new_id())
    scope_id = IdempotencyScopeId(_new_id())
    correlation_id = CorrelationId(_new_id())
    agent_id = "sprint7-agent"
    implementation_identity = "sprint7-test-agent-impl"

    workflow = Workflow(
        workflow_id=workflow_id, request_id=request_id, correlation_id=correlation_id
    )
    workflow.receive(occurred_at=now)
    workflow.prepare(occurred_at=now)
    workflow.dispatch(occurred_at=now)

    task = Task(task_id=task_id, workflow_id=workflow_id, created_at=now)
    attempt = TaskAttempt(
        task_attempt_id=attempt_id,
        task_id=task_id,
        attempt_number=1,
        selection=SelectionIntent(
            agent_id=AgentId(agent_id),
            capability_name=_CAPABILITY_NAME,
            capability_version=_CAPABILITY_VERSION,
            implementation_identity=implementation_identity,
            implementation_version="1.0",
            command_contract_version="1.0",
            event_contract_versions=("1.0",),
            registry_revision="sprint7-rev-1",
            deployment_declaration_digest="sprint7-digest-1",
            selection_policy_version="1.0",
            availability_classification="READY",
            observed_at=now,
            selected_at=now,
        ),
        task_result_deadline=task_result_deadline,
    )
    payload = json.dumps({"contract_name": "ExecuteTask", "payload": {"input": input_text}}).encode(
        "utf-8"
    )
    outbox = OrchestratorOutboxRecord(
        message_id=message_id,
        workflow_id=workflow_id,
        logical_channel="task-commands",
        ordering_key=str(workflow_id),
        payload_bytes=payload,
        headers=(("content-type", b"application/json"),),
        creation_sequence=1,
        created_at=now,
    )
    intent = SubmissionCommitIntent(
        key=AcceptedRequestKey(
            environment="sprint7-integration",
            operation="workflow.submit",
            idempotency_scope_id=scope_id,
            request_id=request_id,
        ),
        evidence=AcceptanceEvidence(
            acceptance_actor_id=ActorId("sprint7-test-actor"),
            accepted_owner_subject_id=OwnerSubjectId("sprint7-test-owner"),
            current_owner_subject_id=OwnerSubjectId("sprint7-test-owner"),
            fingerprint=f"fingerprint-{workflow_id}",
            fingerprint_policy_version="1.0",
            policy_identity="sprint7-test-policy",
            policy_revision="rev-1",
            policy_decision="allow",
            scope_mapping_revision="rev-1",
            authorization_evidence="evidence-1",
            accepted_at=now,
        ),
        workflow=workflow,
        task=task,
        task_attempt=attempt,
        command_outbox=outbox,
        audit=AuditRecord(
            kind="workflow_accepted",
            workflow_id=workflow_id,
            occurred_at=now,
            actor_id=ActorId("sprint7-test-actor"),
            details={},
        ),
    )
    result = await persistence.commit_submission(intent)
    assert result.created is True

    return _DispatchedFixture(
        workflow_id=workflow_id,
        task_id=task_id,
        task_attempt_id=attempt_id,
        correlation_id=correlation_id,
        causation_message_id=message_id,
        producer_component=implementation_identity,
        producer_instance_id=agent_id,
        input_text=input_text,
    )


def _terminal_intent(
    fixture: _DispatchedFixture,
    *,
    word_count: int | None,
    failure_code: str | None = None,
    now: datetime,
) -> TerminalOutcomeIntent:
    return TerminalOutcomeIntent(
        environment="sprint7-integration",
        logical_consumer_id="sprint7-outcomes",
        validated_message_id=MessageId(_new_id()),
        immutable_message_digest=f"digest-{_new_id()}",
        workflow_id=fixture.workflow_id,
        task_id=fixture.task_id,
        task_attempt_id=fixture.task_attempt_id,
        correlation_id=fixture.correlation_id,
        causation_message_id=fixture.causation_message_id,
        producer_component=fixture.producer_component,
        producer_instance_id=fixture.producer_instance_id,
        capability_name=_CAPABILITY_NAME,
        capability_version=_CAPABILITY_VERSION,
        result_text=fixture.input_text if word_count is not None else None,
        agent_evidence_component=fixture.producer_component,
        agent_evidence_instance_id=fixture.producer_instance_id,
        outcome=AgentOutcome(
            task_attempt_id=fixture.task_attempt_id,
            completed_at=now,
            word_count=word_count,
            failure_code=failure_code,
        ),
        occurred_at=now,
        audit=AuditRecord(
            kind="workflow_terminal_outcome",
            workflow_id=fixture.workflow_id,
            occurred_at=now,
            actor_id=ActorId("system:sprint7-test"),
            details={},
        ),
    )


async def _commit_twice(
    persistence: PsycopgAgentPersistence, intent: AgentOutcomeCommitIntent
) -> tuple[AgentOutcomeCommitResult, AgentOutcomeCommitResult]:
    first = await persistence.commit_outcome(intent)
    second = await persistence.commit_outcome(intent)
    return first, second


def test_duplicate_command_execution_produces_exactly_one_agent_receipt(
    postgres_dsn: str,
) -> None:
    """'Duplicate command' (Section 19): redeliver the same completed Agent
    work twice through the real database and prove exactly one completed
    receipt/outcome/event-outbox identity is durably committed, not two.

    This is scoped at the Agent persistence integrity-unit boundary --
    the same durable-commit call `ExecuteTaskDeliveryHandler` -> `TestAgent`
    issues once per (redelivered) command -- rather than re-running the full
    Kafka-to-executor pipeline, since that mechanics is already covered by
    `test_event_bus_delivery.py` and by `TestAgent`'s own completed-receipt
    deduplication unit tests.
    """

    async def _body() -> None:
        pool = await _open_agent_pool(postgres_dsn)
        try:
            persistence = PsycopgAgentPersistence(pool)
            now = datetime.now(UTC)
            attempt_id = TaskAttemptId(_new_id())
            workflow_id = WorkflowId(_new_id())
            event_id = MessageId(_new_id())
            intent = AgentOutcomeCommitIntent(
                completed_work=CompletedAgentWork(
                    receipt=AgentCompletedReceipt(
                        environment="sprint7-integration",
                        agent_deployment_id=AgentId("sprint7-agent"),
                        task_attempt_id=attempt_id,
                        command_message_id=MessageId(_new_id()),
                        command_digest=f"digest-{_new_id()}",
                        terminal_event_message_id=event_id,
                        completed_at=now,
                    ),
                    outcome=AgentOutcome(
                        task_attempt_id=attempt_id, completed_at=now, word_count=7
                    ),
                    event_outbox=AgentEventOutboxRecord(
                        message_id=event_id,
                        workflow_id=workflow_id,
                        logical_channel="task-outcomes",
                        ordering_key=str(workflow_id),
                        payload_bytes=b'{"contract_name":"TaskCompleted"}',
                        headers=(("content-type", b"application/json"),),
                        creation_sequence=1,
                        created_at=now,
                    ),
                ),
                audit=AuditRecord(
                    kind="agent_outcome_committed",
                    workflow_id=workflow_id,
                    occurred_at=now,
                    actor_id=ActorId("agent:sprint7-agent"),
                    details={},
                ),
            )

            first, second = await _commit_twice(persistence, intent)

            assert first.created is True
            assert second.created is False
            assert second.completed_work == first.completed_work

            async with pool.connection() as connection:
                receipts = await (
                    await connection.execute(
                        "SELECT COUNT(*) FROM agent.completed_receipts WHERE task_attempt_id = %s",
                        (attempt_id,),
                    )
                ).fetchone()
                outcomes = await (
                    await connection.execute(
                        "SELECT COUNT(*) FROM agent.outcomes WHERE task_attempt_id = %s",
                        (attempt_id,),
                    )
                ).fetchone()
                events = await (
                    await connection.execute(
                        "SELECT COUNT(*) FROM agent.terminal_events WHERE task_attempt_id = %s",
                        (attempt_id,),
                    )
                ).fetchone()
            assert receipts is not None and receipts[0] == 1
            assert outcomes is not None and outcomes[0] == 1
            assert events is not None and events[0] == 1
        finally:
            await pool.close()

    asyncio.run(_body())


def test_duplicate_terminal_outcome_produces_exactly_one_transition(postgres_dsn: str) -> None:
    """'Duplicate result' (Section 19): redeliver the same terminal event
    twice and prove exactly one Orchestrator inbox disposition and terminal
    transition is durably recorded, not two.
    """

    async def _body() -> None:
        pool = await _open_orchestrator_pool(postgres_dsn)
        try:
            persistence = PsycopgOrchestratorPersistence(pool)
            now = datetime.now(UTC)
            fixture = await _submit_dispatched_workflow(
                persistence, now=now, task_result_deadline=now + timedelta(minutes=5)
            )
            intent = _terminal_intent(fixture, word_count=4, now=now)

            first = await persistence.apply_terminal_outcome(intent)
            second = await persistence.apply_terminal_outcome(intent)

            assert first.disposition is TerminalPersistenceDisposition.APPLIED
            assert second.disposition is TerminalPersistenceDisposition.DUPLICATE
            assert first.workflow is not None and first.workflow.state is not None
            assert first.workflow.state.value == "COMPLETED"

            async with pool.connection() as connection:
                history = await (
                    await connection.execute(
                        """
                        SELECT COUNT(*) FROM orchestrator.workflow_history
                        WHERE workflow_id = %s AND to_state = 'COMPLETED'
                        """,
                        (fixture.workflow_id,),
                    )
                ).fetchone()
                inbox = await (
                    await connection.execute(
                        """
                        SELECT COUNT(*) FROM orchestrator.inbox
                        WHERE workflow_id = %s
                        """,
                        (fixture.workflow_id,),
                    )
                ).fetchone()
            assert history is not None and history[0] == 1
            assert inbox is not None and inbox[0] == 1
        finally:
            await pool.close()

    asyncio.run(_body())


def test_deadline_race_produces_exactly_one_terminal_winner(postgres_dsn: str) -> None:
    """'Deadline race' (Section 19): a real terminal-outcome commit and a real
    deadline-expiry commit race concurrently for the same workflow. Real
    PostgreSQL row-level locking (both paths lock the `workflows` row with
    `SELECT ... FOR UPDATE`) must serialize them so exactly one applies and
    the other observes the already-terminal state safely (recorded as a late
    duplicate or as already-terminal), never a nondeterministic overwrite or
    two terminal transitions.
    """

    async def _body() -> None:
        pool = await _open_orchestrator_pool(postgres_dsn)
        try:
            persistence = PsycopgOrchestratorPersistence(pool)
            now = datetime.now(UTC)
            overdue_deadline = now - timedelta(minutes=1)
            fixture = await _submit_dispatched_workflow(
                persistence, now=now, task_result_deadline=overdue_deadline
            )

            terminal_intent = _terminal_intent(fixture, word_count=2, now=now)
            expired = ExpiredAttempt(
                workflow_id=fixture.workflow_id, task_attempt_id=fixture.task_attempt_id
            )
            deadline_audit = AuditRecord(
                kind="workflow_deadline_expired",
                workflow_id=fixture.workflow_id,
                occurred_at=now,
                actor_id=ActorId("system:sprint7-deadline"),
                details={},
            )

            terminal_result, deadline_result = await asyncio.gather(
                persistence.apply_terminal_outcome(terminal_intent),
                persistence.expire(expired, now=now, audit=deadline_audit),
            )

            terminal_won = (
                terminal_result.disposition is TerminalPersistenceDisposition.APPLIED
                and deadline_result is DeadlinePersistenceDisposition.ALREADY_TERMINAL
            )
            deadline_won = (
                deadline_result is DeadlinePersistenceDisposition.APPLIED
                and terminal_result.disposition
                is TerminalPersistenceDisposition.LATE_AFTER_TERMINAL
            )
            assert terminal_won or deadline_won, (
                terminal_result.disposition,
                deadline_result,
            )

            final = await persistence.get(fixture.workflow_id)
            assert final is not None and final.is_terminal

            async with pool.connection() as connection:
                terminal_rows = await (
                    await connection.execute(
                        """
                        SELECT COUNT(*) FROM orchestrator.workflow_history
                        WHERE workflow_id = %s AND to_state IN ('COMPLETED', 'FAILED')
                        """,
                        (fixture.workflow_id,),
                    )
                ).fetchone()
            assert terminal_rows is not None and terminal_rows[0] == 1
        finally:
            await pool.close()

    asyncio.run(_body())
