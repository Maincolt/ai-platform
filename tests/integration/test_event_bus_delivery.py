"""External-service Event Bus delivery guarantees against the real broker.

These tests exercise `KafkaEventPublisher`/`KafkaEventConsumer`/
`KafkaTransportQuarantineCoordinator` directly against the real local Kafka
topology (see `tests/integration/conftest.py` and `infrastructure/README.md`),
proving the Section 19 "Event Bus delivery" guarantees the mocked unit tests
under `tests/unit/adapters/event_bus/` cannot: keyed ordering, manual
acknowledgment/at-least-once redelivery, and malformed-payload quarantine
through the same validator/handler/quarantine wiring `runtime/composition.py`
uses in the real processes.

Every test uses a fresh UUIDv7 ordering key and a dedicated, randomly suffixed
consumer-group id so it never collides with, or joins, the real
`ai-platform-orchestrator-outcomes`/`ai-platform-agent-commands` groups.

Scope note: the real ACLs provisioned by
`infrastructure/compose/scripts/init-kafka.sh` grant `orchestrator-consumer`/
`agent-consumer` read access only to their two fixed, literal consumer-group
names -- not to arbitrary per-test group ids. To honor the "dedicated,
test-scoped consumer group" requirement without joining those production-named
groups, and without mutating the shared topology's ACLs from a test run, these
tests authenticate as the `admin` SCRAM principal (a documented broker
super-user that bypasses ACL checks -- see `infrastructure/README.md`) rather
than the four least-privilege application principals. This still drives the
real adapters against the real broker end to end; it only changes which
already-provisioned identity is used to do so. ACL enforcement itself is
exercised elsewhere (Sprint 7 security tests), not here.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any

import pytest
from confluent_kafka import Producer as RawKafkaProducer

from ai_platform.adapters.event_bus.consumer import KafkaEventConsumer
from ai_platform.adapters.event_bus.producer import KafkaEventPublisher
from ai_platform.adapters.event_bus.quarantine import (
    KafkaQuarantinePublisher,
    KafkaTransportQuarantineCoordinator,
)
from ai_platform.adapters.event_bus.security import KafkaSecurityConfig, KafkaSecurityProtocol
from ai_platform.adapters.event_bus.topics import (
    KafkaTopicMapping,
    TopicBinding,
    command_topic_binding_for_capability,
    default_topic_mapping,
)
from ai_platform.adapters.persistence.connection import AsyncPsycopgPool
from ai_platform.adapters.persistence.recovery import PsycopgTransportRejectionTransaction
from ai_platform.ports.event_bus import (
    AcknowledgementDisposition,
    EventBusDelivery,
    LogicalChannel,
    LogicalSubscription,
    OutboundMessage,
    PublicationDisposition,
    TransportHeader,
)
from ai_platform.runtime.consumer import DeliveryHandlingDisposition
from ai_platform.runtime.contracts import JsonSchemaMessageValidator
from ai_platform.runtime.handlers import TerminalOutcomeDeliveryHandler
from ai_platform.runtime.loading import load_canonical_message_schemas
from ai_platform.shared.identifiers import (
    CorrelationId,
    MessageId,
    TaskAttemptId,
    TaskId,
    WorkflowId,
)
from ai_platform.shared.outcomes import AgentOutcome

pytestmark = pytest.mark.external_service

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_DIRECTORY = _REPO_ROOT / "contracts" / "json-schema" / "v1"
_ENVIRONMENT = "development"
_OVERALL_POLL_BUDGET_SECONDS = 90.0
_POLL_TIMEOUT_SECONDS = 2.0

# Must track `ai_platform.runtime.composition._EXPECTED_SCHEMA_VERSION`
# (see tests/integration/conftest.py's copy of this same constant/comment).
_EXPECTED_ORCHESTRATOR_SCHEMA_VERSION = 4

_WORD_COUNT_CAPABILITY_NAME = "text.word-count"


def _new_group_id() -> str:
    return f"sprint7-test-{uuid.uuid4()}"


def _new_ordering_key() -> str:
    return str(uuid.uuid7())


@pytest.fixture(scope="session")
def topic_mapping() -> KafkaTopicMapping:
    return default_topic_mapping(environment=_ENVIRONMENT)


@pytest.fixture(scope="session")
def word_count_command_topic_mapping() -> KafkaTopicMapping:
    """TASK_COMMANDS bound to the real capability-scoped topic (ADR-0014 Section 6).

    `KafkaEventConsumer` has no capability-aware fallback the way
    `KafkaEventPublisher._resolve_topic` does -- it subscribes to whatever
    `topic_mapping.topic_for(TASK_COMMANDS)` says, so tests that consume
    TASK_COMMANDS directly need this instead of the plain `topic_mapping`
    fixture, which still resolves TASK_COMMANDS to the pre-ADR-0014 bare
    topic no longer provisioned by `init-kafka.sh`.
    """
    command_binding = command_topic_binding_for_capability(
        environment=_ENVIRONMENT, capability_name=_WORD_COUNT_CAPABILITY_NAME
    )
    outcomes_topic = f"ai-platform.{_ENVIRONMENT}.{LogicalChannel.TASK_OUTCOMES.value}.v1"
    return KafkaTopicMapping(
        (
            command_binding,
            TopicBinding(
                logical_channel=LogicalChannel.TASK_OUTCOMES,
                topic=outcomes_topic,
                quarantine_topic=f"{outcomes_topic}.quarantine",
            ),
        )
    )


@pytest.fixture(scope="session")
def kafka_admin_security(kafka_admin_client_config: dict[str, Any]) -> KafkaSecurityConfig:
    """Admin-principal Kafka credentials; see module docstring for why."""
    return KafkaSecurityConfig(
        security_protocol=KafkaSecurityProtocol.LOCAL_DEVELOPMENT_SASL_PLAINTEXT,
        username=str(kafka_admin_client_config["sasl.username"]),
        password=str(kafka_admin_client_config["sasl.password"]),
    )


def _make_publisher(
    kafka_bootstrap_servers: str,
    topic_mapping: KafkaTopicMapping,
    kafka_admin_security: KafkaSecurityConfig,
) -> KafkaEventPublisher:
    return KafkaEventPublisher(
        bootstrap_servers=kafka_bootstrap_servers,
        client_id=f"sprint7-test-producer-{uuid.uuid4()}",
        topic_mapping=topic_mapping,
        security=kafka_admin_security,
        # Required for TASK_COMMANDS: `_resolve_topic` only applies
        # capability-scoped routing (ADR-0014 Section 6) when both this and
        # the message's `capability_name` are set; otherwise it falls back
        # to `topic_mapping`'s single shared TASK_COMMANDS entry, which
        # `default_topic_mapping` still computes as the pre-ADR-0014 bare
        # topic name -- no longer provisioned by `init-kafka.sh` since
        # Sprint 9, so publishing without this never gets a delivery report.
        environment=_ENVIRONMENT,
    )


def _make_consumer(
    kafka_bootstrap_servers: str,
    topic_mapping: KafkaTopicMapping,
    kafka_admin_security: KafkaSecurityConfig,
    *,
    channel: LogicalChannel,
    group_id: str,
    subscription_identity: str,
) -> KafkaEventConsumer:
    return KafkaEventConsumer(
        bootstrap_servers=kafka_bootstrap_servers,
        client_id=f"sprint7-test-consumer-{uuid.uuid4()}",
        group_id=group_id,
        subscription=LogicalSubscription(identity=subscription_identity, channel=channel),
        topic_mapping=topic_mapping,
        security=kafka_admin_security,
    )


def _collect_matching(
    consumer: KafkaEventConsumer,
    *,
    matches: Callable[[EventBusDelivery], bool],
    count: int,
) -> list[EventBusDelivery]:
    """Poll and acknowledge everything, keeping only deliveries that match."""
    deadline = monotonic() + _OVERALL_POLL_BUDGET_SECONDS
    collected: list[EventBusDelivery] = []
    while len(collected) < count and monotonic() < deadline:
        delivery = consumer.poll(timeout_seconds=_POLL_TIMEOUT_SECONDS)
        if delivery is None:
            continue
        if matches(delivery):
            collected.append(delivery)
        result = consumer.acknowledge(delivery.handle)
        assert result.disposition is AcknowledgementDisposition.ACKNOWLEDGED
    return collected


def _find_matching_without_ack(
    consumer: KafkaEventConsumer,
    *,
    matches: Callable[[EventBusDelivery], bool],
) -> EventBusDelivery:
    """Poll, acknowledging everything that does not match, and stop at the first that does."""
    deadline = monotonic() + _OVERALL_POLL_BUDGET_SECONDS
    while monotonic() < deadline:
        delivery = consumer.poll(timeout_seconds=_POLL_TIMEOUT_SECONDS)
        if delivery is None:
            continue
        if matches(delivery):
            return delivery
        result = consumer.acknowledge(delivery.handle)
        assert result.disposition is AcknowledgementDisposition.ACKNOWLEDGED
    raise AssertionError("expected delivery was not observed within the poll budget")


def test_keyed_ordering_preserves_publish_order_for_same_partition_key(
    kafka_bootstrap_servers: str,
    word_count_command_topic_mapping: KafkaTopicMapping,
    kafka_admin_security: KafkaSecurityConfig,
) -> None:
    ordering_key = _new_ordering_key()
    message_count = 5

    publisher = _make_publisher(
        kafka_bootstrap_servers, word_count_command_topic_mapping, kafka_admin_security
    )
    try:
        for sequence in range(message_count):
            outcome = publisher.publish(
                OutboundMessage(
                    logical_channel=LogicalChannel.TASK_COMMANDS,
                    message_id=str(uuid.uuid7()),
                    ordering_key=ordering_key,
                    value=f'{{"sequence":{sequence}}}'.encode(),
                    headers=(TransportHeader(name="content-type", value=b"application/json"),),
                    capability_name=_WORD_COUNT_CAPABILITY_NAME,
                ),
                timeout_seconds=10.0,
            )
            assert outcome.disposition is PublicationDisposition.ACKNOWLEDGED
    finally:
        publisher.close(timeout_seconds=10.0)

    consumer = _make_consumer(
        kafka_bootstrap_servers,
        word_count_command_topic_mapping,
        kafka_admin_security,
        channel=LogicalChannel.TASK_COMMANDS,
        group_id=_new_group_id(),
        subscription_identity="sprint7-test-ordering",
    )
    try:
        key_bytes = ordering_key.encode("utf-8")
        deliveries = _collect_matching(
            consumer,
            matches=lambda delivery: delivery.ordering_key == key_bytes,
            count=message_count,
        )
    finally:
        consumer.close(timeout_seconds=10.0)

    assert len(deliveries) == message_count
    observed_sequences = [
        int((delivery.value or b"").decode("utf-8").split(":")[1].rstrip("}"))
        for delivery in deliveries
    ]
    assert observed_sequences == list(range(message_count))


def test_manual_acknowledgment_redelivers_after_crash_before_commit(
    kafka_bootstrap_servers: str,
    word_count_command_topic_mapping: KafkaTopicMapping,
    kafka_admin_security: KafkaSecurityConfig,
) -> None:
    ordering_key = _new_ordering_key()
    key_bytes = ordering_key.encode("utf-8")
    marker = f"redelivery-{uuid.uuid4()}".encode()
    group_id = _new_group_id()

    publisher = _make_publisher(
        kafka_bootstrap_servers, word_count_command_topic_mapping, kafka_admin_security
    )
    try:
        outcome = publisher.publish(
            OutboundMessage(
                logical_channel=LogicalChannel.TASK_COMMANDS,
                message_id=str(uuid.uuid7()),
                ordering_key=ordering_key,
                value=marker,
                capability_name=_WORD_COUNT_CAPABILITY_NAME,
            ),
            timeout_seconds=10.0,
        )
        assert outcome.disposition is PublicationDisposition.ACKNOWLEDGED
    finally:
        publisher.close(timeout_seconds=10.0)

    first_consumer = _make_consumer(
        kafka_bootstrap_servers,
        word_count_command_topic_mapping,
        kafka_admin_security,
        channel=LogicalChannel.TASK_COMMANDS,
        group_id=group_id,
        subscription_identity="sprint7-test-redelivery",
    )
    try:
        first_delivery = _find_matching_without_ack(
            first_consumer,
            matches=lambda delivery: delivery.ordering_key == key_bytes,
        )
        assert first_delivery.value == marker
        # Deliberately do not acknowledge: this simulates a crash between
        # polling the record and committing its offset.
    finally:
        first_consumer.close(timeout_seconds=10.0)

    second_consumer = _make_consumer(
        kafka_bootstrap_servers,
        word_count_command_topic_mapping,
        kafka_admin_security,
        channel=LogicalChannel.TASK_COMMANDS,
        group_id=group_id,
        subscription_identity="sprint7-test-redelivery",
    )
    try:
        redelivered = _find_matching_without_ack(
            second_consumer,
            matches=lambda delivery: delivery.ordering_key == key_bytes,
        )
        assert redelivered.value == marker
        result = second_consumer.acknowledge(redelivered.handle)
        assert result.disposition is AcknowledgementDisposition.ACKNOWLEDGED
    finally:
        second_consumer.close(timeout_seconds=10.0)


class _UnreachableTerminalProcessor:
    """Proves the malformed message never reaches domain processing."""

    async def process(
        self,
        *,
        environment: str,
        logical_consumer_id: str,
        validated_message_id: MessageId,
        immutable_message_digest: str,
        workflow_id: WorkflowId,
        task_id: TaskId,
        task_attempt_id: TaskAttemptId,
        correlation_id: CorrelationId,
        causation_message_id: MessageId,
        producer_component: str,
        producer_instance_id: str,
        capability_name: str,
        capability_version: str,
        result_text: str | None,
        agent_evidence_component: str | None,
        agent_evidence_instance_id: str | None,
        outcome: AgentOutcome,
        occurred_at: datetime,
    ) -> Any:
        raise AssertionError("terminal processing must not run for a malformed message")


def test_malformed_payload_is_quarantined_through_the_real_runtime_pipeline(
    kafka_bootstrap_servers: str,
    topic_mapping: KafkaTopicMapping,
    kafka_admin_security: KafkaSecurityConfig,
    kafka_admin_client_config: dict[str, Any],
    postgres_dsn: str,
) -> None:
    """Publish raw malformed bytes and drive them through the real pipeline.

    Mirrors how `runtime/composition.py` wires `KafkaEventConsumer` +
    `JsonSchemaMessageValidator` + `TerminalOutcomeDeliveryHandler` +
    `KafkaTransportQuarantineCoordinator` together, but publishes with a raw
    `confluent_kafka.Producer` (bypassing `KafkaEventPublisher`'s own
    well-formed envelope construction) to reproduce a genuinely malformed
    delivery exactly as the real broker would carry it.
    """
    ordering_key = _new_ordering_key()
    key_bytes = ordering_key.encode("utf-8")
    subscription_identity = f"sprint7-test-malformed-{uuid.uuid4()}"

    raw_producer = RawKafkaProducer(
        {
            **kafka_admin_client_config,
            "client.id": f"sprint7-test-raw-producer-{uuid.uuid4()}",
        }
    )
    raw_producer.produce(
        topic_mapping.topic_for(LogicalChannel.TASK_OUTCOMES),
        key=key_bytes,
        value=b"{not-valid-json",
    )
    delivered = raw_producer.flush(10.0)
    assert delivered == 0, "raw malformed record was not accepted by the broker"

    consumer = _make_consumer(
        kafka_bootstrap_servers,
        topic_mapping,
        kafka_admin_security,
        channel=LogicalChannel.TASK_OUTCOMES,
        group_id=_new_group_id(),
        subscription_identity=subscription_identity,
    )
    quarantine_publisher = KafkaQuarantinePublisher(
        bootstrap_servers=kafka_bootstrap_servers,
        client_id=f"sprint7-test-quarantine-publisher-{uuid.uuid4()}",
        topic_mapping=topic_mapping,
        security=kafka_admin_security,
    )

    async def _run() -> None:
        pool = AsyncPsycopgPool(
            postgres_dsn,
            component_schema="orchestrator",
            expected_schema_version=_EXPECTED_ORCHESTRATOR_SCHEMA_VERSION,
            max_size=2,
        )
        await pool.open()
        try:
            rejections = PsycopgTransportRejectionTransaction(pool)
            subscription = LogicalSubscription(
                identity=subscription_identity, channel=LogicalChannel.TASK_OUTCOMES
            )
            quarantine = KafkaTransportQuarantineCoordinator(
                metadata_provider=consumer,
                subscription=subscription,
                rejections=rejections,
                publisher=quarantine_publisher,
                topic_mapping=topic_mapping,
                publish_timeout_seconds=10.0,
            )
            schemas = load_canonical_message_schemas(
                _SCHEMA_DIRECTORY, contract_names=("TaskCompleted", "TaskFailed")
            )
            handler = TerminalOutcomeDeliveryHandler(
                validator=JsonSchemaMessageValidator(schemas),
                processor=_UnreachableTerminalProcessor(),
                quarantine=quarantine,
                environment=_ENVIRONMENT,
                logical_consumer_id=subscription_identity,
            )

            delivery = _find_matching_without_ack(
                consumer, matches=lambda delivery: delivery.ordering_key == key_bytes
            )
            disposition = await handler.handle(delivery)
            assert disposition is DeliveryHandlingDisposition.DURABLY_QUARANTINED

            ack_result = consumer.acknowledge(delivery.handle)
            assert ack_result.disposition is AcknowledgementDisposition.ACKNOWLEDGED
            await quarantine.after_acknowledgement(delivery, disposition)

            async with pool.connection() as connection:
                row = await (
                    await connection.execute(
                        """
                        SELECT quarantine_state, source_offset_completed, safe_failure_code
                        FROM orchestrator.transport_rejections
                        WHERE logical_subscription = %s
                        """,
                        (subscription_identity,),
                    )
                ).fetchone()
            assert row is not None
            assert row[0] == "CONFIRMED"
            assert row[1] is True
            assert row[2] == "MALFORMED_JSON"
        finally:
            await pool.close()

    try:
        asyncio.run(_run())
    finally:
        consumer.close(timeout_seconds=10.0)
        quarantine_publisher.close(timeout_seconds=10.0)
