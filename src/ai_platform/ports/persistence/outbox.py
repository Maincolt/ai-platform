"""Async outbox claim and publication-state transaction ports."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from ai_platform.agents.domain.outcomes import AgentEventOutboxRecord
from ai_platform.orchestrator.domain.recovery import OrchestratorOutboxRecord
from ai_platform.shared.identifiers import MessageId
from ai_platform.shared.recovery import PublicationState

type OutboxRecord = OrchestratorOutboxRecord | AgentEventOutboxRecord


@dataclass(frozen=True, slots=True)
class ClaimedOutboxRecord:
    record: OutboxRecord
    fencing_token: str
    claim_expires_at: datetime
    publication_attempts: int


@dataclass(frozen=True, slots=True)
class PublicationDisposition:
    state: PublicationState
    attempted_at: datetime
    retryable: bool
    safe_failure_code: str | None = None


class OutboxTransactionPort(Protocol):
    async def claim_next(
        self,
        *,
        logical_channel: str,
        publisher_instance_id: str,
        fencing_token: str,
        claim_ttl: timedelta,
    ) -> ClaimedOutboxRecord | None:
        """Claim the earliest eligible record without blocking unrelated keys."""
        ...

    async def record_publication_result(
        self,
        message_id: MessageId,
        disposition: PublicationDisposition,
        *,
        fencing_token: str,
    ) -> None:
        """Finalize one attempt only when the current fencing token matches."""
        ...

    async def release_claim(self, message_id: MessageId, *, fencing_token: str) -> None:
        """Release an unattempted claim during bounded graceful shutdown."""
        ...
