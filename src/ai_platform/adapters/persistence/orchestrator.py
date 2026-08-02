"""Async Psycopg adapter for Orchestrator queries and integrity units."""

import json
from collections.abc import Mapping
from datetime import datetime
from typing import cast

from ai_platform.adapters.persistence._outbox_common import insert_outbox
from ai_platform.adapters.persistence.accepted_request import (
    insert_accepted_request,
    select_accepted_request,
)
from ai_platform.adapters.persistence.audit import insert_audit
from ai_platform.adapters.persistence.connection import AsyncDbConnection, AsyncPsycopgPool
from ai_platform.adapters.persistence.retry import (
    DEFAULT_TRANSACTION_RETRY_POLICY,
    TransactionRetryPolicy,
    retry_transaction,
)
from ai_platform.adapters.persistence.task import insert_task_and_attempt, update_task_outcome
from ai_platform.adapters.persistence.workflow import (
    insert_workflow,
    select_workflow,
    update_workflow,
)
from ai_platform.orchestrator.domain.accepted_request import AcceptedRequestKey
from ai_platform.orchestrator.domain.audit import AuditRecord
from ai_platform.orchestrator.domain.results import WorkflowFailure, WorkflowResult
from ai_platform.orchestrator.domain.states import WorkflowState
from ai_platform.orchestrator.domain.workflow import Workflow
from ai_platform.ports.persistence.errors import PermanentPersistenceError
from ai_platform.ports.persistence.transactions import (
    AcceptedRequestAccessAuditRecord,
    AcceptedRequestResolution,
    DeadlinePersistenceDisposition,
    ExpiredAttempt,
    SubmissionCommitIntent,
    SubmissionCommitResult,
    TerminalOutcomeCommitResult,
    TerminalOutcomeIntent,
    TerminalPersistenceDisposition,
)
from ai_platform.shared.identifiers import OwnerSubjectId, TaskAttemptId, TaskId, WorkflowId


