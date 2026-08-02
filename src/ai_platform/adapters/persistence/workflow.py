"""Internal async SQL helpers for workflow snapshots and transition history."""

from datetime import datetime

from ai_platform.adapters.persistence.connection import AsyncDbConnection
from ai_platform.orchestrator.domain.audit import AuditRecord
from ai_platform.orchestrator.domain.history import TransitionRecord
from ai_platform.orchestrator.domain.results import WorkflowFailure, WorkflowResult
from ai_platform.orchestrator.domain.states import WorkflowState
from ai_platform.orchestrator.domain.workflow import Workflow
from ai_platform.ports.persistence.errors import PermanentPersistenceError, PersistenceConflictError
from ai_platform.shared.identifiers import (
    CorrelationId,
    MessageId,
    RequestId,
    TaskAttemptId,
    TaskId,
    WorkflowId,
)


async def select_workflow(
    connection: AsyncDbConnection, workflow_id: WorkflowId, *, for_update: bool = False
) -> Workflow | None:
    lock = " FOR UPDATE" if for_update else ""
    row = await (
        await connection.execute(
            """
            SELECT workflow_id, request_id, correlation_id, state, revision,
                   result_word_count, failure_code, failure_detail
            FROM orchestrator.workflows WHERE workflow_id = %s
            """
            + lock,
            (workflow_id,),
        )
    ).fetchone()
    if row is None:
        return None
    history_rows = await (
        await connection.execute(
            """
            SELECT from_state, to_state, revision, occurred_at, cause
            FROM orchestrator.workflow_history
            WHERE workflow_id = %s ORDER BY revision
            """,
            (workflow_id,),
        )
    ).fetchall()
    return workflow_from_rows(row, history_rows)


async def insert_workflow(
    connection: AsyncDbConnection,
    workflow: Workflow,
    *,
    task_id: TaskId,
    task_attempt_id: TaskAttemptId,
    actor_id: str,
) -> None:
    if not workflow.history or workflow.state is None:
        raise PermanentPersistenceError("A new workflow must contain transition history.")
    await connection.execute(
        """
        INSERT INTO orchestrator.workflows (
            workflow_id, request_id, correlation_id, state, revision,
            result_word_count, failure_code, failure_detail, created_at, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            workflow.workflow_id,
            workflow.request_id,
            workflow.correlation_id,
            workflow.state.value,
            workflow.revision,
            workflow.result.word_count if workflow.result else None,
            workflow.failure.code if workflow.failure else None,
            workflow.failure.detail if workflow.failure else None,
            workflow.history[0].occurred_at,
            workflow.history[-1].occurred_at,
        ),
    )
    for record in workflow.history:
        await insert_transition(
            connection,
            workflow,
            record,
            task_id=task_id,
            task_attempt_id=task_attempt_id,
            causing_message_id=None,
            actor_id=actor_id,
        )


async def update_workflow(
    connection: AsyncDbConnection,
    workflow: Workflow,
    *,
    expected_revision: int,
    task_id: TaskId,
    task_attempt_id: TaskAttemptId,
    causing_message_id: MessageId | None,
    audit: AuditRecord,
) -> None:
    if workflow.state is None or not workflow.history:
        raise PermanentPersistenceError("A persisted workflow state is required.")
    latest = workflow.history[-1]
    result = await connection.execute(
        """
        UPDATE orchestrator.workflows
        SET state = %s, revision = %s, result_word_count = %s,
            failure_code = %s, failure_detail = %s, updated_at = %s
        WHERE workflow_id = %s AND revision = %s
        """,
        (
            workflow.state.value,
            workflow.revision,
            workflow.result.word_count if workflow.result else None,
            workflow.failure.code if workflow.failure else None,
            workflow.failure.detail if workflow.failure else None,
            latest.occurred_at,
            workflow.workflow_id,
            expected_revision,
        ),
    )
    if result.rowcount != 1:
        raise PersistenceConflictError("The workflow revision changed concurrently.")
    await insert_transition(
        connection,
        workflow,
        latest,
        task_id=task_id,
        task_attempt_id=task_attempt_id,
        causing_message_id=causing_message_id,
        actor_id=str(audit.actor_id),
    )


async def insert_transition(
    connection: AsyncDbConnection,
    workflow: Workflow,
    record: TransitionRecord,
    *,
    task_id: TaskId,
    task_attempt_id: TaskAttemptId,
    causing_message_id: MessageId | None,
    actor_id: str,
) -> None:
    await connection.execute(
        """
        INSERT INTO orchestrator.workflow_history (
            workflow_id, revision, from_state, to_state, occurred_at, cause,
            request_id, correlation_id, task_id, task_attempt_id,
            causing_message_id, actor_id, failure_code
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            workflow.workflow_id,
            record.revision,
            record.from_state.value if record.from_state else None,
            record.to_state.value,
            record.occurred_at,
            record.cause,
            workflow.request_id,
            workflow.correlation_id,
            task_id,
            task_attempt_id,
            causing_message_id,
            actor_id,
            workflow.failure.code if workflow.failure else None,
        ),
    )


def workflow_from_rows(row: tuple[object, ...], history_rows: list[tuple[object, ...]]) -> Workflow:
    if len(row) != 8:
        raise PermanentPersistenceError("Stored workflow data is invalid.")
    workflow = Workflow(
        workflow_id=WorkflowId(str(row[0])),
        request_id=RequestId(str(row[1])),
        correlation_id=CorrelationId(str(row[2])),
        state=WorkflowState(str(row[3])),
        revision=_int(row[4]),
    )
    if row[5] is not None:
        workflow.result = WorkflowResult(word_count=_int(row[5]))
    if row[6] is not None:
        workflow.failure = WorkflowFailure(code=str(row[6]), detail=str(row[7] or ""))
    workflow.history = []
    for history in history_rows:
        if len(history) != 5 or not isinstance(history[3], datetime):
            raise PermanentPersistenceError("Stored transition history is invalid.")
        workflow.history.append(
            TransitionRecord(
                workflow_id=workflow.workflow_id,
                from_state=WorkflowState(str(history[0])) if history[0] is not None else None,
                to_state=WorkflowState(str(history[1])),
                revision=_int(history[2]),
                occurred_at=history[3],
                cause=str(history[4]),
            )
        )
    return workflow


def _int(value: object) -> int:
    if not isinstance(value, int):
        raise PermanentPersistenceError("Stored numeric data is invalid.")
    return value
