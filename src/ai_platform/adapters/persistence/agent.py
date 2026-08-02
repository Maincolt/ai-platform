"""Async Psycopg adapter for the Agent outcome integrity unit."""

from datetime import datetime

from psycopg.types.json import Jsonb

from ai_platform.adapters.persistence._outbox_common import insert_outbox
from ai_platform.adapters.persistence._serialization import decode_headers, encode_headers
from ai_platform.adapters.persistence.audit import insert_audit
from ai_platform.adapters.persistence.connection import AsyncDbConnection, AsyncPsycopgPool
from ai_platform.adapters.persistence.retry import (
    DEFAULT_TRANSACTION_RETRY_POLICY,
    TransactionRetryPolicy,
    retry_transaction,
)
from ai_platform.agents.domain.outcomes import AgentCompletedReceipt, AgentEventOutboxRecord
from ai_platform.ports.persistence.errors import PermanentPersistenceError
from ai_platform.ports.persistence.transactions import (
    AgentOutcomeCommitIntent,
    AgentOutcomeCommitResult,
    CompletedAgentWork,
)
from ai_platform.shared.identifiers import AgentId, MessageId, TaskAttemptId, WorkflowId
from ai_platform.shared.outcomes import AgentOutcome


class PsycopgAgentPersistence:
    def __init__(
        self,
        pool: AsyncPsycopgPool,
        *,
        retry_policy: TransactionRetryPolicy = DEFAULT_TRANSACTION_RETRY_POLICY,
    ) -> None:
        if pool.component_schema != "agent":
            raise ValueError("PsycopgAgentPersistence requires an agent pool")
        self._pool = pool
        self.transaction_retry_policy = retry_policy

    async def get_completed(self, task_attempt_id: TaskAttemptId) -> CompletedAgentWork | None:
        async with self._pool.connection() as connection:
            return await self._select_completed(connection, task_attempt_id)

    @retry_transaction
    async def commit_outcome(self, intent: AgentOutcomeCommitIntent) -> AgentOutcomeCommitResult:
        work = intent.completed_work
        if (
            work.receipt.task_attempt_id != work.outcome.task_attempt_id
            or work.receipt.terminal_event_message_id != work.event_outbox.message_id
        ):
            raise PermanentPersistenceError(
                "Agent outcome intent contains inconsistent immutable identities."
            )
        async with self._pool.transaction() as connection:
            event = work.event_outbox
            inserted = await (
                await connection.execute(
                    """
                    INSERT INTO agent.terminal_events (
                        message_id, task_attempt_id, workflow_id, logical_channel,
                        ordering_key, payload_bytes, headers, creation_sequence, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (task_attempt_id) DO NOTHING
                    RETURNING message_id
                    """,
                    (
                        event.message_id,
                        work.receipt.task_attempt_id,
                        event.workflow_id,
                        event.logical_channel,
                        event.ordering_key,
                        event.payload_bytes,
                        Jsonb(encode_headers(event.headers)),
                        event.creation_sequence,
                        event.created_at,
                    ),
                )
            ).fetchone()
            if inserted is None:
                winner = await self._select_completed(connection, work.receipt.task_attempt_id)
                if winner is None:
                    raise PermanentPersistenceError(
                        "Agent outcome arbitration returned no complete durable winner."
                    )
                return AgentOutcomeCommitResult(completed_work=winner, created=False)

            await connection.execute(
                """
                INSERT INTO agent.completed_receipts (
                    environment, agent_deployment_id, task_attempt_id,
                    command_message_id, command_digest, terminal_event_message_id, completed_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    work.receipt.environment,
                    work.receipt.agent_deployment_id,
                    work.receipt.task_attempt_id,
                    work.receipt.command_message_id,
                    work.receipt.command_digest,
                    work.receipt.terminal_event_message_id,
                    work.receipt.completed_at,
                ),
            )
            await connection.execute(
                """
                INSERT INTO agent.outcomes (
                    task_attempt_id, completed_at, word_count, failure_code, summary
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    work.outcome.task_attempt_id,
                    work.outcome.completed_at,
                    work.outcome.word_count,
                    work.outcome.failure_code,
                    work.outcome.summary,
                ),
            )
            await insert_outbox(
                connection,
                event,
                schema="agent",
                task_attempt_id=str(work.receipt.task_attempt_id),
            )
            await insert_audit(connection, intent.audit, schema="agent")
            return AgentOutcomeCommitResult(completed_work=work, created=True)

    @staticmethod
    async def _select_completed(
        connection: AsyncDbConnection, task_attempt_id: TaskAttemptId
    ) -> CompletedAgentWork | None:
        row = await (
            await connection.execute(
                """
                SELECT r.environment, r.agent_deployment_id, r.task_attempt_id,
                       r.command_message_id, r.command_digest,
                       r.terminal_event_message_id, r.completed_at,
                       o.completed_at, o.word_count, o.failure_code, o.summary,
                       e.message_id, e.workflow_id, e.logical_channel, e.ordering_key,
                       e.payload_bytes, e.headers, e.creation_sequence, e.created_at
                FROM agent.completed_receipts r
                JOIN agent.outcomes o ON o.task_attempt_id = r.task_attempt_id
                JOIN agent.terminal_events e
                  ON e.message_id = r.terminal_event_message_id
                JOIN agent.event_outbox x ON x.message_id = e.message_id
                WHERE r.task_attempt_id = %s
                """,
                (task_attempt_id,),
            )
        ).fetchone()
        if row is None:
            return None
        if (
            len(row) != 19
            or not isinstance(row[6], datetime)
            or not isinstance(row[7], datetime)
            or not isinstance(row[15], bytes | bytearray)
            or not isinstance(row[17], int)
            or not isinstance(row[18], datetime)
        ):
            raise PermanentPersistenceError("Stored Agent outcome data is invalid.")
        receipt = AgentCompletedReceipt(
            environment=str(row[0]),
            agent_deployment_id=AgentId(str(row[1])),
            task_attempt_id=TaskAttemptId(str(row[2])),
            command_message_id=MessageId(str(row[3])),
            command_digest=str(row[4]),
            terminal_event_message_id=MessageId(str(row[5])),
            completed_at=row[6],
        )
        outcome = AgentOutcome(
            task_attempt_id=receipt.task_attempt_id,
            completed_at=row[7],
            word_count=_optional_int(row[8]),
            failure_code=None if row[9] is None else str(row[9]),
            summary=None if row[10] is None else str(row[10]),
        )
        event = AgentEventOutboxRecord(
            message_id=MessageId(str(row[11])),
            workflow_id=WorkflowId(str(row[12])),
            logical_channel=str(row[13]),
            ordering_key=str(row[14]),
            payload_bytes=bytes(row[15]),
            headers=decode_headers(row[16]),
            creation_sequence=row[17],
            created_at=row[18],
        )
        return CompletedAgentWork(receipt=receipt, outcome=outcome, event_outbox=event)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int):
        raise PermanentPersistenceError("Stored Agent outcome count is invalid.")
    return value