class PsycopgOrchestratorPersistence:
    """Implements Orchestrator query and transaction-shaped persistence ports."""

    def __init__(
        self,
        pool: AsyncPsycopgPool,
        *,
        retry_policy: TransactionRetryPolicy = DEFAULT_TRANSACTION_RETRY_POLICY,
    ) -> None:
        if pool.component_schema != "orchestrator":
            raise ValueError("PsycopgOrchestratorPersistence requires an orchestrator pool")
        self._pool = pool
        self.transaction_retry_policy = retry_policy

    async def resolve(self, key: AcceptedRequestKey) -> AcceptedRequestResolution | None:
        async with self._pool.connection() as connection:
            return await select_accepted_request(connection, key)

    async def get(self, workflow_id: WorkflowId) -> Workflow | None:
        async with self._pool.connection() as connection:
            return await select_workflow(connection, workflow_id)

    async def get_authorized(
        self,
        workflow_id: WorkflowId,
        *,
        environment: str,
        current_owner_subject_id: OwnerSubjectId,
    ) -> Workflow | None:
        async with self._pool.connection() as connection:
            allowed = await (
                await connection.execute(
                    """
                    SELECT 1 FROM orchestrator.accepted_requests
                    WHERE workflow_id = %s AND environment = %s
                      AND current_owner_subject_id = %s
                    """,
                    (workflow_id, environment, current_owner_subject_id),
                )
            ).fetchone()
            if allowed is None:
                return None
            return await select_workflow(connection, workflow_id)

    @retry_transaction
    async def record_request_access(self, record: AcceptedRequestAccessAuditRecord) -> None:
        async with self._pool.transaction() as connection:
            await connection.execute(
                """
                INSERT INTO orchestrator.request_access_audit (
                    environment, operation, idempotency_scope_id, request_id, workflow_id,
                    current_actor_id, resolved_owner_subject_id, effective_correlation_id,
                    policy_identity, policy_revision, policy_decision,
                    scope_mapping_revision, authorization_evidence, disposition, occurred_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    record.key.environment,
                    record.key.operation,
                    record.key.idempotency_scope_id,
                    record.key.request_id,
                    record.workflow_id,
                    record.current_actor_id,
                    record.resolved_owner_subject_id,
                    record.effective_correlation_id,
                    record.policy_identity,
                    record.policy_revision,
                    record.policy_decision,
                    record.scope_mapping_revision,
                    record.authorization_evidence,
                    record.disposition.value,
                    record.occurred_at,
                ),
            )

    @retry_transaction
    async def commit_submission(self, intent: SubmissionCommitIntent) -> SubmissionCommitResult:
        async with self._pool.transaction() as connection:
            resolution = await insert_accepted_request(
                connection, intent.key, intent.evidence, intent.workflow.workflow_id
            )
            if resolution is None:
                resolution = await select_accepted_request(connection, intent.key)
                if resolution is None:
                    raise PermanentPersistenceError(
                        "Accepted-request arbitration returned no durable winner."
                    )
                workflow = await select_workflow(connection, resolution.workflow_id)
                if workflow is None:
                    raise PermanentPersistenceError(
                        "Accepted-request winner does not reference a durable workflow."
                    )
                return SubmissionCommitResult(
                    resolution=resolution, workflow=workflow, created=False
                )

            await insert_workflow(
                connection,
                intent.workflow,
                task_id=intent.task.task_id,
                task_attempt_id=intent.task_attempt.task_attempt_id,
                actor_id=str(intent.audit.actor_id),
            )
            await insert_task_and_attempt(connection, intent.task, intent.task_attempt)
            await insert_outbox(connection, intent.command_outbox, schema="orchestrator")
            await insert_audit(connection, intent.audit, schema="orchestrator")
            return SubmissionCommitResult(
                resolution=resolution, workflow=intent.workflow, created=True
            )

    @retry_transaction
    async def apply_terminal_outcome(
        self, intent: TerminalOutcomeIntent
    ) -> TerminalOutcomeCommitResult:
        async with self._pool.transaction() as connection:
            workflow = await select_workflow(connection, intent.workflow_id, for_update=True)
            existing = await self._select_inbox(
                connection,
                intent.environment,
                intent.logical_consumer_id,
                str(intent.validated_message_id),
            )
            if existing is not None:
                if not self._same_inbox_identity(existing, intent):
                    return TerminalOutcomeCommitResult(
                        disposition=TerminalPersistenceDisposition.PERMANENT_CONFLICT,
                        workflow=workflow,
                    )
                return TerminalOutcomeCommitResult(
                    disposition=TerminalPersistenceDisposition.DUPLICATE, workflow=workflow
                )

            if workflow is None:
                await self._insert_inbox(connection, intent, "permanent_conflict")
                await insert_audit(connection, intent.audit, schema="orchestrator")
                return TerminalOutcomeCommitResult(
                    disposition=TerminalPersistenceDisposition.PERMANENT_CONFLICT,
                    workflow=None,
                )

            if workflow.correlation_id != intent.correlation_id or not await self._matches_attempt(
                connection, intent
            ):
                await self._insert_inbox(connection, intent, "permanent_conflict")
                await insert_audit(connection, intent.audit, schema="orchestrator")
                return TerminalOutcomeCommitResult(
                    disposition=TerminalPersistenceDisposition.PERMANENT_CONFLICT,
                    workflow=workflow,
                )

            if workflow.is_terminal:
                await self._insert_inbox(connection, intent, "late_after_terminal")
                await insert_audit(connection, intent.audit, schema="orchestrator")
                return TerminalOutcomeCommitResult(
                    disposition=TerminalPersistenceDisposition.LATE_AFTER_TERMINAL,
                    workflow=workflow,
                )

            if workflow.state != WorkflowState.DISPATCHED:
                await self._insert_inbox(connection, intent, "permanent_conflict")
                await insert_audit(connection, intent.audit, schema="orchestrator")
                return TerminalOutcomeCommitResult(
                    disposition=TerminalPersistenceDisposition.PERMANENT_CONFLICT,
                    workflow=workflow,
                )

            expected_revision = workflow.revision
            if intent.outcome.word_count is not None:
                workflow.complete(
                    WorkflowResult(word_count=intent.outcome.word_count),
                    occurred_at=intent.occurred_at,
                )
                state = "COMPLETED"
            else:
                workflow.fail(
                    WorkflowFailure(
                        code=intent.outcome.failure_code or "TASK_EXECUTION_FAILED",
                        detail=intent.outcome.summary or "",
                    ),
                    occurred_at=intent.occurred_at,
                )
                state = "FAILED"
            await update_task_outcome(
                connection,
                task_id=str(intent.task_id),
                task_attempt_id=str(intent.task_attempt_id),
                state=state,
                word_count=intent.outcome.word_count,
                failure_code=intent.outcome.failure_code,
                failure_detail=intent.outcome.summary,
                completed_at=intent.outcome.completed_at,
            )
            await update_workflow(
                connection,
                workflow,
                expected_revision=expected_revision,
                task_id=intent.task_id,
                task_attempt_id=intent.task_attempt_id,
                causing_message_id=intent.validated_message_id,
                audit=intent.audit,
            )
            await self._insert_inbox(connection, intent, state.lower())
            await insert_audit(connection, intent.audit, schema="orchestrator")
            return TerminalOutcomeCommitResult(
                disposition=TerminalPersistenceDisposition.APPLIED, workflow=workflow
            )

    async def find_expired(self, *, now: datetime, limit: int) -> tuple[ExpiredAttempt, ...]:
        if limit < 1:
            raise ValueError("limit must be positive")
        async with self._pool.connection() as connection:
            rows = await (
                await connection.execute(
                    """
                    SELECT t.workflow_id, a.task_attempt_id
                    FROM orchestrator.task_attempts a
                    JOIN orchestrator.tasks t ON t.task_id = a.task_id
                    JOIN orchestrator.workflows w ON w.workflow_id = t.workflow_id
                    WHERE a.state = 'DISPATCHED' AND w.state = 'DISPATCHED'
                      AND a.task_result_deadline <= %s
                    ORDER BY a.task_result_deadline, a.task_attempt_id
                    LIMIT %s
                    """,
                    (now, limit),
                )
            ).fetchall()
        return tuple(
            ExpiredAttempt(
                workflow_id=WorkflowId(str(row[0])), task_attempt_id=TaskAttemptId(str(row[1]))
            )
            for row in rows
        )

    @retry_transaction
    async def expire(
        self, candidate: ExpiredAttempt, *, now: datetime, audit: AuditRecord
    ) -> DeadlinePersistenceDisposition:
        async with self._pool.transaction() as connection:
            workflow = await select_workflow(connection, candidate.workflow_id, for_update=True)
            if workflow is None or workflow.is_terminal:
                return DeadlinePersistenceDisposition.ALREADY_TERMINAL
            row = await (
                await connection.execute(
                    """
                    SELECT t.task_id, a.task_result_deadline
                    FROM orchestrator.task_attempts a
                    JOIN orchestrator.tasks t ON t.task_id = a.task_id
                    WHERE t.workflow_id = %s AND a.task_attempt_id = %s
                    FOR UPDATE OF a
                    """,
                    (candidate.workflow_id, candidate.task_attempt_id),
                )
            ).fetchone()
            if row is None or workflow.state != WorkflowState.DISPATCHED:
                return DeadlinePersistenceDisposition.ALREADY_TERMINAL
            if not isinstance(row[1], datetime):
                raise PermanentPersistenceError("Stored task result deadline is invalid.")
            if row[1] > now:
                return DeadlinePersistenceDisposition.NOT_DUE
            expected_revision = workflow.revision
            workflow.fail(
                WorkflowFailure(
                    code="TASK_RESULT_DEADLINE_EXCEEDED",
                    detail="No terminal outcome was received before the task result deadline.",
                ),
                occurred_at=now,
                cause="deadline_expired",
            )
            await update_task_outcome(
                connection,
                task_id=str(row[0]),
                task_attempt_id=str(candidate.task_attempt_id),
                state="FAILED",
                word_count=None,
                failure_code="TASK_RESULT_DEADLINE_EXCEEDED",
                failure_detail="No terminal outcome was received before the task result deadline.",
                completed_at=now,
            )
            await update_workflow(
                connection,
                workflow,
                expected_revision=expected_revision,
                task_id=TaskId(str(row[0])),
                task_attempt_id=candidate.task_attempt_id,
                causing_message_id=None,
                audit=audit,
            )
            await connection.execute(
                """
                UPDATE orchestrator.outbox
                SET publication_state = 'FAILED',
                    safe_failure_code = 'DEADLINE_EXPIRED_BEFORE_PUBLICATION'
                WHERE workflow_id = %s
                  AND publication_state IN ('NOT_ATTEMPTED', 'DEFINITIVELY_NOT_ACCEPTED')
                """,
                (candidate.workflow_id,),
            )
            await insert_audit(connection, audit, schema="orchestrator")
            return DeadlinePersistenceDisposition.APPLIED

    @staticmethod
    async def _select_inbox(
        connection: AsyncDbConnection, environment: str, consumer: str, message_id: str
    ) -> tuple[object, ...] | None:
        return await (
            await connection.execute(
                """
                SELECT immutable_message_digest, workflow_id, task_attempt_id, disposition
                FROM orchestrator.inbox
                WHERE environment = %s AND logical_consumer_id = %s
                  AND validated_message_id = %s
                """,
                (environment, consumer, message_id),
            )
        ).fetchone()

    @staticmethod
    def _same_inbox_identity(row: tuple[object, ...], intent: TerminalOutcomeIntent) -> bool:
        return (
            len(row) == 4
            and str(row[0]) == intent.immutable_message_digest
            and str(row[1]) == str(intent.workflow_id)
            and str(row[2]) == str(intent.task_attempt_id)
        )

    @staticmethod
    async def _insert_inbox(
        connection: AsyncDbConnection, intent: TerminalOutcomeIntent, disposition: str
    ) -> None:
        await connection.execute(
            """
            INSERT INTO orchestrator.inbox (
                environment, logical_consumer_id, validated_message_id,
                immutable_message_digest, workflow_id, task_attempt_id,
                disposition, recorded_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                intent.environment,
                intent.logical_consumer_id,
                intent.validated_message_id,
                intent.immutable_message_digest,
                intent.workflow_id,
                intent.task_attempt_id,
                disposition,
                intent.occurred_at,
            ),
        )

    @staticmethod
    async def _matches_attempt(
        connection: AsyncDbConnection, intent: TerminalOutcomeIntent
    ) -> bool:
        if intent.outcome.task_attempt_id != intent.task_attempt_id:
            return False
        row = await (
            await connection.execute(
                """
                SELECT a.implementation_identity, a.agent_id,
                       a.capability_name, a.capability_version,
                       o.message_id, o.payload_bytes
                FROM orchestrator.tasks t
                JOIN orchestrator.task_attempts a ON a.task_id = t.task_id
                JOIN orchestrator.outbox o ON o.workflow_id = t.workflow_id
                WHERE t.workflow_id = %s AND t.task_id = %s AND a.task_attempt_id = %s
                  AND o.logical_channel = 'task-commands'
                """,
                (intent.workflow_id, intent.task_id, intent.task_attempt_id),
            )
        ).fetchone()
        if (
            row is None
            or len(row) != 6
            or not isinstance(row[5], bytes | bytearray)
            or str(row[0]) != intent.producer_component
            or str(row[1]) != intent.producer_instance_id
            or str(row[2]) != intent.capability_name
            or str(row[3]) != intent.capability_version
            or str(row[4]) != str(intent.causation_message_id)
        ):
            return False
        if (
            intent.agent_evidence_component is not None
            and intent.agent_evidence_component != str(row[0])
        ) or (
            intent.agent_evidence_instance_id is not None
            and intent.agent_evidence_instance_id != str(row[1])
        ):
            return False
        if intent.outcome.word_count is None:
            return intent.result_text is None
        if intent.result_text is None:
            return False
        try:
            command: object = json.loads(bytes(row[5]))
        except UnicodeDecodeError, json.JSONDecodeError:
            raise PermanentPersistenceError("Stored command payload is invalid.") from None
        if not isinstance(command, Mapping):
            raise PermanentPersistenceError("Stored command payload is invalid.")
        command_data = cast(Mapping[str, object], command)
        payload = command_data.get("payload")
        if not isinstance(payload, Mapping):
            raise PermanentPersistenceError("Stored command payload is invalid.")
        payload_data = cast(Mapping[str, object], payload)
        return payload_data.get("input") == intent.result_text
