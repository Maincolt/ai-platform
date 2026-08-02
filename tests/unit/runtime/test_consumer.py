"""Broker-free tests for asynchronous consumer coordination."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from threading import Event
from time import monotonic
from typing import Any

import pytest

from ai_platform.ports.event_bus import (
    AcknowledgementDisposition,
    AcknowledgementResult,
    DeliveryHandle,
    EventBusDelivery,
    EventBusOperationError,
    LogicalChannel,
    LogicalSubscription,
    RejectionClassification,
    ShutdownResult,
)
from ai_platform.runtime.consumer import (
    ConsumerRecoveryRequired,
    DeliveryAcknowledgementObserverPort,
    DeliveryHandlingDisposition,
    EventConsumerWorker,
    RetryExhaustionHandlerPort,
)


class _FakeConsumer:
    def __init__(
        self,
        deliveries: list[EventBusDelivery | None],
        *,
        acknowledgements: list[AcknowledgementResult | EventBusOperationError] | None = None,
    ) -> None:
        self.deliveries = deliveries
        self.acknowledgements = acknowledgements or []
        self.polled: list[float] = []
        self.acknowledged: list[DeliveryHandle] = []
        self.rejected: list[tuple[DeliveryHandle, RejectionClassification]] = []
        self.stopped = False
        self.close_timeout: float | None = None
        self.revocation_listener: Callable[[tuple[DeliveryHandle, ...]], None] | None = None

    def poll(self, *, timeout_seconds: float) -> EventBusDelivery | None:
        self.polled.append(timeout_seconds)
        return self.deliveries.pop(0) if self.deliveries else None

    def acknowledge(self, handle: DeliveryHandle) -> AcknowledgementResult:
        self.acknowledged.append(handle)
        if self.acknowledgements:
            result = self.acknowledgements.pop(0)
            if isinstance(result, EventBusOperationError):
                raise result
            return result
        return _acknowledged()

    def reject(self, handle: DeliveryHandle, classification: RejectionClassification) -> None:
        self.rejected.append((handle, classification))

    def stop_intake(self) -> None:
        self.stopped = True

    def set_revocation_listener(
        self,
        listener: Callable[[tuple[DeliveryHandle, ...]], None],
    ) -> None:
        self.revocation_listener = listener

    def revoke(self, *handles: DeliveryHandle) -> None:
        assert self.revocation_listener is not None
        self.revocation_listener(handles)

    def close(self, *, timeout_seconds: float) -> ShutdownResult:
        self.close_timeout = timeout_seconds
        return ShutdownResult(drained=True)


class _Handler:
    def __init__(self, dispositions: list[DeliveryHandlingDisposition]) -> None:
        self.dispositions = dispositions
        self.handled: list[EventBusDelivery] = []

    async def handle(self, delivery: EventBusDelivery) -> DeliveryHandlingDisposition:
        self.handled.append(delivery)
        return self.dispositions.pop(0)


class _Observer(DeliveryAcknowledgementObserverPort):
    def __init__(self, *, failures: int = 0) -> None:
        self.failures = failures
        self.observed: list[tuple[EventBusDelivery, DeliveryHandlingDisposition]] = []

    async def after_acknowledgement(
        self,
        delivery: EventBusDelivery,
        disposition: DeliveryHandlingDisposition,
    ) -> None:
        self.observed.append((delivery, disposition))
        if self.failures:
            self.failures -= 1
            raise EventBusOperationError("POST_ACK_RECORD_FAILED", retryable=True)


class _RetryExhaustion(RetryExhaustionHandlerPort):
    def __init__(self, *, confirmed: bool = True) -> None:
        self.confirmed = confirmed
        self.calls: list[tuple[EventBusDelivery, str]] = []

    async def quarantine_retry_exhaustion(
        self,
        delivery: EventBusDelivery,
        *,
        safe_failure_code: str,
    ) -> bool:
        self.calls.append((delivery, safe_failure_code))
        return self.confirmed


class _UnboundedCloseConsumer(_FakeConsumer):
    def __init__(self) -> None:
        super().__init__([])
        self.close_started = Event()
        self.release_close = Event()

    def close(self, *, timeout_seconds: float) -> ShutdownResult:
        self.close_timeout = timeout_seconds
        self.close_started.set()
        self.release_close.wait(timeout=1.0)
        return ShutdownResult(drained=True)


def _delivery(token: str = "delivery-1") -> EventBusDelivery:
    return EventBusDelivery(
        handle=DeliveryHandle(token=token),
        subscription=LogicalSubscription(
            identity="outcome-handler-v1",
            channel=LogicalChannel.TASK_OUTCOMES,
        ),
        ordering_key=b"workflow-1",
        value=b'{"message_id":"message-1"}',
        headers=(),
    )


def _acknowledged() -> AcknowledgementResult:
    return AcknowledgementResult(AcknowledgementDisposition.ACKNOWLEDGED)


def _unknown() -> AcknowledgementResult:
    return AcknowledgementResult(
        AcknowledgementDisposition.UNKNOWN,
        reason_code="OFFSET_COMMIT_FAILED",
    )


def _worker(
    consumer: _FakeConsumer,
    handler: _Handler,
    *,
    idle_delay_seconds: float = 0,
    acknowledgement_observer: DeliveryAcknowledgementObserverPort | None = None,
    retry_exhaustion_handler: RetryExhaustionHandlerPort | None = None,
    maximum_processing_attempts: int = 3,
    maximum_concurrency: int = 1,
    poll_timeout_seconds: float = 0.25,
) -> EventConsumerWorker:
    return EventConsumerWorker(
        consumer=consumer,
        handler=handler,
        retry_exhaustion_handler=retry_exhaustion_handler or _RetryExhaustion(),
        acknowledgement_observer=acknowledgement_observer,
        poll_timeout_seconds=poll_timeout_seconds,
        idle_delay_seconds=idle_delay_seconds,
        retry_delay_seconds=0,
        maximum_processing_attempts=maximum_processing_attempts,
        maximum_concurrency=maximum_concurrency,
    )


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


@pytest.mark.parametrize(
    "disposition",
    [
        DeliveryHandlingDisposition.DURABLY_PROCESSED,
        DeliveryHandlingDisposition.DUPLICATE,
        DeliveryHandlingDisposition.LATE,
        DeliveryHandlingDisposition.DURABLY_QUARANTINED,
    ],
)
def test_durable_dispositions_acknowledge_only_after_handler_returns(
    disposition: DeliveryHandlingDisposition,
) -> None:
    delivery = _delivery()
    consumer = _FakeConsumer([delivery])

    class _DurabilityAssertingHandler(_Handler):
        async def handle(self, delivery: EventBusDelivery) -> DeliveryHandlingDisposition:
            assert consumer.acknowledged == []
            return await super().handle(delivery)

    handler = _DurabilityAssertingHandler([disposition])

    assert _run(_worker(consumer, handler).run_once()) is True

    assert handler.handled == [delivery]
    assert consumer.acknowledged == [delivery.handle]
    assert consumer.rejected == []


def test_unknown_commit_is_retried_without_rerunning_handler_or_polling() -> None:
    delivery = _delivery()
    consumer = _FakeConsumer([delivery, _delivery("must-not-poll")], acknowledgements=[_unknown()])
    handler = _Handler([DeliveryHandlingDisposition.DURABLY_PROCESSED])
    worker = _worker(consumer, handler)

    assert _run(worker.run_once()) is True
    assert _run(worker.run_once()) is True

    assert handler.handled == [delivery]
    assert consumer.polled == [0.25]
    assert consumer.acknowledged == [delivery.handle, delivery.handle]


def test_failed_commit_is_retried_without_rerunning_handler() -> None:
    delivery = _delivery()
    failure = EventBusOperationError("OFFSET_COMMIT_FAILED", retryable=True)
    consumer = _FakeConsumer([delivery], acknowledgements=[failure])
    handler = _Handler([DeliveryHandlingDisposition.DUPLICATE])
    worker = _worker(consumer, handler)

    assert _run(worker.run_once()) is True
    assert _run(worker.run_once()) is True

    assert handler.handled == [delivery]
    assert consumer.acknowledged == [delivery.handle, delivery.handle]


def test_post_acknowledgement_failure_is_nonfatal_and_retries_without_recommitting() -> None:
    delivery = _delivery()
    consumer = _FakeConsumer([delivery])
    handler = _Handler([DeliveryHandlingDisposition.DURABLY_QUARANTINED])
    observer = _Observer(failures=1)
    worker = _worker(consumer, handler, acknowledgement_observer=observer)

    assert _run(worker.run_once()) is True
    assert _run(worker.run_once()) is True

    assert handler.handled == [delivery]
    assert consumer.acknowledged == [delivery.handle]
    assert observer.observed == [
        (delivery, DeliveryHandlingDisposition.DURABLY_QUARANTINED),
        (delivery, DeliveryHandlingDisposition.DURABLY_QUARANTINED),
    ]


def test_retryable_disposition_rejects_for_redelivery_without_acknowledging() -> None:
    delivery = _delivery()
    consumer = _FakeConsumer([delivery])
    handler = _Handler([DeliveryHandlingDisposition.RETRYABLE])

    assert _run(_worker(consumer, handler).run_once()) is True

    assert consumer.rejected == [(delivery.handle, RejectionClassification.RETRYABLE)]
    assert consumer.acknowledged == []


def test_retryable_processing_is_bounded_then_durably_quarantined() -> None:
    deliveries = [_delivery(f"delivery-{number}") for number in range(1, 4)]
    consumer = _FakeConsumer(list(deliveries))
    handler = _Handler([DeliveryHandlingDisposition.RETRYABLE] * 3)
    exhaustion = _RetryExhaustion()
    worker = _worker(
        consumer,
        handler,
        retry_exhaustion_handler=exhaustion,
        maximum_processing_attempts=3,
    )

    assert _run(worker.run_once()) is True
    assert _run(worker.run_once()) is True
    assert _run(worker.run_once()) is True

    assert consumer.rejected == [
        (deliveries[0].handle, RejectionClassification.RETRYABLE),
        (deliveries[1].handle, RejectionClassification.RETRYABLE),
    ]
    assert exhaustion.calls == [(deliveries[2], "PROCESSING_RETRY_EXHAUSTED")]
    assert consumer.acknowledged == [deliveries[2].handle]


def test_unexpected_handler_errors_are_bounded_safely_without_detail_leakage() -> None:
    class _FailingHandler(_Handler):
        async def handle(self, delivery: EventBusDelivery) -> DeliveryHandlingDisposition:
            self.handled.append(delivery)
            raise RuntimeError("sensitive handler detail")

    deliveries = [_delivery(f"delivery-{number}") for number in range(1, 3)]
    consumer = _FakeConsumer(list(deliveries))
    handler = _FailingHandler([])
    exhaustion = _RetryExhaustion()
    worker = _worker(
        consumer,
        handler,
        retry_exhaustion_handler=exhaustion,
        maximum_processing_attempts=2,
    )

    assert _run(worker.run_once()) is True
    assert _run(worker.run_once()) is True

    assert exhaustion.calls == [(deliveries[1], "PROCESSING_EXCEPTION_RETRY_EXHAUSTED")]
    assert "sensitive" not in exhaustion.calls[0][1]
    assert consumer.acknowledged == [deliveries[1].handle]


def test_unconfirmed_retry_exhaustion_parks_without_acknowledging() -> None:
    delivery = _delivery()
    consumer = _FakeConsumer([delivery])
    exhaustion = _RetryExhaustion(confirmed=False)
    worker = _worker(
        consumer,
        _Handler([DeliveryHandlingDisposition.RETRYABLE]),
        retry_exhaustion_handler=exhaustion,
        maximum_processing_attempts=1,
    )

    assert _run(worker.run_once()) is True

    assert consumer.rejected == [(delivery.handle, RejectionClassification.PERMANENT)]
    assert consumer.acknowledged == []


def test_run_terminates_with_stable_failure_when_quarantine_is_unconfirmed() -> None:
    consumer = _FakeConsumer([_delivery()])
    worker = _worker(
        consumer,
        _Handler([DeliveryHandlingDisposition.RETRYABLE]),
        retry_exhaustion_handler=_RetryExhaustion(confirmed=False),
        maximum_processing_attempts=1,
    )

    with pytest.raises(
        ConsumerRecoveryRequired,
        match="CONSUMER_QUARANTINE_RECOVERY_REQUIRED",
    ):
        _run(worker.run())


def test_permanent_disposition_parks_and_stops_additional_intake() -> None:
    delivery = _delivery()
    consumer = _FakeConsumer([delivery, _delivery("must-remain-unpolled")])
    handler = _Handler([DeliveryHandlingDisposition.PERMANENT])
    worker = _worker(consumer, handler)

    assert _run(worker.run_once()) is True
    assert _run(worker.run_once()) is False

    assert consumer.rejected == [(delivery.handle, RejectionClassification.PERMANENT)]
    assert consumer.acknowledged == []
    assert consumer.polled == [0.25]


def test_empty_poll_returns_false_without_calling_handler() -> None:
    consumer = _FakeConsumer([None])
    handler = _Handler([])

    assert _run(_worker(consumer, handler).run_once()) is False

    assert handler.handled == []
    assert consumer.polled == [0.25]


def test_stop_prevents_new_intake() -> None:
    consumer = _FakeConsumer([_delivery()])
    handler = _Handler([DeliveryHandlingDisposition.DURABLY_PROCESSED])
    worker = _worker(consumer, handler)

    _run(worker.stop())

    assert _run(worker.run_once()) is False
    assert consumer.stopped is True
    assert consumer.polled == []


def test_close_retries_pending_acknowledgement_and_forwards_remaining_bound() -> None:
    delivery = _delivery()
    consumer = _FakeConsumer([delivery], acknowledgements=[_unknown()])
    handler = _Handler([DeliveryHandlingDisposition.DURABLY_PROCESSED])
    worker = _worker(consumer, handler)
    assert _run(worker.run_once()) is True

    assert _run(worker.close(timeout_seconds=0.5)) is True

    assert consumer.stopped is True
    assert consumer.acknowledged == [delivery.handle, delivery.handle]
    assert consumer.close_timeout is not None
    assert 0 < consumer.close_timeout <= 0.5


def test_close_enforces_bound_when_adapter_does_not() -> None:
    async def scenario() -> None:
        consumer = _UnboundedCloseConsumer()
        worker = _worker(consumer, _Handler([]))
        started_at = monotonic()
        try:
            assert await worker.close(timeout_seconds=0.05) is False
            elapsed = monotonic() - started_at
        finally:
            consumer.release_close.set()

        assert elapsed < 0.2
        assert consumer.close_started.is_set()
        assert consumer.stopped is True

    _run(scenario())


def test_close_rejects_nonpositive_bound() -> None:
    consumer = _FakeConsumer([])
    worker = _worker(consumer, _Handler([]))

    with pytest.raises(ValueError, match="timeout_seconds must be positive"):
        _run(worker.close(timeout_seconds=0))

    assert consumer.stopped is False


def test_run_honors_bounded_global_concurrency() -> None:
    async def scenario() -> None:
        deliveries: list[EventBusDelivery | None] = [
            _delivery(f"delivery-{number}") for number in range(3)
        ]
        consumer = _FakeConsumer(deliveries)
        two_started = asyncio.Event()
        release = asyncio.Event()

        class _BlockingHandler(_Handler):
            async def handle(self, delivery: EventBusDelivery) -> DeliveryHandlingDisposition:
                self.handled.append(delivery)
                if len(self.handled) == 2:
                    two_started.set()
                await release.wait()
                return DeliveryHandlingDisposition.DURABLY_PROCESSED

        handler = _BlockingHandler([])
        worker = _worker(
            consumer,
            handler,
            maximum_concurrency=2,
            idle_delay_seconds=0.01,
        )
        run_task = asyncio.create_task(worker.run())
        await asyncio.wait_for(two_started.wait(), timeout=0.5)

        assert len(handler.handled) == 2
        assert len(consumer.deliveries) == 1

        release.set()
        while len(consumer.acknowledged) < 2:
            await asyncio.sleep(0)
        await worker.stop()
        await asyncio.wait_for(run_task, timeout=0.5)

    _run(scenario())


def test_rebalance_revocation_cancels_work_and_never_acknowledges_stale_handle() -> None:
    async def scenario() -> None:
        delivery = _delivery()
        consumer = _FakeConsumer([delivery, None])
        started = asyncio.Event()
        cancelled = asyncio.Event()

        class _RevokedHandler(_Handler):
            async def handle(self, delivery: EventBusDelivery) -> DeliveryHandlingDisposition:
                self.handled.append(delivery)
                started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    raise
                raise AssertionError("unreachable: event is never set")

        worker = _worker(
            consumer,
            _RevokedHandler([]),
            idle_delay_seconds=0.01,
        )
        run_task = asyncio.create_task(worker.run())
        await asyncio.wait_for(started.wait(), timeout=0.5)

        consumer.revoke(delivery.handle)
        await asyncio.wait_for(cancelled.wait(), timeout=0.5)
        await worker.stop()
        await asyncio.wait_for(run_task, timeout=0.5)

        assert consumer.acknowledged == []
        assert consumer.rejected == []

    _run(scenario())


def test_run_caps_native_poll_for_responsive_group_membership() -> None:
    async def scenario() -> None:
        consumer = _FakeConsumer([None])
        worker = _worker(
            consumer,
            _Handler([]),
            idle_delay_seconds=0.01,
            poll_timeout_seconds=10.0,
        )
        run_task = asyncio.create_task(worker.run())
        while not consumer.polled:
            await asyncio.sleep(0)
        await worker.stop()
        await asyncio.wait_for(run_task, timeout=0.5)

        assert consumer.polled
        assert max(consumer.polled) <= 0.25

    _run(scenario())
