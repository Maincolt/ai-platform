"""Internal async SQL helpers for tasks and attempts."""

from psycopg.types.json import Jsonb

from ai_platform.adapters.persistence.connection import AsyncDbConnection
from ai_platform.orchestrator.domain.task import Task, TaskAttempt


async def insert_task_and_attempt(
    connection: AsyncDbConnection, task: Task, attempt: TaskAttempt
) -> None:
    await connection.execute(
        """
        INSERT INTO orchestrator.tasks
            (task_id, workflow_id, state, created_at, updated_at)
        VALUES (%s, %s, 'DISPATCHED', %s, %s)
        """,
        (task.task_id, task.workflow_id, task.created_at, task.created_at),
    )
    selection = attempt.selection
    await connection.execute(
        """
        INSERT INTO orchestrator.task_attempts (
            task_attempt_id, task_id, attempt_number, state, agent_id,
            capability_name, capability_version, implementation_identity,
            implementation_version, command_contract_version, event_contract_versions,
            registry_revision, deployment_declaration_digest, selection_policy_version,
            availability_classification, observed_at, selected_at, task_result_deadline
        ) VALUES (%s, %s, %s, 'DISPATCHED', %s, %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            attempt.task_attempt_id,
            attempt.task_id,
            attempt.attempt_number,
            selection.agent_id,
            selection.capability_name,
            selection.capability_version,
            selection.implementation_identity,
            selection.implementation_version,
            selection.command_contract_version,
            Jsonb(list(selection.event_contract_versions)),
            selection.registry_revision,
            selection.deployment_declaration_digest,
            selection.selection_policy_version,
            selection.availability_classification,
            selection.observed_at,
            selection.selected_at,
            attempt.task_result_deadline,
        ),
    )


async def update_task_outcome(
    connection: AsyncDbConnection,
    *,
    task_id: str,
    task_attempt_id: str,
    state: str,
    result_data: dict[str, object] | None,
    failure_code: str | None,
    failure_detail: str | None,
    completed_at: object,
) -> None:
    result_json = None if result_data is None else Jsonb(result_data)
    await connection.execute(
        """
        UPDATE orchestrator.tasks
        SET state = %s, result_data = %s, failure_code = %s,
            failure_detail = %s, updated_at = %s
        WHERE task_id = %s
        """,
        (state, result_json, failure_code, failure_detail, completed_at, task_id),
    )
    await connection.execute(
        """
        UPDATE orchestrator.task_attempts
        SET state = %s, result_data = %s, failure_code = %s,
            failure_detail = %s, completed_at = %s
        WHERE task_attempt_id = %s
        """,
        (state, result_json, failure_code, failure_detail, completed_at, task_attempt_id),
    )
