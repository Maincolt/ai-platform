"""Kafka-protocol consumer behind the platform Event Bus port."""

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from threading import Event, Lock, Thread
from time import monotonic
from uuid import uuid4

from confluent_kafka import Consumer, KafkaException, Message, TopicPartition

from ai_platform.adapters.event_bus.security import KafkaSecurityConfig
from ai_platform.adapters.event_bus.topics import KafkaTopicMapping
from ai_platform.ports.event_bus import (
    AcknowledgementDisposition,
    AcknowledgementResult,
    DeliveryHandle,
    EventBusDelivery,
    EventBusOperationError,
    LogicalSubscription,
    RejectionClassification,
    ShutdownResult,
    TransportHeader,
)


@dataclass(slots=True)
class _PendingDelivery:
    handle: DeliveryHandle
    message: Message
    physical_topic: str
    partition: int
    offset: int
    assignment_generation: int
    permanently_parked: bool = False


@dataclass(frozen=True, slots=True)
class KafkaPendingDeliveryMetadata:
    """Broker-private source coordinates for one opaque pending handle."""

    subscription: LogicalSubscription
    physical_source: str
    partition: int
    offset: int


class KafkaOffsetCommitStatus(Enum):
    """Broker-private certainty about a consumer-group source position."""

    COMMITTED = "COMMITTED"
    NOT_COMMITTED = "NOT_COMMITTED"
    UNKNOWN = "UNKNOWN"


