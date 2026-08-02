"""Kafka-private quarantine publication and durable recovery coordination."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Event, Lock
from time import monotonic
from typing import Protocol

from confluent_kafka import KafkaError, KafkaException, Message, Producer

from ai_platform.adapters.event_bus.consumer import (
    KafkaOffsetCommitStatus,
    KafkaPendingDeliveryMetadata,
)
from ai_platform.adapters.event_bus.security import KafkaSecurityConfig
from ai_platform.adapters.event_bus.topics import KafkaTopicMapping
from ai_platform.ports.event_bus import (
    DeliveryHandle,
    EventBusDelivery,
    EventBusOperationError,
    LogicalChannel,
    LogicalSubscription,
    PublicationDisposition,
    PublicationResult,
    ShutdownResult,
)
from ai_platform.ports.persistence.recovery import (
    QuarantinePublicationState,
    TransportDeliveryLocator,
    TransportRejectionRecord,
    TransportRejectionTransactionPort,
)
from ai_platform.runtime.consumer import DeliveryHandlingDisposition
from ai_platform.shared.identifiers import MessageId
from ai_platform.shared.messages import canonical_message_bytes

_SAFE_FAILURE_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,127}")
_TRACEPARENT = re.compile(rb"00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}")
_REJECTION_ID_DOMAIN = b"ai-platform.transport-rejection.v1\0"


class KafkaPendingDeliveryMetadataPort(Protocol):
    """Adapter-private access to broker coordinates for one pending handle."""

    def pending_delivery_metadata(self, handle: DeliveryHandle) -> KafkaPendingDeliveryMetadata: ...

    def source_offset_commit_status(
        self,
        *,
        physical_source: str,
        partition: int,
        offset: int,
        timeout_seconds: float,
    ) -> KafkaOffsetCommitStatus: ...


@dataclass(frozen=True, slots=True)
class KafkaQuarantinePublication:
    """One immutable restricted quarantine record for a physical topic."""

    logical_channel: LogicalChannel
    rejection_id: str
    value: bytes


@dataclass(frozen=True, slots=True)
class QuarantineReconciliationResult:
    """Bounded outcome of confirmed/incomplete startup reconciliation."""

    inspected: int
    completed: int
    not_committed: int
    unknown: int


class KafkaQuarantinePublisherPort(Protocol):
    """Publish only to the configured broker-private quarantine resource."""

    def publish(
        self,
        publication: KafkaQuarantinePublication,
        *,
        timeout_seconds: float,
    ) -> PublicationResult: ...


class KafkaQuarantinePublisher:
    """Bounded publisher restricted to configured quarantine topics."""

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
            raise EventBusOperationError(
                "QUARANTINE_PUBLISHER_START_FAILED", retryable=True
            ) from None
        except ValueError:
            raise EventBusOperationError(
                "QUARANTINE_PUBLISHER_CONFIG_INVALID", retryable=False
            ) from None
        self._topic_mapping = topic_mapping
        self._operation_lock = Lock()
        self._stopping = Event()

    def publish(
        self,
        publication: KafkaQuarantinePublication,
        *,
        timeout_seconds: float,
    ) -> PublicationResult:
        """Publish exact quarantine bytes and report bounded certainty."""

        if timeout_seconds <= 0:
            return _not_accepted("INVALID_TIMEOUT", retryable=False)
        if self._stopping.is_set():
            return _not_accepted("QUARANTINE_PUBLISHER_STOPPED", retryable=True)

        deadline = monotonic() + timeout_seconds
        if not self._operation_lock.acquire(timeout=timeout_seconds):
            return _not_accepted("QUARANTINE_PUBLISHER_BUSY", retryable=True)
        try:
            if self._stopping.is_set():
                return _not_accepted("QUARANTINE_PUBLISHER_STOPPED", retryable=True)
            if deadline - monotonic() <= 0:
                return _not_accepted("QUARANTINE_TIMEOUT_BEFORE_ATTEMPT", retryable=True)

            delivered = Event()
            delivery_error: list[KafkaError | None] = []

            def on_delivery(error: KafkaError | None, _message: Message) -> None:
                delivery_error.append(error)
                delivered.set()

            try:
                self._producer.produce(
                    self._topic_mapping.quarantine_topic_for(publication.logical_channel),
                    key=publication.rejection_id.encode("ascii"),
                    value=publication.value,
                    headers=[("content-type", b"application/json")],
                    on_delivery=on_delivery,
                )
            except BufferError:
                return _not_accepted("QUARANTINE_LOCAL_QUEUE_FULL", retryable=True)
            except KafkaException:
                return _not_accepted("QUARANTINE_PRODUCE_REJECTED", retryable=True)

            while not delivered.is_set():
                remaining = deadline - monotonic()
                if remaining <= 0:
                    return PublicationResult(
                        disposition=PublicationDisposition.UNKNOWN,
                        retryable=True,
                        reason_code="QUARANTINE_DELIVERY_REPORT_TIMEOUT",
                    )
                try:
                    self._producer.poll(min(remaining, 0.05))
                except KafkaException:
                    return PublicationResult(
                        disposition=PublicationDisposition.UNKNOWN,
                        retryable=True,
                        reason_code="QUARANTINE_DELIVERY_POLL_FAILED",
                    )

            error = delivery_error[0]
            if error is None:
                return PublicationResult(
                    disposition=PublicationDisposition.ACKNOWLEDGED,
                    retryable=False,
                )
            return _not_accepted("QUARANTINE_DELIVERY_REJECTED", retryable=error.retriable())
        finally:
            self._operation_lock.release()

    def stop_accepting(self) -> None:
        self._stopping.set()

    def close(self, *, timeout_seconds: float) -> ShutdownResult:
        self.stop_accepting()
        if timeout_seconds <= 0:
            return ShutdownResult(drained=False)
        deadline = monotonic() + timeout_seconds
        if not self._operation_lock.acquire(timeout=timeout_seconds):
            return ShutdownResult(drained=False)
        try:
            try:
                outstanding = self._producer.flush(max(0.0, deadline - monotonic()))
            except KafkaException:
                return ShutdownResult(drained=False)
            return ShutdownResult(drained=outstanding == 0)
        finally:
            self._operation_lock.release()


class KafkaTransportQuarantineCoordinator:
    """Bridge private source evidence to durable quarantine recovery.

    The portable ``EventBusDelivery`` remains broker-neutral. Source topic,
    partition, and offset are resolved by opaque handle through the concrete
    consumer only inside this adapter module.
    """

    def __init__(
        self,
        *,
        metadata_provider: KafkaPendingDeliveryMetadataPort,
        subscription: LogicalSubscription,
        rejections: TransportRejectionTransactionPort,
        publisher: KafkaQuarantinePublisherPort,
        topic_mapping: KafkaTopicMapping,
        publish_timeout_seconds: float,
        maximum_original_bytes: int = 65_536,
        maximum_envelope_bytes: int = 131_072,
    ) -> None:
        if publish_timeout_seconds <= 0:
            raise ValueError("publish_timeout_seconds must be positive")
        if maximum_original_bytes < 0 or maximum_envelope_bytes < 1:
            raise ValueError("quarantine byte bounds are invalid")
        self._metadata_provider = metadata_provider
        self._subscription = subscription
        self._rejections = rejections
        self._publisher = publisher
        self._topic_mapping = topic_mapping
        self._publish_timeout_seconds = publish_timeout_seconds
        self._maximum_original_bytes = maximum_original_bytes
        self._maximum_envelope_bytes = maximum_envelope_bytes
        self._confirmed_by_handle: dict[str, TransportDeliveryLocator] = {}

    async def reconcile_confirmed_offsets(
        self,
        *,
        limit: int,
        query_timeout_seconds: float,
    ) -> QuarantineReconciliationResult:
        """Repair post-offset-commit marker gaps from authoritative broker state."""

        if limit < 1 or limit > 1_000 or query_timeout_seconds <= 0:
            raise ValueError("quarantine reconciliation bounds are invalid")
        records = await self._rejections.list_confirmed_incomplete(
            logical_subscription=self._subscription.identity,
            limit=limit,
        )
        expected_source = self._topic_mapping.topic_for(self._subscription.channel)
        completed = 0
        not_committed = 0
        unknown = 0
        for record in records:
            locator = record.locator
            if locator.physical_source != expected_source:
                unknown += 1
                continue
            try:
                status = await asyncio.to_thread(
                    self._metadata_provider.source_offset_commit_status,
                    physical_source=locator.physical_source,
                    partition=locator.partition,
                    offset=locator.offset,
                    timeout_seconds=query_timeout_seconds,
                )
            except EventBusOperationError:
                status = KafkaOffsetCommitStatus.UNKNOWN
            if status is KafkaOffsetCommitStatus.COMMITTED:
                await self._rejections.mark_source_offset_completed(
                    locator,
                    completed_at=datetime.now(UTC),
                )
                completed += 1
            elif status is KafkaOffsetCommitStatus.NOT_COMMITTED:
                not_committed += 1
            else:
                unknown += 1
        return QuarantineReconciliationResult(
            inspected=len(records),
            completed=completed,
            not_committed=not_committed,
            unknown=unknown,
        )

    async def quarantine(
        self,
        delivery: EventBusDelivery,
        *,
        safe_failure_code: str,
        original_bytes_sha256: str,
        validated_message_id: MessageId | None,
    ) -> bool:
        """Publish and durably confirm one stable quarantine identity."""

        self._validate_request(delivery, safe_failure_code, original_bytes_sha256)
        metadata = await asyncio.to_thread(
            self._metadata_provider.pending_delivery_metadata,
            delivery.handle,
        )
        self._validate_metadata(delivery, metadata)
        locator = TransportDeliveryLocator(
            logical_subscription=metadata.subscription.identity,
            physical_source=metadata.physical_source,
            partition=metadata.partition,
            offset=metadata.offset,
        )
        recorded_at = datetime.now(UTC)
        record = await self._rejections.create_or_resolve(
            locator=locator,
            rejection_id=_stable_rejection_id(locator),
            safe_failure_code=safe_failure_code,
            original_bytes_sha256=original_bytes_sha256,
            recorded_at=recorded_at,
        )
        if record.quarantine_state is QuarantinePublicationState.CONFIRMED:
            self._confirmed_by_handle[delivery.handle.token] = locator
            return True

        publication = KafkaQuarantinePublication(
            logical_channel=delivery.subscription.channel,
            rejection_id=record.rejection_id,
            value=self._quarantine_envelope(
                delivery,
                metadata,
                record,
                validated_message_id=validated_message_id,
            ),
        )
        result = await asyncio.to_thread(
            self._publisher.publish,
            publication,
            timeout_seconds=self._publish_timeout_seconds,
        )
        if result.disposition is PublicationDisposition.ACKNOWLEDGED:
            await self._rejections.record_quarantine_state(
                locator,
                state=QuarantinePublicationState.CONFIRMED,
                recorded_at=datetime.now(UTC),
            )
            self._confirmed_by_handle[delivery.handle.token] = locator
            return True
        if result.disposition is PublicationDisposition.UNKNOWN:
            await self._rejections.record_quarantine_state(
                locator,
                state=QuarantinePublicationState.ATTEMPTED_UNKNOWN,
                recorded_at=datetime.now(UTC),
            )
        return False

    async def after_acknowledgement(
        self,
        delivery: EventBusDelivery,
        disposition: DeliveryHandlingDisposition,
    ) -> None:
        """Record source completion only after its transport commit succeeds."""

        if disposition is not DeliveryHandlingDisposition.DURABLY_QUARANTINED:
            return
        locator = self._confirmed_by_handle.get(delivery.handle.token)
        if locator is None:
            raise EventBusOperationError("QUARANTINE_CONFIRMATION_MISSING", retryable=False)
        await self._rejections.mark_source_offset_completed(
            locator,
            completed_at=datetime.now(UTC),
        )
        del self._confirmed_by_handle[delivery.handle.token]

    async def quarantine_retry_exhaustion(
        self,
        delivery: EventBusDelivery,
        *,
        safe_failure_code: str,
    ) -> bool:
        """Route exhausted processing through the same durable quarantine path."""

        original = delivery.value or b""
        return await self.quarantine(
            delivery,
            safe_failure_code=safe_failure_code,
            original_bytes_sha256=hashlib.sha256(original).hexdigest(),
            validated_message_id=None,
        )

    @staticmethod
    def _validate_request(
        delivery: EventBusDelivery,
        safe_failure_code: str,
        original_bytes_sha256: str,
    ) -> None:
        if _SAFE_FAILURE_CODE.fullmatch(safe_failure_code) is None:
            raise ValueError("safe_failure_code is invalid")
        original = delivery.value or b""
        calculated = hashlib.sha256(original).hexdigest()
        if original_bytes_sha256 != calculated:
            raise ValueError("original_bytes_sha256 does not match the pending delivery")

    def _validate_metadata(
        self,
        delivery: EventBusDelivery,
        metadata: KafkaPendingDeliveryMetadata,
    ) -> None:
        if metadata.subscription != delivery.subscription:
            raise EventBusOperationError("QUARANTINE_SUBSCRIPTION_MISMATCH", retryable=False)
        if metadata.subscription != self._subscription:
            raise EventBusOperationError("QUARANTINE_COORDINATOR_MISMATCH", retryable=False)
        expected_source = self._topic_mapping.topic_for(delivery.subscription.channel)
        if metadata.physical_source != expected_source:
            raise EventBusOperationError("QUARANTINE_SOURCE_MISMATCH", retryable=False)
        if len(metadata.subscription.identity.encode("utf-8")) > 256:
            raise EventBusOperationError("QUARANTINE_SUBSCRIPTION_INVALID", retryable=False)
        if metadata.partition < 0 or metadata.offset < 0:
            raise EventBusOperationError("QUARANTINE_COORDINATES_INVALID", retryable=False)

    def _quarantine_envelope(
        self,
        delivery: EventBusDelivery,
        metadata: KafkaPendingDeliveryMetadata,
        record: TransportRejectionRecord,
        *,
        validated_message_id: MessageId | None,
    ) -> bytes:
        original = delivery.value or b""
        retained = len(original) <= self._maximum_original_bytes
        evidence: dict[str, object] = {
            "sha256": record.original_bytes_sha256,
            "bytes_retained": retained,
        }
        if retained:
            evidence["bytes_base64"] = base64.b64encode(original).decode("ascii")

        source: dict[str, object] = {
            "physical_source": metadata.physical_source,
            "partition": metadata.partition,
            "offset": metadata.offset,
        }
        if delivery.ordering_key is not None and len(delivery.ordering_key) <= 512:
            source["key_base64"] = base64.b64encode(delivery.ordering_key).decode("ascii")
        safe_headers = _safe_headers(delivery)
        if safe_headers:
            source["safe_headers"] = safe_headers

        envelope: dict[str, object] = {
            "record_type": "transport-quarantine",
            "record_version": "1.0",
            "rejection_id": record.rejection_id,
            "logical_channel": delivery.subscription.channel.value,
            "logical_subscription": metadata.subscription.identity,
            "source": source,
            "failure": {
                "code": record.safe_failure_code,
                "recorded_at": _timestamp(record.recorded_at),
            },
            "original": evidence,
        }
        if validated_message_id is not None:
            envelope["validated_message_id"] = str(validated_message_id)
        encoded = canonical_message_bytes(envelope)
        if len(encoded) > self._maximum_envelope_bytes:
            raise EventBusOperationError("QUARANTINE_ENVELOPE_TOO_LARGE", retryable=False)
        return encoded


def _stable_rejection_id(locator: TransportDeliveryLocator) -> str:
    encoded = canonical_message_bytes(
        {
            "logical_subscription": locator.logical_subscription,
            "physical_source": locator.physical_source,
            "partition": locator.partition,
            "offset": locator.offset,
        }
    )
    return f"tr_{hashlib.sha256(_REJECTION_ID_DOMAIN + encoded).hexdigest()}"


def _safe_headers(delivery: EventBusDelivery) -> list[dict[str, object]]:
    retained: list[dict[str, object]] = []
    for header in delivery.headers:
        name = header.name.lower()
        value = header.value
        if value is None or not _is_safe_trace_header(name, value):
            continue
        retained.append(
            {
                "name": name,
                "value_base64": base64.b64encode(value).decode("ascii"),
            }
        )
        if len(retained) == 16:
            break
    return retained


def _is_safe_trace_header(name: str, value: bytes) -> bool:
    if name == "traceparent":
        return (
            _TRACEPARENT.fullmatch(value) is not None
            and value[3:35] != b"0" * 32
            and value[36:52] != b"0" * 16
        )
    if name == "tracestate":
        return 0 < len(value) <= 512 and all(0x20 <= item <= 0x7E for item in value)
    return False


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise EventBusOperationError("QUARANTINE_TIMESTAMP_INVALID", retryable=False)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _not_accepted(reason_code: str, *, retryable: bool) -> PublicationResult:
    return PublicationResult(
        disposition=PublicationDisposition.DEFINITIVELY_NOT_ACCEPTED,
        retryable=retryable,
        reason_code=reason_code,
    )
