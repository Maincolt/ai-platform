"""Shared asynchronous SQL for fenced Orchestrator and Agent outboxes."""

from datetime import datetime, timedelta

from psycopg import sql
from psycopg.types.json import Jsonb

from ai_platform.adapters.persistence._serialization import decode_headers, encode_headers
from ai_platform.adapters.persistence.connection import AsyncDbConnection
from ai_platform.agents.domain.outcomes import AgentEventOutboxRecord
from ai_platform.orchestrator.domain.recovery import OrchestratorOutboxRecord
from ai_platform.ports.persistence.errors import PermanentPersistenceError, PersistenceConflictError
from ai_platform.ports.persistence.outbox import ClaimedOutboxRecord, PublicationDisposition
from ai_platform.shared.identifiers import MessageId, WorkflowId
from ai_platform.shared.recovery import PublicationState

_TABLES = {"orchestrator": ("orchestrator", "outbox"), "agent": ("agent", "event_outbox")}


def table_for(schema: str) -> sql.Identifier:
    try:
        return sql.Identifier(*_TABLES[schema])
    except KeyError as exc:
        raise ValueError("schema must be orchestrator or agent") from exc


async def insert_outbox(
    connection: AsyncDbConnection,
    record: OrchestratorOutboxRecord | AgentEventOutboxRecord,
    *,
    schema: str,
    task_attempt_id: str | None = None,
) -> None:
    table = table_for(schema)
    params: tuple[object, ...] = (
        record.message_id,
        record.workflow_id,
        record.logical_channel,
        record.ordering_key,
        record.payload_bytes,
        Jsonb(encode_headers(record.headers)),
        record.creation_sequence,
        record.created_at,
        record.capability_name,
    )
    if schema == "agent":
        if task_attempt_id is None:
            raise ValueError("task_attempt_id is required for the Agent outbox")
        query = sql.SQL("""
            INSERT INTO {} (
                message_id, workflow_id, logical_channel, ordering_key, payload_bytes,
                headers, creation_sequence, created_at, capability_name, task_attempt_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """).format(table)
        await connection.execute(
            query,
            (*params, task_attempt_id),
        )
    else:
        query = sql.SQL("""
            INSERT INTO {} (
                message_id, workflow_id, logical_channel, ordering_key, payload_bytes,
                headers, creation_sequence, created_at, capability_name
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """).format(table)
        await connection.execute(
            query,
            params,
        )


async def claim_next(
    connection: AsyncDbConnection,
    *,
    schema: str,
    logical_channel: str,
    publisher_instance_id: str,
    fencing_token: str,
    claim_ttl: timedelta,
    max_publication_attempts: int = 3,
) -> ClaimedOutboxRecord | None:
    if max_publication_attempts < 1:
        raise ValueError("max_publication_attempts must be positive")
    table = table_for(schema)
    await connection.execute(
        sql.SQL("""
        UPDATE {table}
        SET publication_state = 'ATTEMPTED_UNKNOWN',
            automatic_retry_allowed = (
                automatic_retry_allowed AND publication_attempts < %s
            ),
            claim_previous_state = NULL, publisher_instance_id = NULL,
            claim_token = NULL, claim_expires_at = NULL
        WHERE logical_channel = %s AND publication_state = 'CLAIMED'
          AND claim_expires_at <= CURRENT_TIMESTAMP
        """).format(table=table),
        (max_publication_attempts, logical_channel),
    )
    row = await (
        await connection.execute(
            sql.SQL("""
            WITH candidate AS (
                SELECT current.message_id
                FROM {table} AS current
                WHERE current.logical_channel = %s
                  AND current.automatic_retry_allowed
                  AND current.publication_state IN (
                      'NOT_ATTEMPTED', 'DEFINITIVELY_NOT_ACCEPTED',
                      'ATTEMPTED_UNKNOWN'
                  )
                  AND current.publication_attempts < %s
                  AND NOT EXISTS (
                      SELECT 1 FROM {table} AS earlier
                      WHERE earlier.logical_channel = current.logical_channel
                        AND earlier.workflow_id = current.workflow_id
                        AND earlier.creation_sequence < current.creation_sequence
                        AND earlier.publication_state <> 'ACKNOWLEDGED'
                  )
                ORDER BY current.created_at, current.message_id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE {table} AS claimed
            SET claim_previous_state = claimed.publication_state,
                publication_state = 'CLAIMED', publisher_instance_id = %s,
                claim_token = %s, claim_expires_at = CURRENT_TIMESTAMP + %s,
                publication_attempts = claimed.publication_attempts + 1
            FROM candidate
            WHERE claimed.message_id = candidate.message_id
            RETURNING claimed.message_id, claimed.workflow_id, claimed.logical_channel,
                      claimed.ordering_key, claimed.payload_bytes, claimed.headers,
                      claimed.creation_sequence, claimed.created_at,
                      claimed.claim_expires_at, claimed.publication_attempts,
                      claimed.capability_name
            """).format(table=table),
            (
                logical_channel,
                max_publication_attempts,
                publisher_instance_id,
                fencing_token,
                claim_ttl,
            ),
        )
    ).fetchone()
    if row is None:
        return None
    return claimed_from_row(row, fencing_token=fencing_token, schema=schema)


