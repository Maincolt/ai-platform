"""Internal async SQL helper for coupled audit records."""

from psycopg import sql
from psycopg.types.json import Jsonb

from ai_platform.adapters.persistence.connection import AsyncDbConnection
from ai_platform.orchestrator.domain.audit import AuditRecord


async def insert_audit(connection: AsyncDbConnection, record: AuditRecord, *, schema: str) -> None:
    if schema not in {"orchestrator", "agent"}:
        raise ValueError("schema must be orchestrator or agent")
    query = sql.SQL(
        "INSERT INTO {}.audit (kind, workflow_id, occurred_at, actor_id, details) "
        "VALUES (%s, %s, %s, %s, %s)"
    ).format(sql.Identifier(schema))
    await connection.execute(
        query,
        (
            record.kind,
            record.workflow_id,
            record.occurred_at,
            record.actor_id,
            Jsonb(dict(record.details)),
        ),
    )
