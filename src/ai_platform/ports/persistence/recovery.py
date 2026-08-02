"""Durable pre-identity transport-rejection recovery port."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol


@dataclass(frozen=True, slots=True)
class TransportDeliveryLocator:
    logical_subscription: str
    physical_source: str
    partition: int
    offset: int


class QuarantinePublicationState(Enum):
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    ATTEMPTED_UNKNOWN = "ATTEMPTED_UNKNOWN"
    CONFIRMED = "CONFIRMED"


@dataclass(frozen=True, slots=True)
class TransportRejectionRecord:
    locator: TransportDeliveryLocator
    rejection_id: str
    safe_failure_code: str
    original_bytes_sha256: str
    quarantine_state: QuarantinePublicationState
    source_offset_completed: bool
    recorded_at: datetime


class TransportRejectionTransactionPort(Protocol):
    async def create_or_resolve(
        self,
        *,
        locator: TransportDeliveryLocator,
        rejection_id: str,
        safe_failure_code: str,
        original_bytes_sha256: str,
        recorded_at: datetime,
    ) -> TransportRejectionRecord:
        """Create one stable rejection identity for a broker delivery."""
        ...

    async def record_quarantine_state(
        self,
        locator: TransportDeliveryLocator,
        *,
        state: QuarantinePublicationState,
        recorded_at: datetime,
    ) -> TransportRejectionRecord: ...

    async def mark_source_offset_completed(
        self, locator: TransportDeliveryLocator, *, completed_at: datetime
    ) -> None:
        """Allowed only after quarantine publication is durably confirmed."""
        ...

    async def list_confirmed_incomplete(
        self,
        *,
        logical_subscription: str,
        limit: int,
    ) -> tuple[TransportRejectionRecord, ...]:
        """Return a bounded recovery batch awaiting source-commit evidence."""
        ...
