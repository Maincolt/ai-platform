"""Broker-free conformance tests for the Kafka-protocol Event Bus adapter.

These tests prove the platform boundary and client-call semantics. Real broker
acknowledgment, redelivery, ordering, rebalance, and durability remain Phase 7
integration-test responsibilities.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from confluent_kafka import KafkaError, KafkaException, Message, TopicPartition

from ai_platform.adapters.event_bus.consumer import KafkaEventConsumer
from ai_platform.adapters.event_bus.producer import KafkaEventPublisher
from ai_platform.adapters.event_bus.security import (
    KafkaSecurityConfig,
    KafkaSecurityConfigurationError,
    KafkaSecurityProtocol,
)
from ai_platform.adapters.event_bus.topics import (
    KafkaTopicMapping,
    TopicBinding,
    TopicMappingError,
    default_topic_mapping,
)
from ai_platform.ports.event_bus import (
    AcknowledgementDisposition,
    DeliveryHandle,
    EventBusOperationError,
    LogicalChannel,
    LogicalSubscription,
    OutboundMessage,
    PublicationDisposition,
    RejectionClassification,
    TransportHeader,
)

DeliveryCallback = Callable[[KafkaError | None, Message], None]


def _mapping() -> KafkaTopicMapping:
    return default_topic_mapping(environment="dev")


def _security(username: str = "orchestrator") -> KafkaSecurityConfig:
    return KafkaSecurityConfig(
        security_protocol=KafkaSecurityProtocol.SASL_SSL,
        username=username,
        password=f"{username}-secret",
        ca_file="/run/secrets/kafka-ca.pem",
    )


def _subscription() -> LogicalSubscription:
    return LogicalSubscription(
        identity="agent-command-handler-v1", channel=LogicalChannel.TASK_COMMANDS
    )


def _outbound(value: bytes = b'{"message_id":"msg-1"}') -> OutboundMessage:
    return OutboundMessage(
        logical_channel=LogicalChannel.TASK_COMMANDS,
        message_id="msg-1",
        ordering_key="01900000-0000-7000-8000-000000000001",
        value=value,
        headers=(TransportHeader(name="traceparent", value=b"safe"),),
    )


def _complete_during_produce(producer: MagicMock, error: KafkaError | None = None) -> None:
    def produce_side_effect(*_args: object, **kwargs: object) -> None:
        callback = cast(DeliveryCallback, kwargs["on_delivery"])
        callback(error, cast(Message, MagicMock()))

    producer.produce.side_effect = produce_side_effect


def _complete_during_poll(producer: MagicMock, error: KafkaError | None = None) -> None:
    callbacks: list[DeliveryCallback] = []

    def produce_side_effect(*_args: object, **kwargs: object) -> None:
        callbacks.append(cast(DeliveryCallback, kwargs["on_delivery"]))

    def poll_side_effect(_timeout: float) -> int:
        callbacks[0](error, cast(Message, MagicMock()))
        return 1

    producer.produce.side_effect = produce_side_effect
    producer.poll.side_effect = poll_side_effect


def _consumer_message(*, offset: int = 42) -> MagicMock:
    message = MagicMock(spec=Message)
    message.error.return_value = None
    message.value.return_value = b'{"message_id":"msg-1"}'
    message.key.return_value = b"workflow-1"
    message.headers.return_value = [("traceparent", b"safe")]
    message.topic.return_value = "ai-platform.dev.task-commands.v1"
    message.partition.return_value = 2
    message.offset.return_value = offset
    return message


def test_default_topic_mapping_resolves_both_logical_channels() -> None:
    mapping = _mapping()

    assert mapping.topic_for(LogicalChannel.TASK_COMMANDS) == ("ai-platform.dev.task-commands.v1")
    assert mapping.quarantine_topic_for(LogicalChannel.TASK_OUTCOMES) == (
        "ai-platform.dev.task-outcomes.v1.quarantine"
    )


def test_topic_mapping_rejects_missing_or_duplicate_resources() -> None:
    one_binding = TopicBinding(
        logical_channel=LogicalChannel.TASK_COMMANDS,
        topic="commands",
        quarantine_topic="commands.quarantine",
    )
    with pytest.raises(TopicMappingError, match="MISSING_LOGICAL_CHANNEL"):
        KafkaTopicMapping([one_binding])

    with pytest.raises(TopicMappingError, match="INVALID_ENVIRONMENT"):
        default_topic_mapping(environment="../unsafe")


def test_security_configuration_is_validated_and_redacted() -> None:
    security = _security()

    rendered = repr(security)
    assert "orchestrator" not in rendered
    assert "orchestrator-secret" not in rendered
    assert "/run/secrets/kafka-ca.pem" not in rendered
    assert "<redacted>" in rendered

    with pytest.raises(KafkaSecurityConfigurationError, match="EMPTY_USERNAME") as error:
        KafkaSecurityConfig(
            security_protocol=KafkaSecurityProtocol.SASL_SSL,
            username="",
            password="do-not-disclose",
        )
    assert "do-not-disclose" not in str(error.value)

    with pytest.raises(KafkaSecurityConfigurationError, match="EMPTY_PASSWORD"):
        KafkaSecurityConfig(
            security_protocol=KafkaSecurityProtocol.SASL_SSL,
            username="orchestrator",
            password="  ",
        )
    with pytest.raises(KafkaSecurityConfigurationError, match="EMPTY_CA_FILE"):
        KafkaSecurityConfig(
            security_protocol=KafkaSecurityProtocol.SASL_SSL,
            username="orchestrator",
            password="secret",
            ca_file="",
        )
    with pytest.raises(KafkaSecurityConfigurationError, match="INVALID_SECURITY_PROTOCOL"):
        KafkaSecurityConfig(
            security_protocol=cast(KafkaSecurityProtocol, "SASL_PLAINTEXT"),
            username="orchestrator",
            password="secret",
        )


def test_plaintext_security_requires_explicit_local_development_classification() -> None:
    security = KafkaSecurityConfig(
        security_protocol=KafkaSecurityProtocol.LOCAL_DEVELOPMENT_SASL_PLAINTEXT,
        username="local-orchestrator",
        password="local-only-secret",
    )

    properties = security.client_properties()
    assert properties["security.protocol"] == "SASL_PLAINTEXT"
    assert properties["sasl.mechanism"] == "SCRAM-SHA-256"
    assert "ssl.ca.location" not in properties

    with pytest.raises(KafkaSecurityConfigurationError, match="CA_FILE_REQUIRES_TLS"):
        KafkaSecurityConfig(
            security_protocol=KafkaSecurityProtocol.LOCAL_DEVELOPMENT_SASL_PLAINTEXT,
            username="local-orchestrator",
            password="local-only-secret",
            ca_file="/not-used.pem",
        )


@patch("ai_platform.adapters.event_bus.producer.Producer")
def test_publish_preserves_exact_bytes_key_headers_and_waits_for_ack(
    mock_producer_cls: MagicMock,
) -> None:
    native_producer = MagicMock()
    _complete_during_poll(native_producer)
    mock_producer_cls.return_value = native_producer
    publisher = KafkaEventPublisher(
        bootstrap_servers="broker:9092",
        client_id="orchestrator",
        topic_mapping=_mapping(),
        security=_security(),
    )
    immutable_bytes = b'{ "intentionally" : "not-reserialized" }'

    result = publisher.publish(_outbound(immutable_bytes), timeout_seconds=1.0)

    assert result.disposition is PublicationDisposition.ACKNOWLEDGED
    native_producer.produce.assert_called_once()
    args, kwargs = native_producer.produce.call_args
    assert args[0] == "ai-platform.dev.task-commands.v1"
    assert kwargs["key"] == b"01900000-0000-7000-8000-000000000001"
    assert kwargs["value"] == immutable_bytes
    assert kwargs["headers"] == [("traceparent", b"safe")]
    native_producer.poll.assert_called_once()


@patch("ai_platform.adapters.event_bus.producer.Producer")
def test_publisher_uses_idempotence_and_strong_acknowledgement(
    mock_producer_cls: MagicMock,
) -> None:
    KafkaEventPublisher(
        bootstrap_servers="broker:9092",
        client_id="orchestrator",
        topic_mapping=_mapping(),
        security=_security(),
    )

    config = mock_producer_cls.call_args.args[0]
    assert config["enable.idempotence"] is True
    assert config["acks"] == "all"
    assert config["max.in.flight.requests.per.connection"] == 5
    assert config["security.protocol"] == "SASL_SSL"
    assert config["sasl.mechanism"] == "SCRAM-SHA-256"
    assert config["sasl.username"] == "orchestrator"
    assert config["sasl.password"] == "orchestrator-secret"
    assert config["ssl.ca.location"] == "/run/secrets/kafka-ca.pem"


@patch("ai_platform.adapters.event_bus.producer.Producer")
def test_native_startup_error_does_not_disclose_credentials(
    mock_producer_cls: MagicMock,
) -> None:
    mock_producer_cls.side_effect = KafkaException("orchestrator-secret")

    with pytest.raises(EventBusOperationError, match="PRODUCER_START_FAILED") as error:
        KafkaEventPublisher(
            bootstrap_servers="broker:9092",
            client_id="orchestrator",
            topic_mapping=_mapping(),
            security=_security(),
        )

    assert "orchestrator-secret" not in str(error.value)
    assert "orchestrator-secret" not in repr(error.value)
    assert error.value.__cause__ is None


@patch("ai_platform.adapters.event_bus.producer.Producer")
def test_delivery_report_failure_is_definitively_not_accepted(
    mock_producer_cls: MagicMock,
) -> None:
    native_producer = MagicMock()
    error = MagicMock(spec=KafkaError)
    error.retriable.return_value = False
    _complete_during_produce(native_producer, cast(KafkaError, error))
    mock_producer_cls.return_value = native_producer
    publisher = KafkaEventPublisher(
        bootstrap_servers="broker:9092",
        client_id="orchestrator",
        topic_mapping=_mapping(),
        security=_security(),
    )

    result = publisher.publish(_outbound(), timeout_seconds=1.0)

    assert result.disposition is PublicationDisposition.DEFINITIVELY_NOT_ACCEPTED
    assert result.reason_code == "DELIVERY_REJECTED"
    assert result.retryable is False


@patch("ai_platform.adapters.event_bus.producer.Producer")
def test_local_queue_rejection_is_definitively_not_accepted(
    mock_producer_cls: MagicMock,
) -> None:
    native_producer = MagicMock()
    native_producer.produce.side_effect = BufferError("sensitive native detail")
    mock_producer_cls.return_value = native_producer
    publisher = KafkaEventPublisher(
        bootstrap_servers="broker:9092",
        client_id="orchestrator",
        topic_mapping=_mapping(),
        security=_security(),
    )

    result = publisher.publish(_outbound(), timeout_seconds=1.0)

    assert result.disposition is PublicationDisposition.DEFINITIVELY_NOT_ACCEPTED
    assert result.reason_code == "LOCAL_QUEUE_FULL"
    assert "sensitive" not in str(result)


@patch("ai_platform.adapters.event_bus.producer.Producer")
def test_missing_delivery_report_is_unknown_not_rejected(
    mock_producer_cls: MagicMock,
) -> None:
    mock_producer_cls.return_value = MagicMock()
    publisher = KafkaEventPublisher(
        bootstrap_servers="broker:9092",
        client_id="orchestrator",
        topic_mapping=_mapping(),
        security=_security(),
    )

    result = publisher.publish(_outbound(), timeout_seconds=0.001)

    assert result.disposition is PublicationDisposition.UNKNOWN
    assert result.reason_code == "DELIVERY_REPORT_TIMEOUT"


@patch("ai_platform.adapters.event_bus.producer.Producer")
def test_poll_failure_after_queueing_is_unknown(mock_producer_cls: MagicMock) -> None:
    native_producer = MagicMock()
    native_producer.poll.side_effect = KafkaException(MagicMock())
    mock_producer_cls.return_value = native_producer
    publisher = KafkaEventPublisher(
        bootstrap_servers="broker:9092",
        client_id="orchestrator",
        topic_mapping=_mapping(),
        security=_security(),
    )

    result = publisher.publish(_outbound(), timeout_seconds=1.0)

    assert result.disposition is PublicationDisposition.UNKNOWN
    assert result.reason_code == "DELIVERY_POLL_FAILED"


@patch("ai_platform.adapters.event_bus.producer.Producer")
def test_stopped_publisher_rejects_before_native_produce(mock_producer_cls: MagicMock) -> None:
    native_producer = MagicMock()
    mock_producer_cls.return_value = native_producer
    publisher = KafkaEventPublisher(
        bootstrap_servers="broker:9092",
        client_id="orchestrator",
        topic_mapping=_mapping(),
        security=_security(),
    )
    publisher.stop_accepting()

    result = publisher.publish(_outbound(), timeout_seconds=1.0)

    assert result.disposition is PublicationDisposition.DEFINITIVELY_NOT_ACCEPTED
    assert result.reason_code == "PUBLISHER_STOPPED"
    native_producer.produce.assert_not_called()


@patch("ai_platform.adapters.event_bus.producer.Producer")
def test_publisher_close_reports_whether_flush_drained(mock_producer_cls: MagicMock) -> None:
    native_producer = MagicMock()
    native_producer.flush.return_value = 1
    mock_producer_cls.return_value = native_producer
    publisher = KafkaEventPublisher(
        bootstrap_servers="broker:9092",
        client_id="orchestrator",
        topic_mapping=_mapping(),
        security=_security(),
    )

    assert publisher.close(timeout_seconds=0.1).drained is False


def _make_consumer(
    mock_consumer_cls: MagicMock,
    native_consumer: MagicMock,
    *,
    maximum_in_flight: int = 1,
) -> KafkaEventConsumer:
    mock_consumer_cls.return_value = native_consumer
    return KafkaEventConsumer(
        bootstrap_servers="broker:9092",
        client_id="test-agent",
        group_id="agent-command-consumer",
        subscription=_subscription(),
        topic_mapping=_mapping(),
        security=_security("test-agent"),
        maximum_in_flight=maximum_in_flight,
    )


@patch("ai_platform.adapters.event_bus.consumer.Consumer")
def test_consumer_uses_logical_binding_and_disables_automatic_progress(
    mock_consumer_cls: MagicMock,
) -> None:
    native_consumer = MagicMock()
    _make_consumer(mock_consumer_cls, native_consumer)

    config = mock_consumer_cls.call_args.args[0]
    assert config["enable.auto.commit"] is False
    assert config["enable.auto.offset.store"] is False
    assert config["security.protocol"] == "SASL_SSL"
    assert config["sasl.mechanism"] == "SCRAM-SHA-256"
    assert config["sasl.username"] == "test-agent"
    assert config["sasl.password"] == "test-agent-secret"
    native_consumer.subscribe.assert_called_once()
    subscribe_args = native_consumer.subscribe.call_args
    assert subscribe_args.args == (["ai-platform.dev.task-commands.v1"],)
    assert callable(subscribe_args.kwargs["on_assign"])
    assert callable(subscribe_args.kwargs["on_revoke"])


@patch("ai_platform.adapters.event_bus.consumer.Consumer")
def test_delivery_exposes_logical_values_and_opaque_handle_only(
    mock_consumer_cls: MagicMock,
) -> None:
    native_consumer = MagicMock()
    native_consumer.poll.return_value = _consumer_message()
    consumer = _make_consumer(mock_consumer_cls, native_consumer, maximum_in_flight=2)

    delivery = consumer.poll(timeout_seconds=0.1)

    assert delivery is not None
    assert delivery.subscription == _subscription()
    assert delivery.ordering_key == b"workflow-1"
    assert delivery.value == b'{"message_id":"msg-1"}'
    assert not hasattr(delivery, "topic")
    assert not hasattr(delivery, "partition")
    assert not hasattr(delivery, "offset")


@patch("ai_platform.adapters.event_bus.consumer.Consumer")
def test_consumer_refuses_later_admission_from_the_same_partition(
    mock_consumer_cls: MagicMock,
) -> None:
    native_consumer = MagicMock()
    native_consumer.poll.return_value = _consumer_message()
    consumer = _make_consumer(mock_consumer_cls, native_consumer, maximum_in_flight=2)
    assert consumer.poll(timeout_seconds=0.1) is not None

    with pytest.raises(EventBusOperationError, match="DELIVERY_IN_FLIGHT"):
        consumer.poll(timeout_seconds=0.1)

    assert native_consumer.poll.call_count == 2


@patch("ai_platform.adapters.event_bus.consumer.Consumer")
def test_consumer_admits_one_delivery_from_each_distinct_partition(
    mock_consumer_cls: MagicMock,
) -> None:
    first = _consumer_message()
    first.partition.return_value = 0
    second = _consumer_message()
    second.partition.return_value = 1
    native_consumer = MagicMock()
    native_consumer.poll.side_effect = [first, second]
    consumer = _make_consumer(mock_consumer_cls, native_consumer, maximum_in_flight=2)

    first_delivery = consumer.poll(timeout_seconds=0.1)
    second_delivery = consumer.poll(timeout_seconds=0.1)

    assert first_delivery is not None
    assert second_delivery is not None
    assert first_delivery.handle != second_delivery.handle
    assert native_consumer.pause.call_count == 2


@patch("ai_platform.adapters.event_bus.consumer.Consumer")
def test_revocation_fences_handle_and_notifies_worker_without_exposing_coordinates(
    mock_consumer_cls: MagicMock,
) -> None:
    native_consumer = MagicMock()
    native_consumer.poll.return_value = _consumer_message()
    consumer = _make_consumer(mock_consumer_cls, native_consumer)
    callbacks = native_consumer.subscribe.call_args.kwargs
    callbacks["on_assign"](
        native_consumer,
        [TopicPartition("ai-platform.dev.task-commands.v1", 2)],
    )
    delivery = consumer.poll(timeout_seconds=0.1)
    assert delivery is not None
    revoked: list[tuple[DeliveryHandle, ...]] = []
    consumer.set_revocation_listener(revoked.append)

    callbacks["on_revoke"](
        native_consumer,
        [TopicPartition("ai-platform.dev.task-commands.v1", 2)],
    )

    assert revoked == [(delivery.handle,)]
    with pytest.raises(EventBusOperationError, match="DELIVERY_REVOKED"):
        consumer.acknowledge(delivery.handle)
    native_consumer.commit.assert_not_called()


@patch("ai_platform.adapters.event_bus.consumer.Consumer")
def test_reassignment_uses_a_new_generation_and_cannot_revive_old_handle(
    mock_consumer_cls: MagicMock,
) -> None:
    native_consumer = MagicMock()
    native_consumer.poll.side_effect = [_consumer_message(), _consumer_message()]
    consumer = _make_consumer(mock_consumer_cls, native_consumer)
    callbacks = native_consumer.subscribe.call_args.kwargs
    partition = TopicPartition("ai-platform.dev.task-commands.v1", 2)
    callbacks["on_assign"](native_consumer, [partition])
    old_delivery = consumer.poll(timeout_seconds=0.1)
    assert old_delivery is not None
    callbacks["on_revoke"](native_consumer, [partition])
    callbacks["on_assign"](native_consumer, [partition])
    replacement = consumer.poll(timeout_seconds=0.1)
    assert replacement is not None

    with pytest.raises(EventBusOperationError, match="DELIVERY_REVOKED"):
        consumer.acknowledge(old_delivery.handle)
    assert consumer.acknowledge(replacement.handle).disposition is (
        AcknowledgementDisposition.ACKNOWLEDGED
    )
    native_consumer.commit.assert_called_once()


@patch("ai_platform.adapters.event_bus.consumer.Consumer")
def test_acknowledge_commits_only_the_explicit_delivery(
    mock_consumer_cls: MagicMock,
) -> None:
    native_message = _consumer_message()
    native_consumer = MagicMock()
    native_consumer.poll.return_value = native_message
    consumer = _make_consumer(mock_consumer_cls, native_consumer)
    delivery = consumer.poll(timeout_seconds=0.1)
    assert delivery is not None

    result = consumer.acknowledge(delivery.handle)

    assert result.disposition is AcknowledgementDisposition.ACKNOWLEDGED
    native_consumer.commit.assert_called_once_with(message=native_message, asynchronous=False)


@patch("ai_platform.adapters.event_bus.consumer.Consumer")
def test_failed_commit_is_unknown_and_keeps_delivery_pending(
    mock_consumer_cls: MagicMock,
) -> None:
    native_consumer = MagicMock()
    native_consumer.poll.return_value = _consumer_message()
    native_consumer.commit.side_effect = KafkaException(MagicMock())
    consumer = _make_consumer(mock_consumer_cls, native_consumer)
    delivery = consumer.poll(timeout_seconds=0.1)
    assert delivery is not None

    result = consumer.acknowledge(delivery.handle)

    assert result.disposition is AcknowledgementDisposition.UNKNOWN
    with pytest.raises(EventBusOperationError, match="DELIVERY_IN_FLIGHT"):
        consumer.poll(timeout_seconds=0.1)


@patch("ai_platform.adapters.event_bus.consumer.Consumer")
def test_retryable_rejection_rewinds_without_committing(mock_consumer_cls: MagicMock) -> None:
    native_consumer = MagicMock()
    native_consumer.poll.side_effect = [_consumer_message(), None]
    consumer = _make_consumer(mock_consumer_cls, native_consumer)
    delivery = consumer.poll(timeout_seconds=0.1)
    assert delivery is not None

    consumer.reject(delivery.handle, RejectionClassification.RETRYABLE)

    native_consumer.commit.assert_not_called()
    native_consumer.seek.assert_called_once()
    assert consumer.poll(timeout_seconds=0.1) is None


@patch("ai_platform.adapters.event_bus.consumer.Consumer")
def test_permanent_rejection_parks_until_quarantine_is_confirmed(
    mock_consumer_cls: MagicMock,
) -> None:
    native_consumer = MagicMock()
    native_message = _consumer_message()
    native_consumer.poll.return_value = native_message
    consumer = _make_consumer(mock_consumer_cls, native_consumer)
    delivery = consumer.poll(timeout_seconds=0.1)
    assert delivery is not None

    consumer.reject(delivery.handle, RejectionClassification.PERMANENT)
    with pytest.raises(EventBusOperationError, match="DELIVERY_IN_FLIGHT"):
        consumer.poll(timeout_seconds=0.1)
    with pytest.raises(EventBusOperationError, match="DELIVERY_PERMANENTLY_PARKED"):
        consumer.reject(delivery.handle, RejectionClassification.RETRYABLE)
    consumer.acknowledge(delivery.handle)

    native_consumer.commit.assert_called_once_with(message=native_message, asynchronous=False)


@patch("ai_platform.adapters.event_bus.consumer.Consumer")
def test_unknown_handle_never_advances_progress(mock_consumer_cls: MagicMock) -> None:
    native_consumer = MagicMock()
    native_consumer.poll.return_value = _consumer_message()
    consumer = _make_consumer(mock_consumer_cls, native_consumer)
    assert consumer.poll(timeout_seconds=0.1) is not None

    with pytest.raises(EventBusOperationError, match="UNKNOWN_DELIVERY_HANDLE"):
        consumer.acknowledge(DeliveryHandle(token="not-the-delivery"))

    native_consumer.commit.assert_not_called()


@patch("ai_platform.adapters.event_bus.consumer.Consumer")
def test_stop_intake_prevents_new_poll(mock_consumer_cls: MagicMock) -> None:
    native_consumer = MagicMock()
    consumer = _make_consumer(mock_consumer_cls, native_consumer)
    consumer.stop_intake()

    assert consumer.poll(timeout_seconds=0.1) is None
    native_consumer.poll.assert_not_called()


@patch("ai_platform.adapters.event_bus.consumer.Consumer")
def test_consumer_close_is_not_drained_with_unacknowledged_work(
    mock_consumer_cls: MagicMock,
) -> None:
    native_consumer = MagicMock()
    native_consumer.poll.return_value = _consumer_message()
    consumer = _make_consumer(mock_consumer_cls, native_consumer)
    assert consumer.poll(timeout_seconds=0.1) is not None

    result = consumer.close(timeout_seconds=1.0)

    assert result.drained is False
    native_consumer.commit.assert_not_called()
    native_consumer.close.assert_called_once()
