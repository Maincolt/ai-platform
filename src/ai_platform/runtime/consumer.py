"""Broker-neutral asynchronous Event Bus consumer coordination."""

from __future__ import annotations

import asyncio
import hashlib
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum
from time import monotonic
from typing import Protocol

from ai_platform.ports.event_bus import (
    AcknowledgementDisposition,
    DeliveryHandle,
    EventBusDelivery,
    EventBusOperationError,
    EventConsumerPort,
    RejectionClassification,
)


class DeliveryHandlingDisposition(Enum):
    """Stable result of handling one delivery.

    The first three and ``DURABLY_QUARANTINED`` prove that the handler has
    committed every required durable effect. ``RETRYABLE`` and ``PERMANENT``
    do not grant permission to advance source progress.
    """

    DURABLY_PROCESSED = "DURABLY_PROCESSED"
    DUPLICATE = "DUPLICATE"
    LATE = "LATE"
    RETRYABLE = "RETRYABLE"
    PERMANENT = "PERMANENT"
    DURABLY_QUARANTINED = "DURABLY_QUARANTINED"


class DeliveryHandlerPort(Protocol):
    """Apply one delivery and report its durable processing disposition."""

    async def handle(self, delivery: EventBusDelivery) -> DeliveryHandlingDisposition:
        """Handle a delivery without acknowledging its broker position."""
        ...


class DeliveryAcknowledgementObserverPort(Protocol):
    """Persist post-commit evidence after source progress is acknowledged."""

    async def after_acknowledgement(
        self,
        delivery: EventBusDelivery,
        disposition: DeliveryHandlingDisposition,
    ) -> None:
        """Complete any durable bookkeeping that must follow source commit."""
        ...


class RetryExhaustionHandlerPort(Protocol):
    """Durably quarantine a delivery after bounded processing attempts."""

    async def quarantine_retry_exhaustion(
        self,
        delivery: EventBusDelivery,
        *,
        safe_failure_code: str,
    ) -> bool:
        """Return true only when quarantine confirmation is durable."""
        ...


class ConsumerRecoveryRequired(RuntimeError):
    """Consumer stopped because durable quarantine confirmation is incomplete."""


_ACKNOWLEDGE_DISPOSITIONS = frozenset(
    {
        DeliveryHandlingDisposition.DURABLY_PROCESSED,
        DeliveryHandlingDisposition.DUPLICATE,
        DeliveryHandlingDisposition.LATE,
        DeliveryHandlingDisposition.DURABLY_QUARANTINED,
    }
)


@dataclass(slots=True)
class _PendingAcknowledgement:
    delivery: EventBusDelivery
    disposition: DeliveryHandlingDisposition
    transport_acknowledged: bool = False


