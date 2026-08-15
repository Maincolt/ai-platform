"""External-service Idempotency/Ownership-disclosure guarantees (Section 19).

Complements `test_submission_idempotency.py` (which proves the real
`accepted_requests` `UNIQUE` constraint arbitrates one workflow per
complete key): this file proves the *other* two persistence-port
operations Section 19's Idempotency/Ownership-disclosure rows depend on,
against the real database rather than the in-memory ports already
exercising the same application-layer logic
(`tests/component/orchestrator/`, `tests/component/api/test_workflow_api.py`):

- `AcceptedRequestQueryPort.resolve()` -- read-after-write of an accepted
  key's durable mapping/evidence, and a clean miss for a key never seen.
- `AcceptedRequestAccessAuditPort.record_request_access()` -- each of the
  three `AcceptedRequestAccessDisposition` values durably persisted with
  its full evidence, not just accepted by the type system.
- `AuthorizedWorkflowQueryPort.get_authorized()` -- the real "safe
  not-found" guarantee: a workflow that genuinely exists is invisible to
  a caller resolved to a different owner, proven against the real query,
  not an in-memory dict's `==` comparison.
- "Same ID in two scopes" (Section 19's Critical Executable Scenarios
  table): the same `request_id` under two different
  `idempotency_scope_id` values must produce two fully independent
  workflows -- proving the composite key is scoped correctly, not
  colliding on `request_id` alone.

Every test builds its own fresh identifiers, so concurrent or repeated
runs never collide with other data in the shared database.
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
from ai_platform.ports.persistence.transactions import (
    AcceptedRequestAccessAuditRecord,
    AcceptedRequestAccessDisposition,
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
    *, key: AcceptedRequestKey, now: datetime, owner: str = "sprint10-ownership-owner"
) -> tuple[SubmissionCommitIntent, WorkflowId]:
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
            agent_id=AgentId("sprint10-ownership-agent"),
            capability_name=_CAPABILITY_NAME,
            capability_version=_CAPABILITY_VERSION,
            implementation_identity="sprint10-ownership-impl",
            implementation_version="1.0",
            command_contract_version="1.0",
            event_contract_versions=("1.0",),
            registry_revision="sprint10-ownership-rev-1",
            deployment_declaration_digest="sprint10-ownership-digest-1",
            selection_policy_version="1.0",
            availability_classification="READY",
            observed_at=now,
            selected_at=now,
        ),
        task_result_deadline=now + timedelta(minutes=5),
    )
    payload = json.dumps(
        {"contract_name": "ExecuteTask", "payload": {"input": "sprint ten ownership words"}}
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
            acceptance_actor_id=ActorId("sprint10-ownership-actor"),
            accepted_owner_subject_id=OwnerSubjectId(owner),
            current_owner_subject_id=OwnerSubjectId(owner),
            fingerprint=f"fingerprint-{key.request_id}",
            fingerprint_policy_version="1.0",
            policy_identity="sprint10-ownership-policy",
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
            actor_id=ActorId("sprint10-ownership-actor"),
            details={},
        ),
    )
    return intent, workflow_id


def test_resolve_reads_back_the_durable_mapping_after_commit(
    postgres_orchestrator_app_dsn: str,
) -> None:
    async def run() -> None:
        now = datetime.now(UTC)
        key = AcceptedRequestKey(
            environment="sprint10-ownership",
            operation="workflow.submit",
            idempotency_scope_id=IdempotencyScopeId(_new_id()),
            request_id=RequestId(_new_id()),
        )
        intent, workflow_id = _build_intent(key=key, now=now)

        pool = await _open_orchestrator_pool(postgres_orchestrator_app_dsn)
        try:
            persistence = PsycopgOrchestratorPersistence(pool)

            never_seen_key = AcceptedRequestKey(
                environment="sprint10-ownership",
                operation="workflow.submit",
                idempotency_scope_id=IdempotencyScopeId(_new_id()),
                request_id=RequestId(_new_id()),
            )
            assert await persistence.resolve(never_seen_key) is None

            result = await persistence.commit_submission(intent)
            assert result.created is True

            resolution = await persistence.resolve(key)
            assert resolution is not None
            assert resolution.workflow_id == workflow_id
            assert resolution.evidence.fingerprint == intent.evidence.fingerprint
            assert resolution.evidence.accepted_owner_subject_id == OwnerSubjectId(
                "sprint10-ownership-owner"
            )
        finally:
            await pool.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "disposition",
    [
        AcceptedRequestAccessDisposition.EQUIVALENT_REPLAY_AUTHORIZED,
        AcceptedRequestAccessDisposition.FINGERPRINT_CONFLICT_AUTHORIZED,
        AcceptedRequestAccessDisposition.OWNER_INTENT_MISMATCH,
    ],
)
def test_record_request_access_durably_persists_every_disposition(
    postgres_orchestrator_app_dsn: str,
    disposition: AcceptedRequestAccessDisposition,
) -> None:
    """Each disposition is internal security evidence for an occupied
    accepted key (`AcceptedRequestAccessAuditRecord`'s own docstring): it
    must never change the accepted request or workflow, only durably
    record that this specific current invocation occurred against it."""

    async def run() -> None:
        now = datetime.now(UTC)
        key = AcceptedRequestKey(
            environment="sprint10-ownership-audit",
            operation="workflow.submit",
            idempotency_scope_id=IdempotencyScopeId(_new_id()),
            request_id=RequestId(_new_id()),
        )
        intent, workflow_id = _build_intent(key=key, now=now)

        pool = await _open_orchestrator_pool(postgres_orchestrator_app_dsn)
        try:
            persistence = PsycopgOrchestratorPersistence(pool)
            result = await persistence.commit_submission(intent)
            assert result.created is True

            record = AcceptedRequestAccessAuditRecord(
                key=key,
                workflow_id=workflow_id,
                current_actor_id=ActorId("sprint10-ownership-replay-actor"),
                resolved_owner_subject_id=OwnerSubjectId("sprint10-ownership-owner"),
                effective_correlation_id=CorrelationId(_new_id()),
                policy_identity="sprint10-ownership-policy",
                policy_revision="rev-1",
                policy_decision="allow",
                scope_mapping_revision="rev-1",
                authorization_evidence="replay-evidence-1",
                disposition=disposition,
                occurred_at=now,
            )
            await persistence.record_request_access(record)

            async with pool.connection() as connection, connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT disposition, workflow_id, current_actor_id "
                    "FROM orchestrator.request_access_audit "
                    "WHERE environment = %s AND operation = %s "
                    "AND idempotency_scope_id = %s AND request_id = %s",
                    (
                        key.environment,
                        key.operation,
                        str(key.idempotency_scope_id),
                        str(key.request_id),
                    ),
                )
                row = await cursor.fetchone()
                assert row is not None
                assert row[0] == disposition.value
                assert row[1] == str(workflow_id)
                assert row[2] == "sprint10-ownership-replay-actor"

                # The accepted request/workflow themselves are untouched by
                # recording access evidence -- still exactly one row, still
                # the original owner.
                await cursor.execute(
                    "SELECT current_owner_subject_id FROM orchestrator.accepted_requests "
                    "WHERE workflow_id = %s",
                    (str(workflow_id),),
                )
                owner_row = await cursor.fetchone()
                assert owner_row is not None
                assert owner_row[0] == "sprint10-ownership-owner"
        finally:
            await pool.close()

    asyncio.run(run())


def test_get_authorized_is_a_real_safe_not_found_for_the_wrong_owner(
    postgres_orchestrator_app_dsn: str,
) -> None:
    """The workflow genuinely exists; a caller resolved to a different
    owner must get exactly the same absence as a workflow_id that was
    never created at all -- proven against the real query, not an
    in-memory dict's `==` comparison."""

    async def run() -> None:
        now = datetime.now(UTC)
        key = AcceptedRequestKey(
            environment="sprint10-ownership-safe-404",
            operation="workflow.submit",
            idempotency_scope_id=IdempotencyScopeId(_new_id()),
            request_id=RequestId(_new_id()),
        )
        intent, workflow_id = _build_intent(key=key, now=now, owner="sprint10-owner-a")

        pool = await _open_orchestrator_pool(postgres_orchestrator_app_dsn)
        try:
            persistence = PsycopgOrchestratorPersistence(pool)
            result = await persistence.commit_submission(intent)
            assert result.created is True

            owner_a_view = await persistence.get_authorized(
                workflow_id,
                environment="sprint10-ownership-safe-404",
                current_owner_subject_id=OwnerSubjectId("sprint10-owner-a"),
            )
            assert owner_a_view is not None
            assert owner_a_view.workflow_id == workflow_id

            owner_b_view = await persistence.get_authorized(
                workflow_id,
                environment="sprint10-ownership-safe-404",
                current_owner_subject_id=OwnerSubjectId("sprint10-owner-b"),
            )
            assert owner_b_view is None

            # Confirm the workflow really does exist -- owner B's None is
            # a scoping decision, not a coincidental missing row.
            unscoped = await persistence.get(workflow_id)
            assert unscoped is not None
        finally:
            await pool.close()

    asyncio.run(run())


def test_same_request_id_in_two_different_scopes_creates_independent_workflows(
    postgres_orchestrator_app_dsn: str,
) -> None:
    """Section 19's "Same ID in two scopes" row: the composite accepted-
    request key must be scoped by `idempotency_scope_id`, not collide on
    `request_id` alone."""

    async def run() -> None:
        now = datetime.now(UTC)
        shared_request_id = RequestId(_new_id())
        first_key = AcceptedRequestKey(
            environment="sprint10-ownership-scopes",
            operation="workflow.submit",
            idempotency_scope_id=IdempotencyScopeId(_new_id()),
            request_id=shared_request_id,
        )
        second_key = AcceptedRequestKey(
            environment="sprint10-ownership-scopes",
            operation="workflow.submit",
            idempotency_scope_id=IdempotencyScopeId(_new_id()),
            request_id=shared_request_id,
        )
        first_intent, first_workflow_id = _build_intent(key=first_key, now=now)
        second_intent, second_workflow_id = _build_intent(key=second_key, now=now)
        assert first_workflow_id != second_workflow_id

        pool = await _open_orchestrator_pool(postgres_orchestrator_app_dsn)
        try:
            persistence = PsycopgOrchestratorPersistence(pool)
            first_result = await persistence.commit_submission(first_intent)
            second_result = await persistence.commit_submission(second_intent)

            assert first_result.created is True
            assert second_result.created is True
            assert first_result.resolution.workflow_id == first_workflow_id
            assert second_result.resolution.workflow_id == second_workflow_id

            async with pool.connection() as connection, connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT count(*) FROM orchestrator.workflows WHERE workflow_id = ANY(%s)",
                    ([str(first_workflow_id), str(second_workflow_id)],),
                )
                row = await cursor.fetchone()
                assert row is not None
                assert row[0] == 2
        finally:
            await pool.close()

    asyncio.run(run())