async def record_publication_result(
    connection: AsyncDbConnection,
    *,
    schema: str,
    message_id: MessageId,
    disposition: PublicationDisposition,
    fencing_token: str,
) -> None:
    if disposition.state in {PublicationState.NOT_ATTEMPTED, PublicationState.CLAIMED}:
        raise ValueError("publication result must be a terminal attempt disposition")
    table = table_for(schema)
    query = sql.SQL("""
        UPDATE {}
        SET publication_state = %s, last_attempted_at = %s, safe_failure_code = %s,
            automatic_retry_allowed = %s,
            claim_previous_state = NULL, publisher_instance_id = NULL,
            claim_token = NULL, claim_expires_at = NULL
        WHERE message_id = %s AND publication_state = 'CLAIMED' AND claim_token = %s
        """).format(table)
    result = await connection.execute(
        query,
        (
            disposition.state.value,
            disposition.attempted_at,
            disposition.safe_failure_code,
            disposition.retryable,
            message_id,
            fencing_token,
        ),
    )
    if result.rowcount != 1:
        raise PersistenceConflictError("The outbox claim is stale or no longer owned.")


async def release_claim(
    connection: AsyncDbConnection, *, schema: str, message_id: MessageId, fencing_token: str
) -> None:
    table = table_for(schema)
    query = sql.SQL("""
        UPDATE {}
        SET publication_state = claim_previous_state, claim_previous_state = NULL,
            publisher_instance_id = NULL, claim_token = NULL, claim_expires_at = NULL,
            publication_attempts = publication_attempts - 1
        WHERE message_id = %s AND publication_state = 'CLAIMED'
          AND claim_token = %s AND claim_previous_state IS NOT NULL
        """).format(table)
    result = await connection.execute(
        query,
        (message_id, fencing_token),
    )
    if result.rowcount != 1:
        raise PersistenceConflictError("The outbox claim is stale or no longer owned.")


def claimed_from_row(
    row: tuple[object, ...], *, fencing_token: str, schema: str
) -> ClaimedOutboxRecord:
    if (
        len(row) != 11
        or not isinstance(row[4], bytes | bytearray)
        or not isinstance(row[7], datetime)
        or not isinstance(row[8], datetime)
        or not isinstance(row[9], int)
        or (row[10] is not None and not isinstance(row[10], str))
    ):
        raise PermanentPersistenceError("Stored outbox data is invalid.")
    message_id = MessageId(str(row[0]))
    workflow_id = WorkflowId(str(row[1]))
    logical_channel = str(row[2])
    ordering_key = str(row[3])
    payload_bytes = bytes(row[4])
    headers = decode_headers(row[5])
    creation_sequence = _positive_int(row[6])
    created_at = row[7]
    capability_name = None if row[10] is None else str(row[10])
    record = (
        OrchestratorOutboxRecord(
            message_id=message_id,
            workflow_id=workflow_id,
            logical_channel=logical_channel,
            ordering_key=ordering_key,
            payload_bytes=payload_bytes,
            headers=headers,
            creation_sequence=creation_sequence,
            created_at=created_at,
            capability_name=capability_name,
        )
        if schema == "orchestrator"
        else AgentEventOutboxRecord(
            message_id=message_id,
            workflow_id=workflow_id,
            logical_channel=logical_channel,
            ordering_key=ordering_key,
            payload_bytes=payload_bytes,
            headers=headers,
            creation_sequence=creation_sequence,
            created_at=created_at,
            capability_name=capability_name,
        )
    )
    return ClaimedOutboxRecord(
        record=record,
        fencing_token=fencing_token,
        claim_expires_at=row[8],
        publication_attempts=row[9],
    )


def _positive_int(value: object) -> int:
    if not isinstance(value, int) or value < 1:
        raise PermanentPersistenceError("Stored creation sequence is invalid.")
    return value
