"""Broker-free tests for the recoverable outbox publisher worker."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from threading import Event
from time import monotonic
from typing import Any

import pytest

from ai_platform.orchestrator.domain.recovery import OrchestratorOutboxRecord
from ai_platform.ports.event_bus import (
    LogicalChannel,
    OutboundMessage,
    PublicationResult,
    ShutdownResult,
    TransportHeader,
)
from ai_platform.ports.event_bus import PublicationDisposition as BusPublicationDisposition
from ai_platform.ports.persistence.outbox import (
    ClaimedOutboxRecord,
    PublicationDisposition,
)
from ai_platform.runtime.publisher import OutboxPublisherWorker
from ai_platform.shared.identifiers import MessageId, WorkflowId
from ai_platform.shared.observability import (
    MetricSignal,
    RecordingOperationalSignals,
    TraceSignal,
)
from ai_platform.shared.recovery import PublicationState


class _FakeOutbox:
    def __init__(self, claim: ClaimedOutboxRecord | None) -> None:
        self.claim = claim
        self.claim_fencing_token: str | None = None
        self.recorded: list[tuple[MessageId, PublicationDisposition, str]] = []

    async def claim_next(
        self,
        *,
        logical_channel: str,
        publisher_instance_id: str,
        fencing_token: str,
        claim_ttl: timedelta,
    ) -> ClaimedOutboxRecord | None:
        assert logical_channel == LogicalChannel.TASK_COMMANDS.value
        assert publisher_instance_id == "publisher-1"
        assert claim_ttl == timedelta(seconds=30)
        self.claim_fencing_token = fencing_token
        return self.claim

    async def record_publication_result(
        self,
        message_id: MessageId,
        disposition: PublicationDisposition,
        *,
        fencing_token: str,
    ) -> None:
        self.recorded.append((message_id, disposition, fencing_token))

    async def release_claim(self, message_id: MessageId, *, fencing_token: str) -> None:
        raise AssertionError(f"unexpected claim release for {message_id} with {fencing_token}")


class _FakePublisher:
    def __init__(self, result: PublicationResult) -> None:
        self.result = result
        self.published: list[tuple[OutboundMessage, float]] = []
        self.stopped = False
        self.close_timeout: float | None = None

    def publish(self, message: OutboundMessage, *, timeout_seconds: float) -> PublicationResult:
        self.published.append((message, timeout_seconds))
        return self.result

    def stop_accepting(self) -> None:
        self.stopped = True

    def close(self, *, timeout_seconds: float) -> ShutdownResult:
        self.close_timeout = timeout_seconds
        return ShutdownResult(drained=True)


class _BlockingPublisher(_FakePublisher):
    def __init__(self) -> None:
        super().__init__(_bus_result(BusPublicationDisposition.UNKNOWN))
        self.publish_started = Event()
        self.release_publish = Event()

    def publish(self, message: OutboundMessage, *, timeout_seconds: float) -> PublicationResult:
        self.published.append((message, timeout_seconds))
        self.publish_started.set()
        self.release_publish.wait(timeout=1.0)
        return self.result


class _UnboundedClosePublisher(_FakePublisher):
    def __init__(self) -> None:
        super().__init__(_bus_result(BusPublicationDisposition.ACKNOWLEDGED))
        self.close_started = Event()
        self.release_close = Event()

    def close(self, *, timeout_seconds: float) -> ShutdownResult:
        self.close_timeout = timeout_seconds
        self.close_started.set()
        self.release_close.wait(timeout=1.0)
        return ShutdownResult(drained=True)


class _FailingSignals:
    def metric(self, signal: MetricSignal) -> None:
        raise RuntimeError(f"telemetry unavailable: {signal.name}")

    def trace(self, signal: TraceSignal) -> None:
        del signal


def _bus_result(
    disposition: BusPublicationDisposition,
    *,
    retryable: bool | None = None,
    reason_code: str | None = None,
) -> PublicationResult:
    return PublicationResult(
        disposition=disposition,
        retryable=(
            disposition is not BusPublicationDisposition.ACKNOWLEDGED
            if retryable is None
            else retryable
        ),
        reason_code=reason_code,
    )


def _claim(*, fencing_token: str = "authoritative-claim-token") -> ClaimedOutboxRecord:
    created_at = datetime(2026, 8, 1, tzinfo=UTC)
    record = OrchestratorOutboxRecord(
        message_id=MessageId("01900000-0000-7000-8000-000000000002"),
        workflow_id=WorkflowId("01900000-0000-7000-8000-000000000001"),
        logical_channel=LogicalChannel.TASK_COMMANDS.value,
        ordering_key="01900000-0000-7000-8000-000000000001",
        payload_bytes=b'{ "preserve" : "these exact bytes" }',
        headers=(("traceparent", b"safe-value"),),
        creation_sequence=1,
        created_at=created_at,
    )
    return ClaimedOutboxRecord(
        record=record,
        fencing_token=fencing_token,
        claim_expires_at=created_at + timedelta(seconds=30),
        publication_attempts=1,
    )


def _worker(outbox: _FakeOutbox, publisher: _FakePublisher) -> OutboxPublisherWorker:
    return OutboxPublisherWorker(
        outbox=outbox,
        publisher=publisher,
        logical_channel=LogicalChannel.TASK_COMMANDS,
        publisher_instance_id="publisher-1",
        claim_ttl=timedelta(seconds=30),
        publish_timeout_seconds=2.5,
        idle_delay_seconds=0,
    )


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


@pytest.mark.parametrize(
    ("bus_disposition", "expected_state"),
    [
        (BusPublicationDisposition.ACKNOWLEDGED, PublicationState.ACKNOWLEDGED),
        (
            BusPublicationDisposition.DEFINITIVELY_NOT_ACCEPTED,
            PublicationState.DEFINITIVELY_NOT_ACCEPTED,
        ),
        (BusPublicationDisposition.UNKNOWN, PublicationState.ATTEMPTED_UNKNOWN),
    ],
)
def test_run_once_preserves_bytes_and_maps_publication_certainty(
    bus_disposition: BusPublicationDisposition,
    expected_state: PublicationState,
) -> None:
    claim = _claim()
    outbox = _FakeOutbox(claim)
    publisher = _FakePublisher(_bus_result(bus_disposition, reason_code="SAFE_REASON"))

    assert _run(_worker(outbox, publisher).run_once()) is True

    assert publisher.published == [
        (
            OutboundMessage(
                logical_channel=LogicalChannel.TASK_COMMANDS,
                message_id=str(claim.record.message_id),
                ordering_key=claim.record.ordering_key,
                value=claim.record.payload_bytes,
                headers=(TransportHeader(name="traceparent", value=b"safe-value"),),
            ),
            2.5,
        )
    ]
    message_id, disposition, fencing_token = outbox.recorded[0]
    assert message_id == claim.record.message_id
    assert disposition.state is expected_state
    assert disposition.safe_failure_code == "SAFE_REASON"
    assert disposition.retryable is (bus_disposition is not BusPublicationDisposition.ACKNOWLEDGED)
    assert disposition.attempted_at.tzinfo is UTC
    assert fencing_token == claim.fencing_token
    assert outbox.claim_fencing_token is not None
    assert outbox.claim_fencing_token != claim.fencing_token


def test_nonretryable_transport_result_is_durably_marked_nonretryable() -> None:
    outbox = _FakeOutbox(_claim())
    publisher = _FakePublisher(
        _bus_result(
            BusPublicationDisposition.DEFINITIVELY_NOT_ACCEPTED,
            retryable=False,
            reason_code="PERMANENT_TRANSPORT_FAILURE",
        )
    )

    assert _run(_worker(outbox, publisher).run_once()) is True

    disposition = outbox.recorded[0][1]
    assert disposition.state is PublicationState.DEFINITIVELY_NOT_ACCEPTED
    assert disposition.retryable is False


def test_run_once_returns_false_without_publishing_when_queue_is_empty() -> None:
    outbox = _FakeOutbox(None)
    publisher = _FakePublisher(_bus_result(BusPublicationDisposition.ACKNOWLEDGED))

    assert _run(_worker(outbox, publisher).run_once()) is False

    assert publisher.published == []
    assert outbox.recorded == []


def test_publication_signal_is_backend_neutral_and_failure_isolated() -> None:
    outbox = _FakeOutbox(_claim())
    publisher = _FakePublisher(_bus_result(BusPublicationDisposition.ACKNOWLEDGED))
    signals = RecordingOperationalSignals()
    worker = OutboxPublisherWorker(
        outbox=outbox,
        publisher=publisher,
        logical_channel=LogicalChannel.TASK_COMMANDS,
        publisher_instance_id="publisher-1",
        claim_ttl=timedelta(seconds=30),
        publish_timeout_seconds=2.5,
        signals=signals,
    )

    assert _run(worker.run_once()) is True
    assert signals.metrics == [
        MetricSignal(
            name="event_bus.publish_attempt",
            value=1,
            labels=(("channel", "task-commands"), ("outcome", "ACKNOWLEDGED")),
        )
    ]

    failing_worker = OutboxPublisherWorker(
        outbox=_FakeOutbox(_claim()),
        publisher=publisher,
        logical_channel=LogicalChannel.TASK_COMMANDS,
        publisher_instance_id="publisher-1",
        claim_ttl=timedelta(seconds=30),
        publish_timeout_seconds=2.5,
        signals=_FailingSignals(),
    )
    assert _run(failing_worker.run_once()) is True


def test_cancellation_after_claim_records_unknown_with_claim_fencing_token() -> None:
    async def scenario() -> None:
        claim = _claim(fencing_token="token-returned-by-store")
        outbox = _FakeOutbox(claim)
        publisher = _BlockingPublisher()
        task = asyncio.create_task(_worker(outbox, publisher).run_once())
        try:
            assert await asyncio.to_thread(publisher.publish_started.wait, 1.0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            publisher.release_publish.set()

        message_id, disposition, fencing_token = outbox.recorded[0]
        assert message_id == claim.record.message_id
        assert disposition.state is PublicationState.ATTEMPTED_UNKNOWN
        assert disposition.safe_failure_code == "PUBLISH_CANCELLED_AFTER_CLAIM"
        assert fencing_token == claim.fencing_token

    _run(scenario())


def test_close_stops_intake_and_forwards_bound() -> None:
    outbox = _FakeOutbox(None)
    publisher = _FakePublisher(_bus_result(BusPublicationDisposition.ACKNOWLEDGED))

    assert _run(_worker(outbox, publisher).close(timeout_seconds=0.5)) is True

    assert publisher.stopped is True
    assert publisher.close_timeout == 0.5


def test_close_enforces_bound_when_adapter_does_not() -> None:
    async def scenario() -> None:
        outbox = _FakeOutbox(None)
        publisher = _UnboundedClosePublisher()
        started_at = monotonic()
        try:
            assert await _worker(outbox, publisher).close(timeout_seconds=0.05) is False
            elapsed = monotonic() - started_at
        finally:
            publisher.release_close.set()

        assert elapsed < 0.2
        assert publisher.close_started.is_set()
        assert publisher.close_timeout == 0.05

    _run(scenario())


def test_close_rejects_nonpositive_bound() -> None:
    outbox = _FakeOutbox(None)
    publisher = _FakePublisher(_bus_result(BusPublicationDisposition.ACKNOWLEDGED))

    with pytest.raises(ValueError, match="timeout_seconds must be positive"):
        _run(_worker(outbox, publisher).close(timeout_seconds=0))

    assert publisher.stopped is False
