"""Technology-neutral Event Bus boundary for Vertical Slice 01.

The port carries immutable domain-message bytes and logical routing values.
Broker clients, physical topics, partitions, offsets, and consumer-group
membership remain adapter details (ADR-0005, Event Bus Port).
"""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class LogicalChannel(Enum):
    """The two bounded-purpose channels selected for Vertical Slice 01."""

    TASK_COMMANDS = "task-commands"
    TASK_OUTCOMES = "task-outcomes"


@dataclass(frozen=True, slots=True)
class LogicalSubscription:
    """Stable platform subscription identity, independent of broker groups."""

    identity: str
    channel: LogicalChannel


@dataclass(frozen=True, slots=True)
class TransportHeader:
    """A validated, nonauthoritative transport header."""

    name: str
    value: bytes | None


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    """One already validated immutable message prepared by an outbox.

    `capability_name` is explicit routing metadata (ADR-0014 Section 6):
    when set on a `TASK_COMMANDS` message, the adapter resolves the
    capability-scoped physical topic instead of a single shared one. `None`
    for logical channels that are not capability-scoped (task-outcomes has
    none today) and is ignored by the adapter in that case.
    """

    logical_channel: LogicalChannel
    message_id: str
    ordering_key: str
    value: bytes
    headers: tuple[TransportHeader, ...] = ()
    capability_name: str | None = None


@dataclass(frozen=True, slots=True)
class DeliveryHandle:
    """Opaque process-local token used only for acknowledgment or rejection."""

    token: str


@dataclass(frozen=True, slots=True)
class EventBusDelivery:
    """Broker-neutral delivery exposed to a validation/processing coordinator."""

    handle: DeliveryHandle
    subscription: LogicalSubscription
    ordering_key: bytes | None
    value: bytes | None
    headers: tuple[TransportHeader, ...]


class PublicationDisposition(Enum):
    """Certainty about one publication attempt."""

    ACKNOWLEDGED = "ACKNOWLEDGED"
    DEFINITIVELY_NOT_ACCEPTED = "DEFINITIVELY_NOT_ACCEPTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class PublicationResult:
    """Bounded, stable result for one publication attempt."""

    disposition: PublicationDisposition
    retryable: bool
    reason_code: str | None = None


class AcknowledgementDisposition(Enum):
    """Certainty about a source-position commit."""

    ACKNOWLEDGED = "ACKNOWLEDGED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class AcknowledgementResult:
    """Bounded, stable result for a consumer acknowledgment attempt."""

    disposition: AcknowledgementDisposition
    reason_code: str | None = None


class RejectionClassification(Enum):
    """Processing classification; rejection never implies acknowledgment."""

    RETRYABLE = "RETRYABLE"
    PERMANENT = "PERMANENT"


@dataclass(frozen=True, slots=True)
class ShutdownResult:
    """Whether all adapter-owned transport work drained inside the bound."""

    drained: bool


class EventBusOperationError(Exception):
    """Stable adapter failure that does not expose a broker exception."""

    def __init__(self, reason_code: str, *, retryable: bool) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.retryable = retryable


class EventPublisherPort(Protocol):
    """Publish immutable messages without exposing a transport client."""

    def publish(self, message: OutboundMessage, *, timeout_seconds: float) -> PublicationResult:
        """Wait at most ``timeout_seconds`` for this message's delivery report."""
        ...

    def stop_accepting(self) -> None:
        """Reject new publication attempts without affecting already queued work."""
        ...

    def close(self, *, timeout_seconds: float) -> ShutdownResult:
        """Stop intake and drain transport-owned work within a bounded interval."""
        ...


class EventConsumerPort(Protocol):
    """Consume through a stable logical subscription with explicit progress."""

    def poll(self, *, timeout_seconds: float) -> EventBusDelivery | None:
        """Return at most one delivery while preserving ordered admission."""
        ...

    def acknowledge(self, handle: DeliveryHandle) -> AcknowledgementResult:
        """Commit progress only after the caller's durable processing commits."""
        ...

    def reject(self, handle: DeliveryHandle, classification: RejectionClassification) -> None:
        """Leave progress uncommitted and either redeliver or park the record."""
        ...

    def stop_intake(self) -> None:
        """Stop polling new records while allowing explicit in-flight disposition."""
        ...

    def close(self, *, timeout_seconds: float) -> ShutdownResult:
        """Bound closure; unacknowledged work remains eligible for redelivery."""
        ...
