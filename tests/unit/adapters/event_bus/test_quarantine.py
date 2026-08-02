"""Broker-free tests for Kafka-private quarantine recovery coordination."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Coroutine
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from confluent_kafka import KafkaError, Message

from ai_platform.adapters.event_bus.consumer import (
    KafkaEventConsumer,
    KafkaOffsetCommitStatus,
    KafkaPendingDeliveryMetadata,
)
from ai_platform.adapters.event_bus.quarantine import (
    KafkaQuarantinePublication,
    KafkaQuarantinePublisher,
    KafkaTransportQuarantineCoordinator,
)
from ai_platform.adapters.event_bus.security import KafkaSecurityConfig, KafkaSecurityProtocol
from ai_platform.adapters.event_bus.topics import default_topic_mapping
from ai_platform.ports.event_bus import (
    DeliveryHandle,
    EventBusDelivery,
    LogicalChannel,
    LogicalSubscription,
    PublicationDisposition,
    PublicationResult,
    TransportHeader,
)
from ai_platform.ports.persistence.recovery import (
    QuarantinePublicationState,
    TransportDeliveryLocator,
    TransportRejectionRecord,
)
from ai_platform.runtime.consumer import DeliveryHandlingDisposition
from ai_platform.shared.identifiers import MessageId

DeliveryCallback = Callable[[KafkaError | None, Message], None]
NOW = datetime(2026, 8, 1, 12, tzinfo=UTC)
MESSAGE_ID = MessageId("018f23a7-6b4d-7c91-8a2e-123456789abc")
TRACEPARENT = b"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


class _MetadataProvider:
    def __init__(
        self,
        metadata: KafkaPendingDeliveryMetadata,
        *,
        commit_statuses: list[KafkaOffsetCommitStatus] | None = None,
    ) -> None:
        self.metadata = metadata
        self.handles: list[DeliveryHandle] = []
        self.commit_statuses = commit_statuses or []

    def pending_delivery_metadata(self, handle: DeliveryHandle) -> KafkaPendingDeliveryMetadata:
        self.handles.append(handle)
        return self.metadata

    def source_offset_commit_status(
        self,
        *,
        physical_source: str,
        partition: int,
        offset: int,
        timeout_seconds: float,
    ) -> KafkaOffsetCommitStatus:
        del physical_source, partition, offset, timeout_seconds
        return self.commit_statuses.pop(0)


class _Rejections:
    def __init__(self, record: TransportRejectionRecord | None = None) -> None:
        self.record = record
        self.created: list[dict[str, object]] = []
        self.states: list[QuarantinePublicationState] = []
        self.completed: list[TransportDeliveryLocator] = []

    async def create_or_resolve(
        self,
        *,
        locator: TransportDeliveryLocator,
        rejection_id: str,
        safe_failure_code: str,
        original_bytes_sha256: str,
        recorded_at: datetime,
    ) -> TransportRejectionRecord:
        self.created.append(
            {
                "locator": locator,
                "rejection_id": rejection_id,
                "safe_failure_code": safe_failure_code,
                "original_bytes_sha256": original_bytes_sha256,
                "recorded_at": recorded_at,
            }
        )
        if self.record is None:
            self.record = TransportRejectionRecord(
                locator=locator,
                rejection_id=rejection_id,
                safe_failure_code=safe_failure_code,
                original_bytes_sha256=original_bytes_sha256,
                quarantine_state=QuarantinePublicationState.NOT_ATTEMPTED,
                source_offset_completed=False,
                recorded_at=NOW,
            )
        else:
            assert self.record.locator == locator
            assert self.record.rejection_id == rejection_id
            assert self.record.safe_failure_code == safe_failure_code
            assert self.record.original_bytes_sha256 == original_bytes_sha256
        return self.record

    async def record_quarantine_state(
        self,
        locator: TransportDeliveryLocator,
        *,
        state: QuarantinePublicationState,
        recorded_at: datetime,
    ) -> TransportRejectionRecord:
        del recorded_at
        assert self.record is not None
        assert self.record.locator == locator
        self.states.append(state)
        self.record = replace(self.record, quarantine_state=state)
        return self.record

    async def mark_source_offset_completed(
        self,
        locator: TransportDeliveryLocator,
        *,
        completed_at: datetime,
    ) -> None:
        del completed_at
        assert self.record is not None
        assert self.record.quarantine_state is QuarantinePublicationState.CONFIRMED
        self.completed.append(locator)
        self.record = replace(self.record, source_offset_completed=True)

    async def list_confirmed_incomplete(
        self,
        *,
        logical_subscription: str,
        limit: int,
    ) -> tuple[TransportRejectionRecord, ...]:
        assert logical_subscription == _subscription().identity
        assert 1 <= limit <= 1_000
        if (
            self.record is not None
            and self.record.quarantine_state is QuarantinePublicationState.CONFIRMED
            and not self.record.source_offset_completed
        ):
            return (self.record,)
        return ()


class _Publisher:
    def __init__(self, results: list[PublicationResult]) -> None:
        self.results = results
        self.publications: list[tuple[KafkaQuarantinePublication, float]] = []

    def publish(
        self,
        publication: KafkaQuarantinePublication,
        *,
        timeout_seconds: float,
    ) -> PublicationResult:
        self.publications.append((publication, timeout_seconds))
        return self.results.pop(0)


def _subscription() -> LogicalSubscription:
    return LogicalSubscription("outcome-handler-v1", LogicalChannel.TASK_OUTCOMES)


def _delivery(value: bytes = b"not-json") -> EventBusDelivery:
    return EventBusDelivery(
        handle=DeliveryHandle("opaque-handle"),
        subscription=_subscription(),
        ordering_key=b"workflow-key",
        value=value,
        headers=(
            TransportHeader("traceparent", TRACEPARENT),
            TransportHeader("authorization", b"must-not-appear"),
        ),
    )


def _metadata() -> KafkaPendingDeliveryMetadata:
    return KafkaPendingDeliveryMetadata(
        subscription=_subscription(),
        physical_source="ai-platform.dev.task-outcomes.v1",
        partition=2,
        offset=42,
    )


def _result(disposition: PublicationDisposition) -> PublicationResult:
    return PublicationResult(
        disposition=disposition,
        retryable=disposition is not PublicationDisposition.ACKNOWLEDGED,
    )


def _coordinator(
    rejections: _Rejections,
    publisher: _Publisher,
    *,
    metadata: KafkaPendingDeliveryMetadata | None = None,
    maximum_original_bytes: int = 65_536,
) -> KafkaTransportQuarantineCoordinator:
    return KafkaTransportQuarantineCoordinator(
        metadata_provider=_MetadataProvider(metadata or _metadata()),
        subscription=_subscription(),
        rejections=rejections,
        publisher=publisher,
        topic_mapping=default_topic_mapping(environment="dev"),
        publish_timeout_seconds=1.5,
        maximum_original_bytes=maximum_original_bytes,
    )


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def test_confirmation_precedes_source_acknowledgement_completion() -> None:
    async def scenario() -> None:
        delivery = _delivery()
        rejections = _Rejections()
        publisher = _Publisher([_result(PublicationDisposition.ACKNOWLEDGED)])
        coordinator = _coordinator(rejections, publisher)
        digest = hashlib.sha256(delivery.value or b"").hexdigest()

        assert await coordinator.quarantine(
            delivery,
            safe_failure_code="MALFORMED_JSON",
            original_bytes_sha256=digest,
            validated_message_id=None,
        )
        assert rejections.states == [QuarantinePublicationState.CONFIRMED]
        assert rejections.completed == []

        await coordinator.after_acknowledgement(
            delivery,
            DeliveryHandlingDisposition.DURABLY_PROCESSED,
        )
        assert rejections.completed == []
        await coordinator.after_acknowledgement(
            delivery,
            DeliveryHandlingDisposition.DURABLY_QUARANTINED,
        )
        assert rejections.completed == [_metadata_locator()]

        publication, timeout = publisher.publications[0]
        assert timeout == 1.5
        envelope = json.loads(publication.value)
        assert envelope["rejection_id"] == publication.rejection_id
        assert envelope["source"] == {
            "key_base64": "d29ya2Zsb3cta2V5",
            "offset": 42,
            "partition": 2,
            "physical_source": "ai-platform.dev.task-outcomes.v1",
            "safe_headers": [
                {
                    "name": "traceparent",
                    "value_base64": (
                        "MDAtNGJmOTJmMzU3N2IzNGRhNmEzY2U5MjlkMGUwZTQ3MzYt"
                        "MDBmMDY3YWEwYmE5MDJiNy0wMQ=="
                    ),
                }
            ],
        }
        assert "must-not-appear" not in publication.value.decode()
        assert envelope["original"]["sha256"] == digest

    _run(scenario())


def test_unknown_publication_is_durable_and_never_confirms_or_completes() -> None:
    delivery = _delivery()
    rejections = _Rejections()
    publisher = _Publisher([_result(PublicationDisposition.UNKNOWN)])
    coordinator = _coordinator(rejections, publisher)

    confirmed = _run(
        coordinator.quarantine(
            delivery,
            safe_failure_code="MALFORMED_JSON",
            original_bytes_sha256=hashlib.sha256(delivery.value or b"").hexdigest(),
            validated_message_id=None,
        )
    )

    assert confirmed is False
    assert rejections.states == [QuarantinePublicationState.ATTEMPTED_UNKNOWN]
    assert rejections.completed == []


def test_retry_preserves_rejection_identity_and_exact_envelope_bytes() -> None:
    async def scenario() -> None:
        delivery = _delivery()
        rejections = _Rejections()
        publisher = _Publisher(
            [
                _result(PublicationDisposition.UNKNOWN),
                _result(PublicationDisposition.ACKNOWLEDGED),
            ]
        )
        coordinator = _coordinator(rejections, publisher)
        digest = hashlib.sha256(delivery.value or b"").hexdigest()

        assert not await coordinator.quarantine(
            delivery,
            safe_failure_code="MALFORMED_JSON",
            original_bytes_sha256=digest,
            validated_message_id=None,
        )
        assert await coordinator.quarantine(
            delivery,
            safe_failure_code="MALFORMED_JSON",
            original_bytes_sha256=digest,
            validated_message_id=None,
        )

        first = publisher.publications[0][0]
        second = publisher.publications[1][0]
        assert first.rejection_id == second.rejection_id
        assert first.rejection_id.startswith("tr_")
        assert first.value == second.value
        assert rejections.created[0]["rejection_id"] == rejections.created[1]["rejection_id"]

    _run(scenario())


def test_existing_confirmation_skips_republication_and_allows_ack() -> None:
    delivery = _delivery()
    digest = hashlib.sha256(delivery.value or b"").hexdigest()
    rejections = _Rejections()
    first_publisher = _Publisher([_result(PublicationDisposition.UNKNOWN)])
    first_coordinator = _coordinator(rejections, first_publisher)
    assert not _run(
        first_coordinator.quarantine(
            delivery,
            safe_failure_code="MALFORMED_JSON",
            original_bytes_sha256=digest,
            validated_message_id=None,
        )
    )
    assert rejections.record is not None
    rejections.record = replace(
        rejections.record,
        quarantine_state=QuarantinePublicationState.CONFIRMED,
    )
    recovery_publisher = _Publisher([])
    recovery_coordinator = _coordinator(rejections, recovery_publisher)

    assert _run(
        recovery_coordinator.quarantine(
            delivery,
            safe_failure_code="MALFORMED_JSON",
            original_bytes_sha256=digest,
            validated_message_id=None,
        )
    )
    assert recovery_publisher.publications == []


def test_startup_reconciliation_repairs_only_broker_committed_offsets() -> None:
    locator = _metadata_locator()
    record = TransportRejectionRecord(
        locator=locator,
        rejection_id="tr_stable",
        safe_failure_code="MALFORMED_JSON",
        original_bytes_sha256=hashlib.sha256(b"not-json").hexdigest(),
        quarantine_state=QuarantinePublicationState.CONFIRMED,
        source_offset_completed=False,
        recorded_at=NOW,
    )
    rejections = _Rejections(record)
    provider = _MetadataProvider(
        _metadata(),
        commit_statuses=[KafkaOffsetCommitStatus.COMMITTED],
    )
    coordinator = KafkaTransportQuarantineCoordinator(
        metadata_provider=provider,
        subscription=_subscription(),
        rejections=rejections,
        publisher=_Publisher([]),
        topic_mapping=default_topic_mapping(environment="dev"),
        publish_timeout_seconds=1.5,
    )

    result = _run(coordinator.reconcile_confirmed_offsets(limit=10, query_timeout_seconds=0.25))

    assert result.completed == 1
    assert result.not_committed == 0
    assert result.unknown == 0
    assert rejections.completed == [locator]


def test_oversized_original_is_not_copied_into_bounded_envelope() -> None:
    delivery = _delivery(b"sensitive" * 100)
    rejections = _Rejections()
    publisher = _Publisher([_result(PublicationDisposition.ACKNOWLEDGED)])
    coordinator = _coordinator(rejections, publisher, maximum_original_bytes=16)

    assert _run(
        coordinator.quarantine(
            delivery,
            safe_failure_code="MESSAGE_TOO_LARGE",
            original_bytes_sha256=hashlib.sha256(delivery.value or b"").hexdigest(),
            validated_message_id=MESSAGE_ID,
        )
    )

    envelope = json.loads(publisher.publications[0][0].value)
    assert envelope["original"]["bytes_retained"] is False
    assert "bytes_base64" not in envelope["original"]
    assert envelope["validated_message_id"] == MESSAGE_ID


def test_digest_mismatch_fails_before_persistence_or_publication() -> None:
    rejections = _Rejections()
    publisher = _Publisher([])
    coordinator = _coordinator(rejections, publisher)

    with pytest.raises(ValueError, match="does not match"):
        _run(
            coordinator.quarantine(
                _delivery(),
                safe_failure_code="MALFORMED_JSON",
                original_bytes_sha256="0" * 64,
                validated_message_id=None,
            )
        )

    assert rejections.created == []
    assert publisher.publications == []


@patch("ai_platform.adapters.event_bus.quarantine.Producer")
def test_private_publisher_targets_only_configured_quarantine_topic(
    mock_producer_cls: MagicMock,
) -> None:
    native = MagicMock()

    def produce_side_effect(*_args: object, **kwargs: object) -> None:
        callback = cast(DeliveryCallback, kwargs["on_delivery"])
        callback(None, cast(Message, MagicMock()))

    native.produce.side_effect = produce_side_effect
    mock_producer_cls.return_value = native
    publisher = KafkaQuarantinePublisher(
        bootstrap_servers="broker:9092",
        client_id="orchestrator-quarantine",
        topic_mapping=default_topic_mapping(environment="dev"),
        security=_security(),
    )
    publication = KafkaQuarantinePublication(
        logical_channel=LogicalChannel.TASK_OUTCOMES,
        rejection_id="tr_stable",
        value=b'{"bounded":true}',
    )

    result = publisher.publish(publication, timeout_seconds=1.0)

    assert result.disposition is PublicationDisposition.ACKNOWLEDGED
    args, kwargs = native.produce.call_args
    assert args[0] == "ai-platform.dev.task-outcomes.v1.quarantine"
    assert kwargs["key"] == b"tr_stable"
    assert kwargs["value"] == publication.value
    config = mock_producer_cls.call_args.args[0]
    assert config["security.protocol"] == "SASL_SSL"
    assert config["sasl.username"] == "orchestrator"


@patch("ai_platform.adapters.event_bus.consumer.Consumer")
def test_private_metadata_is_resolved_by_handle_without_changing_public_delivery(
    mock_consumer_cls: MagicMock,
) -> None:
    message = MagicMock(spec=Message)
    message.error.return_value = None
    message.value.return_value = b"invalid"
    message.key.return_value = b"key"
    message.headers.return_value = []
    message.topic.return_value = "ai-platform.dev.task-outcomes.v1"
    message.partition.return_value = 3
    message.offset.return_value = 99
    native = MagicMock()
    native.poll.return_value = message
    mock_consumer_cls.return_value = native
    consumer = KafkaEventConsumer(
        bootstrap_servers="broker:9092",
        client_id="orchestrator",
        group_id="outcomes",
        subscription=_subscription(),
        topic_mapping=default_topic_mapping(environment="dev"),
        security=_security(),
    )

    delivery = consumer.poll(timeout_seconds=0.1)
    assert delivery is not None
    metadata = consumer.pending_delivery_metadata(delivery.handle)

    assert metadata.partition == 3
    assert metadata.offset == 99
    assert not hasattr(delivery, "partition")
    assert not hasattr(delivery, "offset")


def _metadata_locator() -> TransportDeliveryLocator:
    return TransportDeliveryLocator(
        logical_subscription="outcome-handler-v1",
        physical_source="ai-platform.dev.task-outcomes.v1",
        partition=2,
        offset=42,
    )


def _security() -> KafkaSecurityConfig:
    return KafkaSecurityConfig(
        security_protocol=KafkaSecurityProtocol.SASL_SSL,
        username="orchestrator",
        password="secret",
        ca_file="/run/secrets/kafka-ca.pem",
    )
