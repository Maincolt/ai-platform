"""External-service audit-failure/rollback guarantee against the real database.

Section 19's "Audit failure" row requires: fail a required acceptance or
transition audit write and confirm the surrounding business transaction rolls
back atomically -- no business mutation is left durable without its required
audit evidence.

This test forces that failure for real rather than mocking it: it revokes
`INSERT` on `orchestrator.audit` from the real `ai_platform_orchestrator_runtime`
permission role (temporarily, as the `postgres` administrator), drives a real
`PsycopgOrchestratorPersistence.commit_submission` call through the real
`ai_platform_orchestrator_app` login, and confirms that neither the workflow,
task, task attempt, nor outbox row it also would have written was left
behind -- the whole integrity unit rolled back together with the failed audit
write, not just the audit table.

The revoked grant is always restored in a fixture teardown (even if the test
body fails), so the shared database is left in the same permission state
this test found it in.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterator
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
from ai_platform.orchestrator.domain.task import Task, TaskAttempt
from ai_platform.orchestrator.domain.workflow import Workflow
from ai_platform.ports.persistence.errors import PermanentPersistenceError
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


@pytest.fixture
def orchestrator_audit_insert_revoked(postgres_dsn: str) -> Iterator[None]:
    """Temporarily revoke INSERT on orchestrator.audit from the runtime role.

    Restores the exact grant bootstrap_roles.sql establishes
    (`GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA orchestrator
    TO ai_platform_orchestrator_runtime`) in a `finally` block so this always
    runs, even if the test body raises.
    """
    with psycopg.connect(postgres_dsn, connect_timeout=5) as connection:
        with connection.cursor() as cur:
            cur.execute("REVOKE INSERT ON orchestrator.audit FROM ai_platform_orchestrator_runtime")
        connection.commit()
    try:
        yield
    finally:
        with psycopg.connect(postgres_dsn, connect_timeout=5) as connection:
            with connection.cursor() as cur:
                cur.execute(
                    "GRANT INSERT ON orchestrator.audit TO ai_platform_orchestrator_runtime"
                )
            connection.commit()


def _build_submission_intent(*, now: datetime) -> tuple[SubmissionCommitIntent, WorkflowId]:
    workflow_id = WorkflowId(_new_id())
    task_id = TaskId(_new_id())
    attempt_id = TaskAttemptId(_new_id())
    message_id = MessageId(_new_id())
    request_id = RequestId(_new_id())
    scope_id = IdempotencyScopeId(_new_id())
    correlation_id = CorrelationId(_new_id())

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
            agent_id=AgentId("sprint7-audit-agent"),
            capability_name=_CAPABILITY_NAME,
            capability_version=_CAPABILITY_VERSION,
            implementation_identity="sprint7-audit-agent-impl",
            implementation_version="1.0",
            command_contract_version="1.0",
            event_contract_versions=("1.0",),
            registry_revision="sprint7-audit-rev-1",
            deployment_declaration_digest="sprint7-audit-digest-1",
            selection_policy_version="1.0",
            availability_classification="READY",
            observed_at=now,
            selected_at=now,
        ),
        task_result_deadline=now + timedelta(minutes=5),
    )
    payload = json.dumps(
        {"contract_name": "ExecuteTask", "payload": {"input": "sprint seven audit failure"}}
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
            environment="sprint7-audit-failure",
            operation="workflow.submit",
            idempotency_scope_id=scope_id,
            request_id=request_id,
        ),
        evidence=AcceptanceEvidence(
            acceptance_actor_id=ActorId("sprint7-audit-actor"),
            accepted_owner_subject_id=OwnerSubjectId("sprint7-audit-owner"),
            current_owner_subject_id=OwnerSubjectId("sprint7-audit-owner"),
            fingerprint=f"fingerprint-{workflow_id}",
            fingerprint_policy_version="1.0",
            policy_identity="sprint7-audit-policy",
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
            actor_id=ActorId("sprint7-audit-actor"),
            details={},
        ),
    )
    return intent, workflow_id


def test_failed_audit_write_rolls_back_the_entire_submission_transaction(
    postgres_orchestrator_app_dsn: str,
    postgres_dsn: str,
    orchestrator_audit_insert_revoked: None,
) -> None:
    now = datetime.now(UTC)
    intent, workflow_id = _build_submission_intent(now=now)

    async def _attempt_commit() -> None:
        pool = AsyncPsycopgPool(
            postgres_orchestrator_app_dsn,
            component_schema="orchestrator",
            expected_schema_version=_EXPECTED_ORCHESTRATOR_SCHEMA_VERSION,
            max_size=2,
        )
        await pool.open()
        try:
            persistence = PsycopgOrchestratorPersistence(pool)
            with pytest.raises(PermanentPersistenceError):
                await persistence.commit_submission(intent)
        finally:
            await pool.close()

    asyncio.run(_attempt_commit())

    # The whole integrity unit -- workflow, task, task attempt, and outbox --
    # must have rolled back with the failed audit write, not just the audit
    # table. Checked with the administrator connection so this assertion is
    # independent of the very grants under test.
    with psycopg.connect(postgres_dsn, connect_timeout=5) as connection, connection.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM orchestrator.workflows WHERE workflow_id = %s",
            (workflow_id,),
        )
        workflow_count = cur.fetchone()
        cur.execute(
            "SELECT COUNT(*) FROM orchestrator.tasks WHERE workflow_id = %s",
            (workflow_id,),
        )
        task_count = cur.fetchone()
        cur.execute(
            "SELECT COUNT(*) FROM orchestrator.outbox WHERE workflow_id = %s",
            (workflow_id,),
        )
        outbox_count = cur.fetchone()
        cur.execute(
            "SELECT COUNT(*) FROM orchestrator.audit WHERE workflow_id = %s",
            (workflow_id,),
        )
        audit_count = cur.fetchone()

    assert workflow_count == (0,)
    assert task_count == (0,)
    assert outbox_count == (0,)
    assert audit_count == (0,)
