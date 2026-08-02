"""Bounded Kafka-protocol publisher behind the platform Event Bus port."""

from threading import Event, Lock
from time import monotonic

from confluent_kafka import KafkaError, KafkaException, Message, Producer

from ai_platform.adapters.event_bus.security import KafkaSecurityConfig
from ai_platform.adapters.event_bus.topics import KafkaTopicMapping
from ai_platform.ports.event_bus import (
    EventBusOperationError,
    OutboundMessage,
    PublicationDisposition,
    PublicationResult,
    ShutdownResult,
)


class KafkaEventPublisher:
    """Publish exact outbox bytes and classify the specific delivery attempt."""

    def __init__(
        self,
        *,
        bootstrap_servers: str,
        client_id: str,
        topic_mapping: KafkaTopicMapping,
        security: KafkaSecurityConfig,
    ) -> None:
        client_config: dict[str, object] = {
            "bootstrap.servers": bootstrap_servers,
            "client.id": client_id,
            "enable.idempotence": True,
            "acks": "all",
            "max.in.flight.requests.per.connection": 5,
        }
        client_config.update(security.client_properties())
        try:
            self._producer = Producer(client_config)
        except KafkaException:
            raise EventBusOperationError("PRODUCER_START_FAILED", retryable=True) from None
        except ValueError:
            raise EventBusOperationError("PRODUCER_CONFIG_INVALID", retryable=False) from None
        self._topic_mapping = topic_mapping
        self._operation_lock = Lock()
        self._stopping = Event()

    def publish(self, message: OutboundMessage, *, timeout_seconds: float) -> PublicationResult:
        """Wait boundedly for this record's delivery report.

        Returning ``UNKNOWN`` means the record was handed to the client but a
        conclusive delivery report was not observed inside the bound. Recovery
        may therefore republish the same bytes, key, and message identity.
        """
        if timeout_seconds <= 0:
            return self._not_accepted("INVALID_TIMEOUT", retryable=False)
        if self._stopping.is_set():
            return self._not_accepted("PUBLISHER_STOPPED", retryable=True)

        deadline = monotonic() + timeout_seconds
        if not self._operation_lock.acquire(timeout=timeout_seconds):
            return self._not_accepted("PUBLISHER_BUSY", retryable=True)

        try:
            if self._stopping.is_set():
                return self._not_accepted("PUBLISHER_STOPPED", retryable=True)
            remaining = deadline - monotonic()
            if remaining <= 0:
                return self._not_accepted("PUBLISH_TIMEOUT_BEFORE_ATTEMPT", retryable=True)

            delivered = Event()
            delivery_error: list[KafkaError | None] = []

            def on_delivery(error: KafkaError | None, _message: Message) -> None:
                delivery_error.append(error)
                delivered.set()

            try:
                self._producer.produce(
                    self._topic_mapping.topic_for(message.logical_channel),
                    key=message.ordering_key.encode("utf-8"),
                    value=message.value,
                    headers=[(header.name, header.value) for header in message.headers],
                    on_delivery=on_delivery,
                )
            except BufferError:
                return self._not_accepted("LOCAL_QUEUE_FULL", retryable=True)
            except KafkaException:
                return self._not_accepted("PRODUCE_REJECTED", retryable=True)

            while not delivered.is_set():
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return PublicationResult(
                        disposition=PublicationDisposition.UNKNOWN,
                        retryable=True,
                        reason_code="DELIVERY_REPORT_TIMEOUT",
                    )
                try:
                    self._producer.poll(min(remaining, 0.05))
                except KafkaException:
                    return PublicationResult(
                        disposition=PublicationDisposition.UNKNOWN,
                        retryable=True,
                        reason_code="DELIVERY_POLL_FAILED",
                    )

            error = delivery_error[0]
            if error is None:
                return PublicationResult(
                    disposition=PublicationDisposition.ACKNOWLEDGED,
                    retryable=False,
                )
            return self._not_accepted("DELIVERY_REJECTED", retryable=error.retriable())
        finally:
            self._operation_lock.release()

    @staticmethod
    def _not_accepted(reason_code: str, *, retryable: bool) -> PublicationResult:
        return PublicationResult(
            disposition=PublicationDisposition.DEFINITIVELY_NOT_ACCEPTED,
            retryable=retryable,
            reason_code=reason_code,
        )

    def stop_accepting(self) -> None:
        """Prevent new records from entering the producer."""
        self._stopping.set()

    def close(self, *, timeout_seconds: float) -> ShutdownResult:
        """Stop intake and flush queued records within the caller's bound."""
        self.stop_accepting()
        if timeout_seconds <= 0:
            return ShutdownResult(drained=False)

        deadline = monotonic() + timeout_seconds
        if not self._operation_lock.acquire(timeout=timeout_seconds):
            return ShutdownResult(drained=False)
        try:
            remaining = max(0.0, deadline - monotonic())
            try:
                outstanding = self._producer.flush(remaining)
            except KafkaException:
                return ShutdownResult(drained=False)
            return ShutdownResult(drained=outstanding == 0)
        finally:
            self._operation_lock.release()
