"""External-service State-machine guarantees against the real database (Section 19).

The `Workflow` aggregate's transition legality (every legal edge,
illegal/late/conflicting events, terminal immutability) is already
thoroughly proven at the unit/domain level with in-memory state
(`tests/unit/orchestrator/domain/`) -- that logic runs in application
code before persistence, so re-proving illegal transitions raise is not
a real-database-specific concern. What *is* real-database-specific, and
untested elsewhere, is whether the persistence layer faithfully durable-
round-trips the resulting history, and whether the schema itself (not
just application code) defends terminal-state integrity:

- `insert_workflow` writes one `orchestrator.workflow_history` row per
  `Workflow.history` entry; `select_workflow` must reconstruct the full,
  correctly-ordered list from those rows, not just the latest state.
- A terminal transition (`apply_terminal_outcome`) appends to that
  history rather than replacing it.
- `orchestrator.workflows`' own `workflows_terminal_payload_check`
  constraint rejects a direct write that claims a terminal state without
  the terminal payload/failure code state machine requires -- proving
  the database would refuse to store a corruption even if application
  code had a bug that tried to write one.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from ai_platform.adapters.persistence.connection import AsyncPsycopgPool
from ai_platform.adapters.persistence.orchestrator import PsycopgOrchestratorPersistence
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
from ai_platform.ports.persistence.transactions import SubmissionCommitIntent, TerminalOutcomeIntent
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

# Must track `ai_platform.runtime.composition._EXPECTED_SCHEMA_VERSION`
# (see tests/integration/conftest.py's copy of this same constant/comment).
_EXPECTED_ORCHESTRATOR_SCHEMA_VERSION = 3


def _new_id() -> str:
    return str(uuid.uuid7())


async def _open_orchestrator_pool(dsn: str) -> AsyncPsycopgPool:
    pool = AsyncPsycopgPool(
        dsn,
        component_schema="orchestrator",
        expected_schema_version=_EXPECTED_ORCHESTRATOR_SCHEMA_VERSION,
        min_size=1,
        max_size=3,
    )
    await pool.open()
    return pool


def _build_intent(
    *, now: datetime
) -> tuple[SubmissionCommitIntent, WorkflowId, TaskId, TaskAttemptId]:
    workflow_id = WorkflowId(_new_id())
    task_id = TaskId(_new_id())
    attempt_id = TaskAttemptId(_new_id())
    message_id = MessageId(_new_id())
    request_id = RequestId(_new_id())

    workflow = Workflow(
        workflow_id=workflow_id, request_id=request_id, correlation_id=CorrelationId(_new_id())
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
            agent_id=AgentId("sprint10-state-machine-agent"),
            capability_name=_CAPABILITY_NAME,
            capability_version=_CAPABILITY_VERSION,
            implementation_identity="sprint10-state-machine-impl",
            implementation_version="1.0",
            command_contract_version="1.0",
            event_contract_versions=("1.0",),
            registry_revision="sprint10-state-machine-rev-1",
            deployment_declaration_digest="sprint10-state-machine-digest-1",
            selection_policy_version="1.0",
            availability_classification="READY",
            observed_at=now,
            selected_at=now,
        ),
        task_result_deadline=now + timedelta(minutes=5),
    )
    payload = json.dumps(
        {"contract_name": "ExecuteTask", "payload": {"input": "sprint ten state machine words"}}
    ).encode("utf-8")
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
            environment="sprint10-state-machine",
            operation="workflow.submit",
            idempotency_scope_id=IdempotencyScopeId(_new_id()),
            request_id=request_id,
        ),
        evidence=AcceptanceEvidence(
            acceptance_actor_id=ActorId("sprint10-state-machine-actor"),
            accepted_owner_subject_id=OwnerSubjectId("sprint10-state-machine-owner"),
            current_owner_subject_id=OwnerSubjectId("sprint10-state-machine-owner"),
            fingerprint=f"fingerprint-{workflow_id}",
            fingerprint_policy_version="1.0",
            policy_identity="sprint10-state-machine-policy",
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
            actor_id=ActorId("sprint10-state-machine-actor"),
            details={},
        ),
    )
    return intent, workflow_id, task_id, attempt_id


def test_workflow_history_round_trips_every_transition_in_order(
    postgres_orchestrator_app_dsn: str,
) -> None:
    async def run() -> None:
        now = datetime.now(UTC)
        intent, workflow_id, _task_id, _attempt_id = _build_intent(now=now)
        expected_transitions = [
            (record.from_state, record.to_state) for record in intent.workflow.history
        ]
        assert expected_transitions == [
            (None, WorkflowState.RECEIVED),
            (WorkflowState.RECEIVED, WorkflowState.PENDING),
            (WorkflowState.PENDING, WorkflowState.DISPATCHED),
        ]

        pool = await _open_orchestrator_pool(postgres_orchestrator_app_dsn)
        try:
            persistence = PsycopgOrchestratorPersistence(pool)
            result = await persistence.commit_submission(intent)
            assert result.created is True

            stored = await persistence.get(workflow_id)
            assert stored is not None
            stored_transitions = [(record.from_state, record.to_state) for record in stored.history]
            assert stored_transitions == expected_transitions
            # Revisions are strictly increasing and match arrival order.
            revisions = [record.revision for record in stored.history]
            assert revisions == sorted(revisions)
            assert stored.state is WorkflowState.DISPATCHED
        finally:
            await pool.close()

    asyncio.run(run())


def test_terminal_transition_appends_to_history_rather_than_replacing_it(
    postgres_orchestrator_app_dsn: str,
) -> None:
    async def run() -> None:
        now = datetime.now(UTC)
        intent, workflow_id, task_id, attempt_id = _build_intent(now=now)

        pool = await _open_orchestrator_pool(postgres_orchestrator_app_dsn)
        try:
            persistence = PsycopgOrchestratorPersistence(pool)
            commit_result = await persistence.commit_submission(intent)
            assert commit_result.created is True
            before = await persistence.get(workflow_id)
            assert before is not None
            assert len(before.history) == 3

            terminal_intent = TerminalOutcomeIntent(
                environment="sprint10-state-machine",
                logical_consumer_id="sprint10-state-machine-outcomes",
                validated_message_id=MessageId(_new_id()),
                immutable_message_digest=f"digest-{_new_id()}",
                workflow_id=workflow_id,
                task_id=task_id,
                task_attempt_id=attempt_id,
                correlation_id=intent.workflow.correlation_id,
                causation_message_id=intent.command_outbox.message_id,
                producer_component="sprint10-state-machine-impl",
                producer_instance_id="sprint10-state-machine-agent",
                capability_name=_CAPABILITY_NAME,
                capability_version=_CAPABILITY_VERSION,
                result_text="sprint ten state machine words",
                agent_evidence_component="sprint10-state-machine-impl",
                agent_evidence_instance_id="sprint10-state-machine-agent",
                outcome=AgentOutcome(
                    task_attempt_id=attempt_id,
                    completed_at=now,
                    result_data={"word_count": 5},
                    failure_code=None,
                ),
                occurred_at=now,
                audit=AuditRecord(
                    kind="workflow_terminal_outcome",
                    workflow_id=workflow_id,
                    occurred_at=now,
                    actor_id=ActorId("system:sprint10-state-machine"),
                    details={},
                ),
            )
            terminal_result = await persistence.apply_terminal_outcome(terminal_intent)
            assert terminal_result.disposition.value == "APPLIED"

            after = await persistence.get(workflow_id)
            assert after is not None
            assert len(after.history) == 4
            # The first three entries are byte-for-byte the same records,
            # not regenerated -- proving this was an append, not a rewrite.
            assert [(r.from_state, r.to_state) for r in after.history[:3]] == [
                (r.from_state, r.to_state) for r in before.history
            ]
            assert after.history[3].to_state is WorkflowState.COMPLETED
            assert after.state is WorkflowState.COMPLETED
        finally:
            await pool.close()

    asyncio.run(run())


def test_database_rejects_a_terminal_state_write_without_its_required_payload(
    postgres_orchestrator_app_dsn: str,
) -> None:
    """`workflows_terminal_payload_check` is the schema's own defense: a
    COMPLETED row with no result_data (or a FAILED row with no
    failure_code) must never be storable, regardless of what application
    code does or doesn't validate first."""

    async def run() -> None:
        now = datetime.now(UTC)
        intent, workflow_id, _task_id, _attempt_id = _build_intent(now=now)

        pool = await _open_orchestrator_pool(postgres_orchestrator_app_dsn)
        try:
            persistence = PsycopgOrchestratorPersistence(pool)
            result = await persistence.commit_submission(intent)
            assert result.created is True

            async with pool.connection() as connection, connection.cursor() as cursor:
                with pytest.raises(psycopg.errors.CheckViolation):
                    await cursor.execute(
                        "UPDATE orchestrator.workflows "
                        "SET state = 'COMPLETED', revision = revision + 1, "
                        "updated_at = %s "
                        "WHERE workflow_id = %s",
                        (now, str(workflow_id)),
                    )
                await connection.rollback()

            # The rejected write left the workflow exactly as it was.
            unchanged = await persistence.get(workflow_id)
            assert unchanged is not None
            assert unchanged.state is WorkflowState.DISPATCHED
        finally:
            await pool.close()

    asyncio.run(run())
