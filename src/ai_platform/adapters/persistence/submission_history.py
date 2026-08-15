"""Internal async SQL helpers for submission history (ADR-0024).

An additive record of what was submitted (capability, input text, when),
joined against `orchestrator.workflows` at read time for current
state/result -- never a separate copy of mutable workflow state.
"""

from datetime import datetime
from typing import cast

from ai_platform.adapters.persistence.connection import AsyncDbConnection
from ai_platform.orchestrator.domain.states import WorkflowState
from ai_platform.orchestrator.domain.workflow import Workflow
from ai_platform.ports.persistence.errors import PermanentPersistenceError
from ai_platform.ports.persistence.transactions import SubmissionHistoryEntry
from ai_platform.shared.identifiers import CorrelationId, RequestId, WorkflowId


async def insert_submission_history(
    connection: AsyncDbConnection,
    workflow: Workflow,
    *,
    capability_name: str,
    capability_version: str,
    input_text: str,
    submitted_at: datetime,
) -> None:
    await connection.execute(
        """
        INSERT INTO orchestrator.submission_history (
            workflow_id, capability_name, capability_version, input_text, submitted_at
        ) VALUES (%s, %s, %s, %s, %s)
        """,
        (
            workflow.workflow_id,
            capability_name,
            capability_version,
            input_text,
            submitted_at,
        ),
    )


async def select_submission_history(
    connection: AsyncDbConnection,
    *,
    capability_name: str | None,
    limit: int,
    before: datetime | None,
) -> list[SubmissionHistoryEntry]:
    # Both filters are always-present placeholders (`%s IS NULL OR ...`)
    # rather than a dynamically assembled WHERE clause, so the query text
    # itself stays a fixed literal -- matching this codebase's psycopg
    # convention of never building SQL by string interpolation.
    rows = await (
        await connection.execute(
            """
            SELECT sh.workflow_id, sh.capability_name, sh.capability_version,
                   sh.input_text, sh.submitted_at,
                   w.request_id, w.correlation_id, w.state,
                   w.result_data, w.failure_code, w.failure_detail
            FROM orchestrator.submission_history sh
            JOIN orchestrator.workflows w ON w.workflow_id = sh.workflow_id
            WHERE (%s::text IS NULL OR sh.capability_name = %s)
              AND (%s::timestamptz IS NULL OR sh.submitted_at < %s)
            ORDER BY sh.submitted_at DESC
            LIMIT %s
            """,
            (capability_name, capability_name, before, before, limit),
        )
    ).fetchall()
    return [_entry_from_row(row) for row in rows]


def _entry_from_row(row: tuple[object, ...]) -> SubmissionHistoryEntry:
    if len(row) != 11:
        raise PermanentPersistenceError("Stored submission history data is invalid.")
    result_data = row[8]
    if result_data is not None and not isinstance(result_data, dict):
        raise PermanentPersistenceError("Stored submission history result data is invalid.")
    return SubmissionHistoryEntry(
        workflow_id=WorkflowId(str(row[0])),
        capability_name=str(row[1]),
        capability_version=str(row[2]),
        input_text=str(row[3]),
        submitted_at=_datetime(row[4]),
        request_id=RequestId(str(row[5])),
        correlation_id=CorrelationId(str(row[6])),
        state=WorkflowState(str(row[7])),
        result_data=cast(dict[str, object] | None, result_data),
        failure_code=str(row[9]) if row[9] is not None else None,
        failure_detail=str(row[10]) if row[10] is not None else None,
    )


def _datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise PermanentPersistenceError("Stored submission history timestamp is invalid.")
    return value
