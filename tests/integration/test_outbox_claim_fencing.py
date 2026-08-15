"""External-service Inbox/outbox guarantees against the real database (Section 19).

Two rows from Section 19's Inbox/outbox category that
`tests/integration/test_recovery.py`/`test_concurrency.py` do not
directly exercise:

- **Claim fencing**: two publisher processes racing to claim the same
  eligible outbox row must have exactly one winner, decided by the real
  `UPDATE ... WHERE publication_state = 'NOT_ATTEMPTED'` claim query
  (`_outbox_common.claim_next`) under real transaction serialization, not
  application-level locking.
- **Duplicate/changed payload identity**: `orchestrator.outbox.message_id`
  is a real `PRIMARY KEY` -- a second row claiming the same message
  identity with *different* payload bytes must be rejected by the
  database itself, not merely by convention.
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
from ai_platform.adapters.persistence.outbox import OutboxRecoveryPolicy, PsycopgOutboxTransaction
from ai_platform.orchestrator.domain.accepted_request import (
    AcceptanceEvidence,
    AcceptedRequestKey,
)
from ai_platform.orchestrator.domain.audit import AuditRecord
from ai_platform.orchestrator.domain.recovery import OrchestratorOutboxRecord
from ai_platform.orchestrator.domain.selection import SelectionIntent
from ai_platform.orchestrator.domain.task import Task, TaskAttempt
from ai_platform.orchestrator.domain.workflow import Workflow
from ai_platform.ports.persistence.transactions import SubmissionCommitIntent
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

pytestmark = pytest.mark.external_service

_CAPABILITY_NAME = "text.word-count"
_CAPABILITY_VERSION = "1.0"

# Must track `ai_platform.runtime.composition._EXPECTED_SCHEMA_VERSION`
# (see tests/integration/conftest.py's copy of this same constant/comment).
_EXPECTED_ORCHESTRATOR_SCHEMA_VERSION = 4


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
    *, now: datetime, logical_channel: str
) -> tuple[SubmissionCommitIntent, MessageId]:
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
            agent_id=AgentId("sprint10-outbox-agent"),
            capability_name=_CAPABILITY_NAME,
            capability_version=_CAPABILITY_VERSION,
            implementation_identity="sprint10-outbox-impl",
            implementation_version="1.0",
            command_contract_version="1.0",
            event_contract_versions=("1.0",),
            registry_revision="sprint10-outbox-rev-1",
            deployment_declaration_digest="sprint10-outbox-digest-1",
            selection_policy_version="1.0",
            availability_classification="READY",
            observed_at=now,
            selected_at=now,
        ),
        task_result_deadline=now + timedelta(minutes=5),
    )
    payload = json.dumps(
        {"contract_name": "ExecuteTask", "payload": {"input": "sprint ten outbox words"}}
    ).encode("utf-8")
    outbox = OrchestratorOutboxRecord(
        message_id=message_id,
        workflow_id=workflow_id,
        logical_channel=logical_channel,
        ordering_key=str(workflow_id),
        payload_bytes=payload,
        headers=(("content-type", b"application/json"),),
        creation_sequence=1,
        created_at=now,
    )
    intent = SubmissionCommitIntent(
        key=AcceptedRequestKey(
            environment="sprint10-outbox",
            operation="workflow.submit",
            idempotency_scope_id=IdempotencyScopeId(_new_id()),
            request_id=request_id,
        ),
        evidence=AcceptanceEvidence(
            acceptance_actor_id=ActorId("sprint10-outbox-actor"),
            accepted_owner_subject_id=OwnerSubjectId("sprint10-outbox-owner"),
            current_owner_subject_id=OwnerSubjectId("sprint10-outbox-owner"),
            fingerprint=f"fingerprint-{workflow_id}",
            fingerprint_policy_version="1.0",
            policy_identity="sprint10-outbox-policy",
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
            actor_id=ActorId("sprint10-outbox-actor"),
            details={},
        ),
    )
    return intent, message_id


def test_concurrent_claim_next_has_exactly_one_winner(postgres_orchestrator_app_dsn: str) -> None:
    async def run() -> None:
        now = datetime.now(UTC)
        # A logical_channel unique to this test invocation, not the real
        # "task-commands" channel: `claim_next` picks the *oldest* eligible
        # row across the whole shared channel with `FOR UPDATE SKIP LOCKED`
        # (no blocking), so on a shared dev database accumulating
        # NOT_ATTEMPTED rows from other tests, two racers could each
        # cleanly claim a *different* pre-existing row without ever really
        # contending for this test's own row. A dedicated channel makes
        # this test's single row the only eligible candidate, so the race
        # is actually for it.
        logical_channel = f"sprint10-outbox-claim-fencing-{_new_id()}"
        intent, message_id = _build_intent(now=now, logical_channel=logical_channel)

        commit_pool = await _open_orchestrator_pool(postgres_orchestrator_app_dsn)
        try:
            persistence = PsycopgOrchestratorPersistence(commit_pool)
            result = await persistence.commit_submission(intent)
            assert result.created is True
        finally:
            await commit_pool.close()

        first_pool = await _open_orchestrator_pool(postgres_orchestrator_app_dsn)
        second_pool = await _open_orchestrator_pool(postgres_orchestrator_app_dsn)
        try:
            first_outbox = PsycopgOutboxTransaction(
                first_pool, recovery_policy=OutboxRecoveryPolicy(max_publication_attempts=3)
            )
            second_outbox = PsycopgOutboxTransaction(
                second_pool, recovery_policy=OutboxRecoveryPolicy(max_publication_attempts=3)
            )

            first_claim, second_claim = await asyncio.gather(
                first_outbox.claim_next(
                    logical_channel=logical_channel,
                    publisher_instance_id="sprint10-outbox-racer-a",
                    fencing_token=_new_id(),
                    claim_ttl=timedelta(seconds=30),
                ),
                second_outbox.claim_next(
                    logical_channel=logical_channel,
                    publisher_instance_id="sprint10-outbox-racer-b",
                    fencing_token=_new_id(),
                    claim_ttl=timedelta(seconds=30),
                ),
            )

            # The dedicated logical_channel makes this test's single row
            # the only eligible candidate for either racer, so this really
            # is a race for the same row, not a coincidence of separate
            # eligible rows.
            claims = [claim for claim in (first_claim, second_claim) if claim is not None]
            assert len(claims) == 1, f"expected exactly one winner, got {len(claims)}"
            assert claims[0].record.message_id == message_id

            async with first_pool.connection() as connection, connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT publication_state, publisher_instance_id, claim_token "
                    "FROM orchestrator.outbox WHERE message_id = %s",
                    (str(message_id),),
                )
                row = await cursor.fetchone()
                assert row is not None
                assert row[0] == "CLAIMED"
                assert row[1] in {"sprint10-outbox-racer-a", "sprint10-outbox-racer-b"}
                assert row[2] == claims[0].fencing_token
        finally:
            await first_pool.close()
            await second_pool.close()

    asyncio.run(run())


def test_database_rejects_a_second_message_id_with_different_payload(
    postgres_orchestrator_app_dsn: str,
) -> None:
    """`orchestrator.outbox.message_id` is a real `PRIMARY KEY`: a second
    insert claiming the same identity with different payload bytes must
    fail at the database, not merely be discouraged by convention."""

    async def run() -> None:
        now = datetime.now(UTC)
        intent, message_id = _build_intent(
            now=now, logical_channel=f"sprint10-outbox-duplicate-{_new_id()}"
        )

        pool = await _open_orchestrator_pool(postgres_orchestrator_app_dsn)
        try:
            persistence = PsycopgOrchestratorPersistence(pool)
            result = await persistence.commit_submission(intent)
            assert result.created is True

            async with pool.connection() as connection, connection.cursor() as cursor:
                with pytest.raises(psycopg.errors.UniqueViolation):
                    await cursor.execute(
                        "INSERT INTO orchestrator.outbox ("
                        "  message_id, workflow_id, logical_channel, ordering_key, "
                        "  payload_bytes, headers, creation_sequence, created_at"
                        ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                        (
                            str(message_id),
                            str(intent.workflow.workflow_id),
                            "task-commands",
                            str(intent.workflow.workflow_id),
                            b'{"contract_name":"ExecuteTask","payload":{"input":"different"}}',
                            json.dumps({"content-type": "application/json"}),
                            2,
                            now,
                        ),
                    )
                await connection.rollback()

            # The original row is unchanged by the rejected attempt.
            async with pool.connection() as connection, connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT count(*) FROM orchestrator.outbox WHERE message_id = %s",
                    (str(message_id),),
                )
                row = await cursor.fetchone()
                assert row is not None
                assert row[0] == 1
        finally:
            await pool.close()

    asyncio.run(run())