class KafkaEventConsumer:
    """Admit at most one record per assigned partition.

    Public delivery handles remain opaque. Internally each handle is fenced by
    the partition-assignment generation in which it was created, so work from
    a revoked assignment can never advance the replacement assignment.
    """

    def __init__(
        self,
        *,
        bootstrap_servers: str,
        client_id: str,
        group_id: str,
        subscription: LogicalSubscription,
        topic_mapping: KafkaTopicMapping,
        security: KafkaSecurityConfig,
        maximum_in_flight: int = 1,
    ) -> None:
        if maximum_in_flight < 1:
            raise ValueError("maximum_in_flight must be positive")
        self._subscription = subscription
        self._physical_topic = topic_mapping.topic_for(subscription.channel)
        client_config: dict[str, object] = {
            "bootstrap.servers": bootstrap_servers,
            "client.id": client_id,
            "group.id": group_id,
            "enable.auto.commit": False,
            "enable.auto.offset.store": False,
            "auto.offset.reset": "earliest",
        }
        client_config.update(security.client_properties())
        try:
            self._consumer = Consumer(client_config)
        except KafkaException:
            raise EventBusOperationError("CONSUMER_START_FAILED", retryable=True) from None
        except ValueError:
            raise EventBusOperationError("CONSUMER_CONFIG_INVALID", retryable=False) from None

        self._operation_lock = Lock()
        self._stopping = Event()
        self._closed = Event()
        self._pending: dict[str, _PendingDelivery] = {}
        self._active_partitions: dict[tuple[str, int], str] = {}
        self._partition_generations: dict[tuple[str, int], int] = {}
        self._next_assignment_generation = 0
        self._assignment_observed = False
        self._revoked_handle_tokens: set[str] = set()
        self._revoked_handle_order: deque[str] = deque()
        self._revocation_listener: Callable[[tuple[DeliveryHandle, ...]], None] | None = None
        self._maximum_in_flight = maximum_in_flight
        self._capacity_paused = False
        try:
            self._consumer.subscribe(
                [self._physical_topic],
                on_assign=self._on_assign,
                on_revoke=self._on_revoke,
            )
        except KafkaException:
            self._consumer.close()
            raise EventBusOperationError("CONSUMER_START_FAILED", retryable=True) from None

    def poll(self, *, timeout_seconds: float) -> EventBusDelivery | None:
        """Poll one record while no earlier delivery awaits disposition."""
        if timeout_seconds < 0:
            raise EventBusOperationError("INVALID_TIMEOUT", retryable=False)
        if self._stopping.is_set() or self._closed.is_set():
            return None
        if not self._operation_lock.acquire(timeout=timeout_seconds):
            raise EventBusOperationError("CONSUMER_BUSY", retryable=True)

        try:
            if self._stopping.is_set() or self._closed.is_set():
                return None
            if len(self._pending) >= self._maximum_in_flight:
                raise EventBusOperationError("DELIVERY_IN_FLIGHT", retryable=False)
            try:
                message = self._consumer.poll(timeout_seconds)
            except KafkaException:
                raise EventBusOperationError("CONSUME_FAILED", retryable=True) from None
            if message is None:
                return None

            error = message.error()
            if error is not None:
                self._stopping.set()
                raise EventBusOperationError("CONSUME_RECORD_ERROR", retryable=error.retriable())

            topic = message.topic()
            partition = message.partition()
            offset = message.offset()
            if (
                topic is None
                or topic != self._physical_topic
                or partition is None
                or offset is None
            ):
                self._stopping.set()
                raise EventBusOperationError("INVALID_TRANSPORT_METADATA", retryable=False)

            partition_key = (topic, partition)
            generation = self._partition_generations.get(partition_key, 0)
            if self._assignment_observed and generation == 0:
                self._stopping.set()
                raise EventBusOperationError("DELIVERY_OUTSIDE_ASSIGNMENT", retryable=False)
            if partition_key in self._active_partitions:
                self._stopping.set()
                raise EventBusOperationError("DELIVERY_IN_FLIGHT", retryable=False)

            handle = DeliveryHandle(token=uuid4().hex)
            self._pending[handle.token] = _PendingDelivery(
                handle=handle,
                message=message,
                physical_topic=topic,
                partition=partition,
                offset=offset,
                assignment_generation=generation,
            )
            self._active_partitions[partition_key] = handle.token
            try:
                self._consumer.pause([TopicPartition(topic, partition)])
                if len(self._pending) >= self._maximum_in_flight:
                    self._pause_for_capacity()
            except KafkaException:
                self._pending.pop(handle.token, None)
                self._active_partitions.pop(partition_key, None)
                raise EventBusOperationError("PARTITION_PAUSE_FAILED", retryable=True) from None
            headers = tuple(
                TransportHeader(
                    name=name,
                    value=value.encode("utf-8") if isinstance(value, str) else value,
                )
                for name, value in (message.headers() or [])
            )
            raw_key = message.key()
            ordering_key = raw_key.encode("utf-8") if isinstance(raw_key, str) else raw_key
            raw_value = message.value()
            value = raw_value.encode("utf-8") if isinstance(raw_value, str) else raw_value
            return EventBusDelivery(
                handle=handle,
                subscription=self._subscription,
                ordering_key=ordering_key,
                value=value,
                headers=headers,
            )
        finally:
            self._operation_lock.release()

    def acknowledge(self, handle: DeliveryHandle) -> AcknowledgementResult:
        """Synchronously commit only the explicitly completed delivery."""
        with self._operation_lock:
            pending = self._require_pending(handle)
            if not self._is_current(pending):
                self._invalidate_pending(pending)
                raise EventBusOperationError("DELIVERY_REVOKED", retryable=False)
            try:
                self._consumer.commit(message=pending.message, asynchronous=False)
            except KafkaException:
                return AcknowledgementResult(
                    disposition=AcknowledgementDisposition.UNKNOWN,
                    reason_code="OFFSET_COMMIT_FAILED",
                )
            self._complete_pending(pending)
            return AcknowledgementResult(
                disposition=AcknowledgementDisposition.ACKNOWLEDGED,
            )

    def reject(self, handle: DeliveryHandle, classification: RejectionClassification) -> None:
        """Reject without committing source progress.

        Retryable work is rewound for redelivery. Permanent work stays parked,
        blocking further intake; after durable quarantine confirmation the
        owning coordinator may acknowledge the same handle. The adapter itself
        never treats rejection as permission to advance an offset.
        """
        with self._operation_lock:
            pending = self._require_pending(handle)
            if not self._is_current(pending):
                self._invalidate_pending(pending)
                raise EventBusOperationError("DELIVERY_REVOKED", retryable=False)
            if classification is RejectionClassification.PERMANENT:
                pending.permanently_parked = True
                return
            if pending.permanently_parked:
                raise EventBusOperationError("DELIVERY_PERMANENTLY_PARKED", retryable=False)
            try:
                self._consumer.seek(
                    TopicPartition(
                        pending.physical_topic,
                        pending.partition,
                        pending.offset,
                    )
                )
            except KafkaException:
                raise EventBusOperationError("REDELIVERY_SEEK_FAILED", retryable=True) from None
            self._complete_pending(pending)

    def _require_pending(self, handle: DeliveryHandle) -> _PendingDelivery:
        pending = self._pending.get(handle.token)
        if pending is None:
            if handle.token in self._revoked_handle_tokens:
                raise EventBusOperationError("DELIVERY_REVOKED", retryable=False)
            raise EventBusOperationError("UNKNOWN_DELIVERY_HANDLE", retryable=False)
        return pending

    def _is_current(self, pending: _PendingDelivery) -> bool:
        partition_key = (pending.physical_topic, pending.partition)
        return self._partition_generations.get(partition_key, 0) == pending.assignment_generation

    def _complete_pending(self, pending: _PendingDelivery) -> None:
        partition_key = (pending.physical_topic, pending.partition)
        self._pending.pop(pending.handle.token, None)
        self._active_partitions.pop(partition_key, None)
        if self._is_current(pending) and not self._stopping.is_set():
            try:
                if self._capacity_paused and len(self._pending) < self._maximum_in_flight:
                    self._resume_after_capacity()
                else:
                    self._consumer.resume([TopicPartition(*partition_key)])
            except KafkaException:
                self._stopping.set()
                raise EventBusOperationError("PARTITION_RESUME_FAILED", retryable=True) from None

    def _invalidate_pending(self, pending: _PendingDelivery) -> None:
        self._pending.pop(pending.handle.token, None)
        self._active_partitions.pop((pending.physical_topic, pending.partition), None)
        self._remember_revoked_handle(pending.handle.token)

    def _remember_revoked_handle(self, token: str) -> None:
        if token in self._revoked_handle_tokens:
            return
        self._revoked_handle_tokens.add(token)
        self._revoked_handle_order.append(token)
        if len(self._revoked_handle_order) > 4096:
            expired = self._revoked_handle_order.popleft()
            self._revoked_handle_tokens.discard(expired)

    def set_revocation_listener(
        self,
        listener: Callable[[tuple[DeliveryHandle, ...]], None],
    ) -> None:
        """Install the worker's opaque-handle cancellation notification."""

        with self._operation_lock:
            self._revocation_listener = listener

    def service_callbacks(self, *, timeout_seconds: float) -> None:
        """Serve group callbacks while capacity-paused without admitting work."""

        if timeout_seconds < 0:
            raise EventBusOperationError("INVALID_TIMEOUT", retryable=False)
        if self._stopping.is_set() or self._closed.is_set():
            return
        if not self._operation_lock.acquire(timeout=timeout_seconds):
            raise EventBusOperationError("CONSUMER_BUSY", retryable=True)
        try:
            try:
                message = self._consumer.poll(timeout_seconds)
            except KafkaException:
                raise EventBusOperationError("CONSUME_FAILED", retryable=True) from None
            if message is not None:
                self._stopping.set()
                raise EventBusOperationError("CAPACITY_PAUSE_VIOLATION", retryable=False)
        finally:
            self._operation_lock.release()

    def _pause_for_capacity(self) -> None:
        assigned = [
            TopicPartition(topic, partition) for topic, partition in self._partition_generations
        ]
        if assigned:
            self._consumer.pause(assigned)
        self._capacity_paused = True

    def _resume_after_capacity(self) -> None:
        resumable = [
            TopicPartition(topic, partition)
            for topic, partition in self._partition_generations
            if (topic, partition) not in self._active_partitions
        ]
        if resumable:
            self._consumer.resume(resumable)
        self._capacity_paused = False

    def _on_assign(self, _consumer: Consumer, partitions: list[TopicPartition]) -> None:
        """Record a new assignment epoch; invoked synchronously by ``poll``."""

        self._assignment_observed = True
        self._next_assignment_generation += 1
        generation = self._next_assignment_generation
        reassigned: list[DeliveryHandle] = []
        for partition in partitions:
            if partition.topic == self._physical_topic and partition.partition >= 0:
                partition_key = (partition.topic, partition.partition)
                token = self._active_partitions.get(partition_key)
                pending = self._pending.get(token) if token is not None else None
                if pending is not None:
                    reassigned.append(pending.handle)
                    self._invalidate_pending(pending)
                self._partition_generations[partition_key] = generation
        if self._capacity_paused:
            self._consumer.pause(partitions)
        listener = self._revocation_listener
        if listener is not None and reassigned:
            listener(tuple(reassigned))

    def _on_revoke(self, _consumer: Consumer, partitions: list[TopicPartition]) -> None:
        """Fence and report all work owned by the revoked assignment."""

        revoked_keys = {
            (partition.topic, partition.partition)
            for partition in partitions
            if partition.topic == self._physical_topic and partition.partition >= 0
        }
        revoked: list[DeliveryHandle] = []
        for partition_key in revoked_keys:
            self._partition_generations.pop(partition_key, None)
            token = self._active_partitions.get(partition_key)
            if token is None:
                continue
            pending = self._pending.get(token)
            if pending is not None:
                revoked.append(pending.handle)
                self._invalidate_pending(pending)
        if self._capacity_paused and len(self._pending) < self._maximum_in_flight:
            self._resume_after_capacity()
        listener = self._revocation_listener
        if listener is not None and revoked:
            listener(tuple(revoked))

    def pending_delivery_metadata(self, handle: DeliveryHandle) -> KafkaPendingDeliveryMetadata:
        """Resolve broker coordinates without adding them to the public delivery."""

        with self._operation_lock:
            pending = self._require_pending(handle)
            return KafkaPendingDeliveryMetadata(
                subscription=self._subscription,
                physical_source=pending.physical_topic,
                partition=pending.partition,
                offset=pending.offset,
            )

    def source_offset_commit_status(
        self,
        *,
        physical_source: str,
        partition: int,
        offset: int,
        timeout_seconds: float,
    ) -> KafkaOffsetCommitStatus:
        """Compare one source record with this consumer group's committed position."""

        if (
            physical_source != self._physical_topic
            or partition < 0
            or offset < 0
            or timeout_seconds <= 0
        ):
            raise EventBusOperationError("INVALID_SOURCE_POSITION_QUERY", retryable=False)
        if not self._operation_lock.acquire(timeout=timeout_seconds):
            return KafkaOffsetCommitStatus.UNKNOWN
        try:
            try:
                positions = self._consumer.committed(
                    [TopicPartition(physical_source, partition)],
                    timeout=timeout_seconds,
                )
            except KafkaException:
                return KafkaOffsetCommitStatus.UNKNOWN
            if len(positions) != 1:
                return KafkaOffsetCommitStatus.UNKNOWN
            position = positions[0]
            if position.topic != physical_source or position.partition != partition:
                return KafkaOffsetCommitStatus.UNKNOWN
            if position.offset > offset:
                return KafkaOffsetCommitStatus.COMMITTED
            return KafkaOffsetCommitStatus.NOT_COMMITTED
        finally:
            self._operation_lock.release()

    def stop_intake(self) -> None:
        """Prevent any subsequent poll from admitting new work."""
        self._stopping.set()

    def close(self, *, timeout_seconds: float) -> ShutdownResult:
        """Bound caller wait even if the native client's close stalls."""
        self.stop_intake()
        if timeout_seconds <= 0:
            return ShutdownResult(drained=False)

        deadline = monotonic() + timeout_seconds
        if not self._operation_lock.acquire(timeout=timeout_seconds):
            return ShutdownResult(drained=False)
        try:
            had_pending = bool(self._pending)
            close_failed = Event()

            def close_native_consumer() -> None:
                try:
                    self._consumer.close()
                except KafkaException:
                    close_failed.set()

            close_thread = Thread(target=close_native_consumer, daemon=True)
            close_thread.start()
            close_thread.join(max(0.0, deadline - monotonic()))
            finished = not close_thread.is_alive()
            if finished:
                self._closed.set()
                self._pending.clear()
                self._active_partitions.clear()
            return ShutdownResult(
                drained=finished and not close_failed.is_set() and not had_pending,
            )
        finally:
            self._operation_lock.release()
