"""Psycopg asynchronous fenced outbox transaction adapter."""

from dataclasses import dataclass
from datetime import timedelta

from ai_platform.adapters.persistence import _outbox_common
from ai_platform.adapters.persistence.connection import AsyncPsycopgPool
from ai_platform.adapters.persistence.retry import (
    DEFAULT_TRANSACTION_RETRY_POLICY,
    TransactionRetryPolicy,
    retry_transaction,
)
from ai_platform.ports.persistence.outbox import ClaimedOutboxRecord, PublicationDisposition
from ai_platform.shared.identifiers import MessageId


@dataclass(frozen=True, slots=True)
class OutboxRecoveryPolicy:
    """Bound automatic publication retries while retaining terminal rows."""

    max_publication_attempts: int = 3

    def __post_init__(self) -> None:
        if not 1 <= self.max_publication_attempts <= 100:
            raise ValueError("max_publication_attempts must be between 1 and 100")


DEFAULT_OUTBOX_RECOVERY_POLICY = OutboxRecoveryPolicy()


class PsycopgOutboxTransaction:
    def __init__(
        self,
        pool: AsyncPsycopgPool,
        *,
        retry_policy: TransactionRetryPolicy = DEFAULT_TRANSACTION_RETRY_POLICY,
        recovery_policy: OutboxRecoveryPolicy = DEFAULT_OUTBOX_RECOVERY_POLICY,
    ) -> None:
        self._pool = pool
        self.transaction_retry_policy = retry_policy
        self._recovery_policy = recovery_policy

    @retry_transaction
    async def claim_next(
        self,
        *,
        logical_channel: str,
        publisher_instance_id: str,
        fencing_token: str,
        claim_ttl: timedelta,
    ) -> ClaimedOutboxRecord | None:
        async with self._pool.transaction() as connection:
            return await _outbox_common.claim_next(
                connection,
                schema=self._pool.component_schema,
                logical_channel=logical_channel,
                publisher_instance_id=publisher_instance_id,
                fencing_token=fencing_token,
                claim_ttl=claim_ttl,
                max_publication_attempts=self._recovery_policy.max_publication_attempts,
            )

    @retry_transaction
    async def record_publication_result(
        self,
        message_id: MessageId,
        disposition: PublicationDisposition,
        *,
        fencing_token: str,
    ) -> None:
        async with self._pool.transaction() as connection:
            await _outbox_common.record_publication_result(
                connection,
                schema=self._pool.component_schema,
                message_id=message_id,
                disposition=disposition,
                fencing_token=fencing_token,
            )

    @retry_transaction
    async def release_claim(self, message_id: MessageId, *, fencing_token: str) -> None:
        async with self._pool.transaction() as connection:
            await _outbox_common.release_claim(
                connection,
                schema=self._pool.component_schema,
                message_id=message_id,
                fencing_token=fencing_token,
            )
