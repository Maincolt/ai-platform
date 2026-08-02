"""Durable pre-identity transport-rejection recovery adapter."""

from datetime import datetime

from psycopg import sql

from ai_platform.adapters.persistence.connection import AsyncDbConnection, AsyncPsycopgPool
from ai_platform.adapters.persistence.retry import (
    DEFAULT_TRANSACTION_RETRY_POLICY,
    TransactionRetryPolicy,
    retry_transaction,
)
from ai_platform.ports.persistence.errors import PermanentPersistenceError, PersistenceConflictError
from ai_platform.ports.persistence.recovery import (
    QuarantinePublicationState,
    TransportDeliveryLocator,
    TransportRejectionRecord,
)


class PsycopgTransportRejectionTransaction:
    def __init__(
        self,
        pool: AsyncPsycopgPool,
        *,
        retry_policy: TransactionRetryPolicy = DEFAULT_TRANSACTION_RETRY_POLICY,
    ) -> None:
        self._pool = pool
        self._table = sql.Identifier(pool.component_schema, "transport_rejections")
        self.transaction_retry_policy = retry_policy

    @retry_transaction
    async def create_or_resolve(
        self,
        *,
        locator: TransportDeliveryLocator,
        rejection_id: str,
        safe_failure_code: str,
        original_bytes_sha256: str,
        recorded_at: datetime,
    ) -> TransportRejectionRecord:
        async with self._pool.transaction() as connection:
            inserted = await (
                await connection.execute(
                    sql.SQL("""
                    INSERT INTO {} (
                        logical_subscription, physical_source, partition_number,
                        source_offset, rejection_id, safe_failure_code,
                        original_bytes_sha256, recorded_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (
                        logical_subscription, physical_source, partition_number, source_offset
                    ) DO NOTHING
                    RETURNING logical_subscription, physical_source, partition_number,
                              source_offset, rejection_id, safe_failure_code,
                              original_bytes_sha256, quarantine_state,
                              source_offset_completed, recorded_at
                    """).format(self._table),
                    self._locator_params(locator)
                    + (rejection_id, safe_failure_code, original_bytes_sha256, recorded_at),
                )
            ).fetchone()
            row = inserted or await self._select(connection, locator)
            if row is None:
                raise PermanentPersistenceError("Transport rejection could not be resolved.")
            record = self._record_from_row(row)
            if (
                record.rejection_id != rejection_id
                or record.safe_failure_code != safe_failure_code
                or record.original_bytes_sha256 != original_bytes_sha256
            ):
                raise PersistenceConflictError(
                    "The transport delivery locator has conflicting immutable evidence."
                )
            return record

    @retry_transaction
    async def record_quarantine_state(
        self,
        locator: TransportDeliveryLocator,
        *,
        state: QuarantinePublicationState,
        recorded_at: datetime,
    ) -> TransportRejectionRecord:
        if state is QuarantinePublicationState.NOT_ATTEMPTED:
            raise ValueError("quarantine state cannot be reset to NOT_ATTEMPTED")
        async with self._pool.transaction() as connection:
            result = await connection.execute(
                sql.SQL("""
                UPDATE {}
                SET quarantine_state = %s, quarantine_updated_at = %s
                WHERE logical_subscription = %s AND physical_source = %s
                  AND partition_number = %s AND source_offset = %s
                  AND (quarantine_state <> 'CONFIRMED' OR %s = 'CONFIRMED')
                """).format(self._table),
                (
                    state.value,
                    recorded_at,
                    *self._locator_params(locator),
                    state.value,
                ),
            )
            if result.rowcount != 1:
                row = await self._select(connection, locator)
                if row is None:
                    raise PersistenceConflictError("The transport rejection does not exist.")
            row = await self._select(connection, locator)
            if row is None:
                raise PermanentPersistenceError("Transport rejection disappeared after update.")
            return self._record_from_row(row)

    @retry_transaction
    async def mark_source_offset_completed(
        self, locator: TransportDeliveryLocator, *, completed_at: datetime
    ) -> None:
        async with self._pool.transaction() as connection:
            result = await connection.execute(
                sql.SQL("""
                UPDATE {}
                SET source_offset_completed = TRUE,
                    source_offset_completed_at = COALESCE(source_offset_completed_at, %s)
                WHERE logical_subscription = %s AND physical_source = %s
                  AND partition_number = %s AND source_offset = %s
                  AND quarantine_state = 'CONFIRMED'
                """).format(self._table),
                (completed_at, *self._locator_params(locator)),
            )
            if result.rowcount != 1:
                raise PersistenceConflictError(
                    "Source offset completion requires confirmed quarantine publication."
                )

    @retry_transaction
    async def list_confirmed_incomplete(
        self,
        *,
        logical_subscription: str,
        limit: int,
    ) -> tuple[TransportRejectionRecord, ...]:
        if not logical_subscription or limit < 1 or limit > 1_000:
            raise ValueError("confirmed-incomplete recovery bounds are invalid")
        async with self._pool.connection() as connection:
            rows = await (
                await connection.execute(
                    sql.SQL("""
                    SELECT logical_subscription, physical_source, partition_number,
                           source_offset, rejection_id, safe_failure_code,
                           original_bytes_sha256, quarantine_state,
                           source_offset_completed, recorded_at
                    FROM {}
                    WHERE logical_subscription = %s
                      AND quarantine_state = 'CONFIRMED'
                      AND source_offset_completed = FALSE
                    ORDER BY recorded_at, physical_source, partition_number, source_offset
                    LIMIT %s
                    """).format(self._table),
                    (logical_subscription, limit),
                )
            ).fetchall()
        return tuple(self._record_from_row(row) for row in rows)

    async def _select(
        self, connection: AsyncDbConnection, locator: TransportDeliveryLocator
    ) -> tuple[object, ...] | None:
        return await (
            await connection.execute(
                sql.SQL("""
                SELECT logical_subscription, physical_source, partition_number,
                       source_offset, rejection_id, safe_failure_code,
                       original_bytes_sha256, quarantine_state,
                       source_offset_completed, recorded_at
                FROM {}
                WHERE logical_subscription = %s AND physical_source = %s
                  AND partition_number = %s AND source_offset = %s
                """).format(self._table),
                self._locator_params(locator),
            )
        ).fetchone()

    @staticmethod
    def _locator_params(locator: TransportDeliveryLocator) -> tuple[object, ...]:
        return (
            locator.logical_subscription,
            locator.physical_source,
            locator.partition,
            locator.offset,
        )

    @staticmethod
    def _record_from_row(row: tuple[object, ...]) -> TransportRejectionRecord:
        if (
            len(row) != 10
            or not isinstance(row[2], int)
            or not isinstance(row[3], int)
            or not isinstance(row[8], bool)
            or not isinstance(row[9], datetime)
        ):
            raise PermanentPersistenceError("Stored transport rejection is invalid.")
        return TransportRejectionRecord(
            locator=TransportDeliveryLocator(
                logical_subscription=str(row[0]),
                physical_source=str(row[1]),
                partition=row[2],
                offset=row[3],
            ),
            rejection_id=str(row[4]),
            safe_failure_code=str(row[5]),
            original_bytes_sha256=str(row[6]),
            quarantine_state=QuarantinePublicationState(str(row[7])),
            source_offset_completed=row[8],
            recorded_at=row[9],
        )
