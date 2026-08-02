"""Recoverable outbox publisher worker."""

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ai_platform.ports.event_bus import (
    EventPublisherPort,
    LogicalChannel,
    OutboundMessage,
    TransportHeader,
)
from ai_platform.ports.event_bus import PublicationDisposition as BusPublicationDisposition
from ai_platform.ports.persistence.outbox import (
    OutboxTransactionPort,
    PublicationDisposition,
)
from ai_platform.shared.observability import (
    MetricSignal,
    NoOpOperationalSignals,
    OperationalSignalsPort,
)
from ai_platform.shared.recovery import PublicationState


class OutboxPublisherWorker:
    """Publish immutable claimed records and durably record attempt certainty."""

    def __init__(
        self,
        *,
        outbox: OutboxTransactionPort,
        publisher: EventPublisherPort,
        logical_channel: LogicalChannel,
        publisher_instance_id: str,
        claim_ttl: timedelta,
        publish_timeout_seconds: float,
        idle_delay_seconds: float = 0.1,
        signals: OperationalSignalsPort | None = None,
    ) -> None:
        if claim_ttl <= timedelta(0):
            raise ValueError("claim_ttl must be positive")
        if publish_timeout_seconds <= 0 or idle_delay_seconds < 0:
            raise ValueError("publisher timing bounds are invalid")
        self._outbox = outbox
        self._publisher = publisher
        self._logical_channel = logical_channel
        self._publisher_instance_id = publisher_instance_id
        self._claim_ttl = claim_ttl
        self._publish_timeout_seconds = publish_timeout_seconds
        self._idle_delay_seconds = idle_delay_seconds
        self._signals = signals or NoOpOperationalSignals()
        self._stopping = asyncio.Event()

    async def run_once(self) -> bool:
        """Process at most one record; return whether work was claimed."""

        fencing_token = uuid4().hex
        claim = await self._outbox.claim_next(
            logical_channel=self._logical_channel.value,
            publisher_instance_id=self._publisher_instance_id,
            fencing_token=fencing_token,
            claim_ttl=self._claim_ttl,
        )
        if claim is None:
            return False

        record = claim.record
        message = OutboundMessage(
            logical_channel=self._logical_channel,
            message_id=str(record.message_id),
            ordering_key=record.ordering_key,
            value=record.payload_bytes,
            headers=tuple(
                TransportHeader(name=name, value=value) for name, value in record.headers
            ),
        )
        attempted_at = datetime.now(UTC)
        try:
            result = await asyncio.to_thread(
                self._publisher.publish,
                message,
                timeout_seconds=self._publish_timeout_seconds,
            )
        except asyncio.CancelledError:
            await self._outbox.record_publication_result(
                record.message_id,
                PublicationDisposition(
                    state=PublicationState.ATTEMPTED_UNKNOWN,
                    attempted_at=attempted_at,
                    retryable=True,
                    safe_failure_code="PUBLISH_CANCELLED_AFTER_CLAIM",
                ),
                fencing_token=claim.fencing_token,
            )
            raise

        if result.disposition is BusPublicationDisposition.ACKNOWLEDGED:
            state = PublicationState.ACKNOWLEDGED
        elif result.disposition is BusPublicationDisposition.DEFINITIVELY_NOT_ACCEPTED:
            state = PublicationState.DEFINITIVELY_NOT_ACCEPTED
        else:
            state = PublicationState.ATTEMPTED_UNKNOWN
        await self._outbox.record_publication_result(
            record.message_id,
            PublicationDisposition(
                state=state,
                attempted_at=attempted_at,
                retryable=result.retryable,
                safe_failure_code=result.reason_code,
            ),
            fencing_token=claim.fencing_token,
        )
        self._emit_publication_metric(state)
        return True

    def _emit_publication_metric(self, state: PublicationState) -> None:
        # Optional telemetry cannot become a publication dependency.
        with suppress(Exception):
            self._signals.metric(
                MetricSignal(
                    name="event_bus.publish_attempt",
                    value=1,
                    labels=(
                        ("channel", self._logical_channel.value),
                        ("outcome", state.value),
                    ),
                )
            )

    async def run(self) -> None:
        while not self._stopping.is_set():
            handled = await self.run_once()
            if not handled:
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._stopping.wait(), timeout=self._idle_delay_seconds)

    def stop(self) -> None:
        self._stopping.set()
        self._publisher.stop_accepting()

    async def close(self, *, timeout_seconds: float) -> bool:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.stop()
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    self._publisher.close,
                    timeout_seconds=timeout_seconds,
                ),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            return False
        return result.drained