class EventConsumerWorker:
    """Coordinate asynchronous handling with explicit transport progress.

    A delivery whose handler has committed a durable outcome moves into an
    acknowledgment-only state. An unknown or failed offset commit leaves that
    state intact, so later iterations retry only the commit and never rerun the
    handler.
    """

    def __init__(
        self,
        *,
        consumer: EventConsumerPort,
        handler: DeliveryHandlerPort,
        retry_exhaustion_handler: RetryExhaustionHandlerPort,
        acknowledgement_observer: DeliveryAcknowledgementObserverPort | None = None,
        poll_timeout_seconds: float,
        idle_delay_seconds: float = 0.1,
        retry_delay_seconds: float = 0.1,
        maximum_processing_attempts: int = 3,
        maximum_concurrency: int = 1,
    ) -> None:
        if poll_timeout_seconds <= 0 or idle_delay_seconds < 0 or retry_delay_seconds < 0:
            raise ValueError("consumer timing bounds are invalid")
        if maximum_processing_attempts < 1:
            raise ValueError("maximum_processing_attempts must be positive")
        if maximum_concurrency < 1:
            raise ValueError("maximum_concurrency must be positive")
        self._consumer = consumer
        self._handler = handler
        self._retry_exhaustion_handler = retry_exhaustion_handler
        self._acknowledgement_observer = acknowledgement_observer
        self._poll_timeout_seconds = poll_timeout_seconds
        self._idle_delay_seconds = idle_delay_seconds
        self._retry_delay_seconds = retry_delay_seconds
        self._maximum_processing_attempts = maximum_processing_attempts
        self._maximum_concurrency = maximum_concurrency
        self._stopping = asyncio.Event()
        self._iteration_lock = asyncio.Lock()
        self._pending_acknowledgement: _PendingAcknowledgement | None = None
        self._permanently_parked = False
        self._retry_fingerprint: str | None = None
        self._processing_attempts = 0
        self._retry_waiting = False
        self._active_tasks: dict[str, asyncio.Task[None]] = {}
        self._concurrent_retry_attempts: dict[str, int] = {}
        self._run_loop: asyncio.AbstractEventLoop | None = None

    async def run_once(self) -> bool:
        """Process or disposition at most one delivery.

        ``True`` means a delivery or pending acknowledgment was attempted;
        ``False`` means no work was admitted or a permanent delivery remains
        parked awaiting separately durable quarantine handling.
        """

        async with self._iteration_lock:
            if self._pending_acknowledgement is not None:
                await self._acknowledge_pending()
                return True
            if self._permanently_parked or self._stopping.is_set():
                return False

            delivery = await asyncio.to_thread(
                self._consumer.poll,
                timeout_seconds=self._poll_timeout_seconds,
            )
            if delivery is None:
                return False

            try:
                disposition = await self._handler.handle(delivery)
            except Exception:
                await self._handle_retryable(
                    delivery,
                    safe_failure_code="PROCESSING_EXCEPTION_RETRY_EXHAUSTED",
                )
                return True
            if disposition in _ACKNOWLEDGE_DISPOSITIONS:
                self._reset_retry_state()
                self._pending_acknowledgement = _PendingAcknowledgement(
                    delivery=delivery,
                    disposition=disposition,
                )
                await self._acknowledge_pending()
            elif disposition is DeliveryHandlingDisposition.RETRYABLE:
                await self._handle_retryable(
                    delivery,
                    safe_failure_code="PROCESSING_RETRY_EXHAUSTED",
                )
            else:
                self._reset_retry_state()
                await asyncio.to_thread(
                    self._consumer.reject,
                    delivery.handle,
                    RejectionClassification.PERMANENT,
                )
                self._permanently_parked = True
            return True

    async def _handle_retryable(
        self,
        delivery: EventBusDelivery,
        *,
        safe_failure_code: str,
    ) -> None:
        fingerprint = _delivery_fingerprint(delivery)
        if fingerprint != self._retry_fingerprint:
            self._retry_fingerprint = fingerprint
            self._processing_attempts = 0
        self._processing_attempts += 1

        if self._processing_attempts < self._maximum_processing_attempts:
            await asyncio.to_thread(
                self._consumer.reject,
                delivery.handle,
                RejectionClassification.RETRYABLE,
            )
            self._retry_waiting = True
            return

        try:
            confirmed = await self._retry_exhaustion_handler.quarantine_retry_exhaustion(
                delivery,
                safe_failure_code=safe_failure_code,
            )
        except Exception:
            confirmed = False
        self._reset_retry_state()
        if confirmed:
            self._pending_acknowledgement = _PendingAcknowledgement(
                delivery=delivery,
                disposition=DeliveryHandlingDisposition.DURABLY_QUARANTINED,
            )
            await self._acknowledge_pending()
            return

        await asyncio.to_thread(
            self._consumer.reject,
            delivery.handle,
            RejectionClassification.PERMANENT,
        )
        self._permanently_parked = True

    def _reset_retry_state(self) -> None:
        self._retry_fingerprint = None
        self._processing_attempts = 0
        self._retry_waiting = False

    async def _acknowledge_pending(self) -> bool:
        pending = self._pending_acknowledgement
        if pending is None:
            return True
        if not pending.transport_acknowledged:
            try:
                result = await asyncio.to_thread(
                    self._consumer.acknowledge,
                    pending.delivery.handle,
                )
            except EventBusOperationError:
                return False
            if result.disposition is not AcknowledgementDisposition.ACKNOWLEDGED:
                return False
            pending.transport_acknowledged = True

        if self._acknowledgement_observer is not None:
            try:
                await self._acknowledgement_observer.after_acknowledgement(
                    pending.delivery,
                    pending.disposition,
                )
            except Exception:
                return False
        self._pending_acknowledgement = None
        return True

    async def run(self) -> None:
        """Poll responsively and process bounded, partition-fenced deliveries."""

        self._run_loop = asyncio.get_running_loop()
        listener_setter = getattr(self._consumer, "set_revocation_listener", None)
        if callable(listener_setter):
            listener_setter(self._deliveries_revoked)

        try:
            while not self._stopping.is_set():
                self._raise_completed_task_failures()
                if self._permanently_parked:
                    raise ConsumerRecoveryRequired("CONSUMER_QUARANTINE_RECOVERY_REQUIRED")

                if len(self._active_tasks) >= self._maximum_concurrency:
                    callback_service = getattr(self._consumer, "service_callbacks", None)
                    if callable(callback_service):
                        await asyncio.to_thread(
                            callback_service,
                            timeout_seconds=min(self._poll_timeout_seconds, 0.25),
                        )
                    await self._wait_for_progress(self._idle_delay_seconds)
                    continue

                delivery = await asyncio.to_thread(
                    self._consumer.poll,
                    timeout_seconds=min(self._poll_timeout_seconds, 0.25),
                )
                if delivery is None:
                    await self._wait_for_progress(self._idle_delay_seconds)
                    continue

                task = asyncio.create_task(self._process_concurrent_delivery(delivery))
                self._active_tasks[delivery.handle.token] = task
        finally:
            self._run_loop = None

    def _deliveries_revoked(self, handles: tuple[DeliveryHandle, ...]) -> None:
        """Marshal native rebalance notifications onto the worker event loop."""

        loop = self._run_loop
        if loop is not None:
            loop.call_soon_threadsafe(self._cancel_revoked_deliveries, handles)

    def _cancel_revoked_deliveries(self, handles: tuple[DeliveryHandle, ...]) -> None:
        for handle in handles:
            task = self._active_tasks.get(handle.token)
            if task is not None:
                task.cancel()

    def _raise_completed_task_failures(self) -> None:
        for token, task in tuple(self._active_tasks.items()):
            if not task.done():
                continue
            self._active_tasks.pop(token, None)
            if task.cancelled():
                continue
            failure = task.exception()
            if failure is not None:
                raise failure

    async def _wait_for_progress(self, timeout_seconds: float) -> None:
        if timeout_seconds <= 0:
            await asyncio.sleep(0)
            return
        stop_waiter = asyncio.create_task(self._stopping.wait())
        done, _ = await asyncio.wait(
            (*self._active_tasks.values(), stop_waiter),
            timeout=timeout_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if stop_waiter not in done:
            stop_waiter.cancel()
            with suppress(asyncio.CancelledError):
                await stop_waiter

    async def _process_concurrent_delivery(self, delivery: EventBusDelivery) -> None:
        fingerprint = _delivery_fingerprint(delivery)
        try:
            try:
                disposition = await self._handler.handle(delivery)
            except asyncio.CancelledError:
                raise
            except Exception:
                await self._handle_concurrent_retryable(
                    delivery,
                    fingerprint=fingerprint,
                    safe_failure_code="PROCESSING_EXCEPTION_RETRY_EXHAUSTED",
                )
                return

            if disposition in _ACKNOWLEDGE_DISPOSITIONS:
                self._concurrent_retry_attempts.pop(fingerprint, None)
                await self._acknowledge_concurrent(delivery, disposition)
            elif disposition is DeliveryHandlingDisposition.RETRYABLE:
                await self._handle_concurrent_retryable(
                    delivery,
                    fingerprint=fingerprint,
                    safe_failure_code="PROCESSING_RETRY_EXHAUSTED",
                )
            else:
                self._concurrent_retry_attempts.pop(fingerprint, None)
                await asyncio.to_thread(
                    self._consumer.reject,
                    delivery.handle,
                    RejectionClassification.PERMANENT,
                )
                self._permanently_parked = True
        except EventBusOperationError as exc:
            if exc.reason_code != "DELIVERY_REVOKED":
                raise

    async def _handle_concurrent_retryable(
        self,
        delivery: EventBusDelivery,
        *,
        fingerprint: str,
        safe_failure_code: str,
    ) -> None:
        attempts = self._concurrent_retry_attempts.get(fingerprint, 0) + 1
        self._concurrent_retry_attempts[fingerprint] = attempts
        if attempts < self._maximum_processing_attempts:
            await asyncio.to_thread(
                self._consumer.reject,
                delivery.handle,
                RejectionClassification.RETRYABLE,
            )
            if self._retry_delay_seconds:
                await asyncio.sleep(self._retry_delay_seconds)
            return

        self._concurrent_retry_attempts.pop(fingerprint, None)
        try:
            confirmed = await self._retry_exhaustion_handler.quarantine_retry_exhaustion(
                delivery,
                safe_failure_code=safe_failure_code,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            confirmed = False
        if confirmed:
            await self._acknowledge_concurrent(
                delivery,
                DeliveryHandlingDisposition.DURABLY_QUARANTINED,
            )
            return
        await asyncio.to_thread(
            self._consumer.reject,
            delivery.handle,
            RejectionClassification.PERMANENT,
        )
        self._permanently_parked = True

    async def _acknowledge_concurrent(
        self,
        delivery: EventBusDelivery,
        disposition: DeliveryHandlingDisposition,
    ) -> None:
        transport_acknowledged = False
        while True:
            if not transport_acknowledged:
                try:
                    result = await asyncio.to_thread(
                        self._consumer.acknowledge,
                        delivery.handle,
                    )
                except EventBusOperationError as exc:
                    if exc.reason_code == "DELIVERY_REVOKED":
                        return
                    result = None
                if (
                    result is not None
                    and result.disposition is AcknowledgementDisposition.ACKNOWLEDGED
                ):
                    transport_acknowledged = True
            if transport_acknowledged:
                if self._acknowledgement_observer is None:
                    return
                try:
                    await self._acknowledgement_observer.after_acknowledgement(
                        delivery,
                        disposition,
                    )
                    return
                except asyncio.CancelledError:
                    raise
                except Exception:
                    pass
            if self._idle_delay_seconds:
                await asyncio.sleep(self._idle_delay_seconds)

    async def stop(self) -> None:
        """Stop future intake while allowing admitted work to reach disposition."""

        self._stopping.set()
        await asyncio.to_thread(self._consumer.stop_intake)

    async def close(self, *, timeout_seconds: float) -> bool:
        """Stop intake and close the consumer inside one caller-supplied bound."""

        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        deadline = monotonic() + timeout_seconds
        try:
            await asyncio.wait_for(self.stop(), timeout=timeout_seconds)
        except TimeoutError:
            return False

        remaining = deadline - monotonic()
        if remaining <= 0:
            return False
        active = tuple(self._active_tasks.values())
        if active:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*active, return_exceptions=True),
                    timeout=remaining,
                )
            except TimeoutError:
                for task in active:
                    task.cancel()
                return False

        remaining = deadline - monotonic()
        if remaining <= 0:
            return False
        try:
            await asyncio.wait_for(self._iteration_lock.acquire(), timeout=remaining)
        except TimeoutError:
            return False

        try:
            while self._pending_acknowledgement is not None:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return False
                try:
                    completed = await asyncio.wait_for(
                        self._acknowledge_pending(),
                        timeout=remaining,
                    )
                except Exception:
                    return False
                if completed:
                    break
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return False
                with suppress(TimeoutError):
                    await asyncio.wait_for(
                        asyncio.sleep(self._idle_delay_seconds),
                        timeout=remaining,
                    )

            remaining = deadline - monotonic()
            if remaining <= 0:
                return False
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._consumer.close,
                        timeout_seconds=remaining,
                    ),
                    timeout=remaining,
                )
            except TimeoutError:
                return False
            return result.drained and not self._permanently_parked
        finally:
            self._iteration_lock.release()


def _delivery_fingerprint(delivery: EventBusDelivery) -> str:
    """Create bounded process-local retry continuity evidence, not identity."""

    digest = hashlib.sha256()
    for value in (
        delivery.subscription.identity.encode("utf-8"),
        delivery.subscription.channel.value.encode("ascii"),
        delivery.ordering_key or b"",
        delivery.value or b"",
    ):
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)
    for header in delivery.headers:
        name = header.name.encode("utf-8")
        value = header.value or b""
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)
    return digest.hexdigest()
