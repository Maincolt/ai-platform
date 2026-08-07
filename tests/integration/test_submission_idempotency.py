"""External-service "one workflow per complete key" guarantee (Section 19).

`PsycopgOrchestratorPersistence.commit_submission` (`insert_accepted_request`)
relies on a real PostgreSQL `PRIMARY KEY`/`UNIQUE` constraint on
`orchestrator.accepted_requests` to arbitrate two commits carrying the same
`AcceptedRequestKey`: whichever `INSERT` wins the constraint gets
`created=True` and its workflow becomes durable; the loser resolves to the
winner's already-committed workflow via `SELECT` and gets `created=False`,
contributing no second workflow/task/attempt/outbox/audit row. This is
proven in-memory and at the component/API level elsewhere
(`tests/component/orchestrator/`, `tests/component/api/test_workflow_api.py`)
but never against the real constraint that is the actual arbitration
mechanism -- `tests/integration/test_concurrency.py` covers duplicate
command/duplicate result/deadline race, not this first-acceptance row.

Every test builds its own fresh `AcceptedRequestKey`, so concurrent or
repeated runs never collide with other data in the shared database.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

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
    *, key: AcceptedRequestKey, now: datetime, actor_suffix: str
) -> tuple[SubmissionCommitIntent, WorkflowId]:
    """Build one independently-valid submission for `key`.

    Two calls with the same `key` but different `actor_suffix` simulate two
    genuinely independent submission attempts racing (or repeating) the
    same accepted-request key -- each with its own fresh workflow/task/
    attempt identity, exactly as two different API request handlers would
    build them before either has seen the other's result.
    """
    workflow_id = WorkflowId(_new_id())
    task_id = TaskId(_new_id())
    attempt_id = TaskAttemptId(_new_id())
    message_id = MessageId(_new_id())

    workflow = Workflow(
        workflow_id=workflow_id, request_id=key.request_id, correlation_id=CorrelationId(_new_id())
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
            agent_id=AgentId(f"sprint10-idempotency-agent-{actor_suffix}"),
            capability_name=_CAPABILITY_NAME,
            capability_version=_CAPABILITY_VERSION,
            implementation_identity="sprint10-idempotency-impl",
            implementation_version="1.0",
            command_contract_version="1.0",
            event_contract_versions=("1.0",),
            registry_revision="sprint10-idempotency-rev-1",
            deployment_declaration_digest="sprint10-idempotency-digest-1",
            selection_policy_version="1.0",
            availability_classification="READY",
            observed_at=now,
            selected_at=now,
        ),
        task_result_deadline=now + timedelta(minutes=5),
    )
    payload = json.dumps(
        {"contract_name": "ExecuteTask", "payload": {"input": "sprint ten idempotency words"}}
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
        key=key,
        evidence=AcceptanceEvidence(
            acceptance_actor_id=ActorId(f"sprint10-idempotency-actor-{actor_suffix}"),
            accepted_owner_subject_id=OwnerSubjectId("sprint10-idempotency-owner"),
            current_owner_subject_id=OwnerSubjectId("sprint10-idempotency-owner"),
            fingerprint=f"fingerprint-{key.request_id}",
            fingerprint_policy_version="1.0",
            policy_identity="sprint10-idempotency-policy",
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
            actor_id=ActorId(f"sprint10-idempotency-actor-{actor_suffix}"),
            details={},
        ),
    )
    return intent, workflow_id


def test_sequential_resubmission_of_the_same_key_creates_no_second_workflow(
    postgres_orchestrator_app_dsn: str,
) -> None:
    async def run() -> None:
        now = datetime.now(UTC)
        key = AcceptedRequestKey(
            environment="sprint10-idempotency",
            operation="workflow.submit",
            idempotency_scope_id=IdempotencyScopeId(_new_id()),
            request_id=RequestId(_new_id()),
        )
        first_intent, first_workflow_id = _build_intent(key=key, now=now, actor_suffix="first")
        second_intent, second_workflow_id = _build_intent(key=key, now=now, actor_suffix="second")
        assert first_workflow_id != second_workflow_id

        pool = await _open_orchestrator_pool(postgres_orchestrator_app_dsn)
        try:
            persistence = PsycopgOrchestratorPersistence(pool)

            first_result = await persistence.commit_submission(first_intent)
            second_result = await persistence.commit_submission(second_intent)

            assert first_result.created is True
            assert first_result.resolution.workflow_id == first_workflow_id

            # The real UNIQUE constraint made the second commit resolve to
            # the first's already-durable workflow, not create its own.
            assert second_result.created is False
            assert second_result.resolution.workflow_id == first_workflow_id
            assert second_result.workflow.workflow_id == first_workflow_id

            async with pool.connection() as connection, connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT count(*) FROM orchestrator.workflows WHERE workflow_id = ANY(%s)",
                    ([str(first_workflow_id), str(second_workflow_id)],),
                )
                row = await cursor.fetchone()
                assert row is not None
                # Exactly one workflow row exists between the two
                # candidate identifiers -- the second workflow_id was
                # never persisted at all.
                assert row[0] == 1

                await cursor.execute(
                    "SELECT count(*) FROM orchestrator.accepted_requests "
                    "WHERE environment = %s AND operation = %s "
                    "AND idempotency_scope_id = %s AND request_id = %s",
                    (
                        key.environment,
                        key.operation,
                        str(key.idempotency_scope_id),
                        str(key.request_id),
                    ),
                )
                accepted_row = await cursor.fetchone()
                assert accepted_row is not None
                assert accepted_row[0] == 1
        finally:
            await pool.close()

    asyncio.run(run())


def test_concurrent_first_acceptance_of_the_same_key_has_exactly_one_winner(
    postgres_orchestrator_app_dsn: str,
) -> None:
    """Section 19's "Concurrent first acceptance" row: two genuinely
    concurrent commits racing the same key must still resolve to exactly
    one created workflow, decided by the real constraint under real
    transaction serialization -- not by which coroutine happened to run
    first in this process."""

    async def run() -> None:
        now = datetime.now(UTC)
        key = AcceptedRequestKey(
            environment="sprint10-idempotency-concurrent",
            operation="workflow.submit",
            idempotency_scope_id=IdempotencyScopeId(_new_id()),
            request_id=RequestId(_new_id()),
        )
        first_intent, first_workflow_id = _build_intent(key=key, now=now, actor_suffix="race-a")
        second_intent, second_workflow_id = _build_intent(key=key, now=now, actor_suffix="race-b")

        first_pool = await _open_orchestrator_pool(postgres_orchestrator_app_dsn)
        second_pool = await _open_orchestrator_pool(postgres_orchestrator_app_dsn)
        try:
            first_persistence = PsycopgOrchestratorPersistence(first_pool)
            second_persistence = PsycopgOrchestratorPersistence(second_pool)

            results = await asyncio.gather(
                first_persistence.commit_submission(first_intent),
                second_persistence.commit_submission(second_intent),
            )

            created_flags = [result.created for result in results]
            assert sorted(created_flags) == [False, True]

            winning_workflow_id = next(
                result.resolution.workflow_id for result in results if result.created
            )
            assert winning_workflow_id in (first_workflow_id, second_workflow_id)
            # Both results must agree on the same winner, whichever it was.
            assert results[0].resolution.workflow_id == results[1].resolution.workflow_id

            async with first_pool.connection() as connection, connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT count(*) FROM orchestrator.workflows WHERE workflow_id = ANY(%s)",
                    ([str(first_workflow_id), str(second_workflow_id)],),
                )
                row = await cursor.fetchone()
                assert row is not None
                assert row[0] == 1
        finally:
            await first_pool.close()
            await second_pool.close()

    asyncio.run(run())
