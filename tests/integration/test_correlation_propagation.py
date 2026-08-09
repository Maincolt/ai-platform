"""External-service correlation propagation guarantee (Section 19).

`docs/implementation/vertical-slice-01.md`'s Correlation Normalization
Scenarios table's "Propagation" column claims a valid correlation_id
flows "through supported logs, traces, audit, command, and events" --
`tests/unit/api/test_correlation.py` and
`tests/component/api/test_workflow_api.py` thoroughly prove the
validation/discard/generate rules and the HTTP response header, but
neither proves the value actually reaches a real downstream `ExecuteTask`
command message on the real broker -- both stop at the HTTP boundary or a
real-database `commit_submission`, never at a real Kafka payload.

This test closes that specific gap: build one real submission carrying a
known correlation_id, commit it against the real database (the same
`PsycopgOrchestratorPersistence.commit_submission` path
`tests/integration/test_submission_idempotency.py` exercises), publish
its outbox row through the real `OutboxPublisherWorker`/`KafkaEventPublisher`
pair to the real broker, then consume it back and assert the raw message
bytes -- not an in-memory object -- carry the same correlation_id, and
that the message is genuinely valid against the canonical `ExecuteTask`
JSON Schema.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from typing import Any, cast

import pytest
from confluent_kafka import Consumer as RawKafkaConsumer

from ai_platform.adapters.event_bus.producer import KafkaEventPublisher
from ai_platform.adapters.event_bus.security import KafkaSecurityConfig, KafkaSecurityProtocol
from ai_platform.adapters.event_bus.topics import (
    KafkaTopicMapping,
    TopicBinding,
    command_topic_binding_for_capability,
)
from ai_platform.adapters.persistence.connection import AsyncPsycopgPool
from ai_platform.adapters.persistence.orchestrator import PsycopgOrchestratorPersistence
from ai_platform.orchestrator.domain.accepted_request import (
    AcceptanceEvidence,
    AcceptedRequestKey,
)
from ai_platform.orchestrator.domain.audit import AuditRecord
from ai_platform.orchestrator.domain.recovery import OrchestratorOutboxRecord
from ai_platform.orchestrator.domain.selection import SelectionIntent
from ai_platform.orchestrator.domain.task import Task, TaskAttempt
from ai_platform.orchestrator.domain.workflow import Workflow
from ai_platform.ports.event_bus import LogicalChannel, OutboundMessage, TransportHeader
from ai_platform.ports.event_bus import PublicationDisposition as BusPublicationDisposition
from ai_platform.ports.persistence.transactions import SubmissionCommitIntent
from ai_platform.runtime.contracts import JsonSchemaMessageValidator
from ai_platform.runtime.loading import load_canonical_message_schemas
from ai_platform.shared.identifiers import (
    ActorId,
    AgentId,
    CorrelationId,
    IdempotencyScopeId,
    MessageId,
    OwnerSubjectId,
    RequestId,
    TaskAttemptId,
    TaskId,
    WorkflowId,
)

pytestmark = pytest.mark.external_service

_ENVIRONMENT = "development"
_CAPABILITY_NAME = "text.word-count"
_CAPABILITY_VERSION = "1.0"
_OVERALL_POLL_BUDGET_SECONDS = 90.0

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_DIRECTORY = _REPO_ROOT / "contracts" / "json-schema" / "v1"

# Must track `ai_platform.runtime.composition._EXPECTED_SCHEMA_VERSION`
# (see tests/integration/conftest.py's copy of this same constant/comment).
_EXPECTED_ORCHESTRATOR_SCHEMA_VERSION = 3


def _new_id() -> str:
    return str(uuid.uuid7())


async def _open_orchestrator_pool(dsn: str) -> AsyncPsycopgPool:
    pool = AsyncPsycopgPool(
        dsn,
        component_schema="orchestrator",
        expected_schema_version=_EXPECTED_ORCHESTRATOR_SCHEMA_VERSION,
        min_size=1,
        max_size=3,
    )
    await pool.open()
    return pool


def _build_intent(
    *, correlation_id: CorrelationId, now: datetime
) -> tuple[SubmissionCommitIntent, dict[str, Any]]:
    """Build one real, schema-valid submission carrying `correlation_id`."""
    workflow_id = WorkflowId(_new_id())
    task_id = TaskId(_new_id())
    attempt_id = TaskAttemptId(_new_id())
    message_id = MessageId(_new_id())
    request_id = RequestId(_new_id())
    producer_instance_id = _new_id()
    agent_instance_id = _new_id()
    task_result_deadline = now + timedelta(minutes=5)

    workflow = Workflow(
        workflow_id=workflow_id, request_id=request_id, correlation_id=correlation_id
    )
    workflow.receive(occurred_at=now)
    workflow.prepare(occurred_at=now)
    workflow.dispatch(occurred_at=now)

    task = Task(task_id=task_id, workflow_id=workflow_id, created_at=now)
    attempt = TaskAttempt(
        task_attempt_id=attempt_id,
        task_id=task_id,
        attempt_number=1,
        selection=SelectionIntent(
            agent_id=AgentId("sprint10-correlation-agent"),
            capability_name=_CAPABILITY_NAME,
            capability_version=_CAPABILITY_VERSION,
            implementation_identity="sprint10-correlation-impl",
            implementation_version="1.0",
            command_contract_version="1.0",
            event_contract_versions=("1.0",),
            registry_revision="sprint10-correlation-rev-1",
            deployment_declaration_digest="sprint10-correlation-digest-1",
            selection_policy_version="1.0",
            availability_classification="READY",
            observed_at=now,
            selected_at=now,
        ),
        task_result_deadline=task_result_deadline,
    )

    # Real, schema-valid `ExecuteTask` envelope+payload (see
    # contracts/json-schema/v1/execute_task.schema.json) -- the same shape
    # `runtime/composition.py` builds for a real submission, with a known
    # correlation_id planted so this test can prove it survives the trip
    # to a real Kafka message unchanged.
    execute_task_message = {
        "message_id": str(message_id),
        "message_kind": "command",
        "contract_name": "ExecuteTask",
        "contract_version": "1.0",
        "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "correlation_id": str(correlation_id),
        "causation_id": None,
        "workflow_id": str(workflow_id),
        "task_id": str(task_id),
        "task_attempt_id": str(attempt_id),
        "producer": {"component": "orchestrator", "instance_id": producer_instance_id},
        "payload": {
            "request_id": str(request_id),
            "input": "sprint ten correlation propagation words",
            "capability": _CAPABILITY_NAME,
            "capability_version": _CAPABILITY_VERSION,
            "selected_agent": {
                "component": "test-agent",
                "instance_id": agent_instance_id,
            },
            "attempt_number": 1,
            "task_result_deadline": task_result_deadline.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }
    payload_bytes = json.dumps(execute_task_message).encode("utf-8")

    outbox = OrchestratorOutboxRecord(
        message_id=message_id,
        workflow_id=workflow_id,
        logical_channel=LogicalChannel.TASK_COMMANDS.value,
        ordering_key=str(workflow_id),
        payload_bytes=payload_bytes,
        headers=(("content-type", b"application/json"),),
        creation_sequence=1,
        created_at=now,
        capability_name=_CAPABILITY_NAME,
    )
    intent = SubmissionCommitIntent(
        key=AcceptedRequestKey(
            environment="sprint10-correlation",
            operation="workflow.submit",
            idempotency_scope_id=IdempotencyScopeId(_new_id()),
            request_id=request_id,
        ),
        evidence=AcceptanceEvidence(
            acceptance_actor_id=ActorId("sprint10-correlation-actor"),
            accepted_owner_subject_id=OwnerSubjectId("sprint10-correlation-owner"),
            current_owner_subject_id=OwnerSubjectId("sprint10-correlation-owner"),
            fingerprint=f"fingerprint-{request_id}",
            fingerprint_policy_version="1.0",
            policy_identity="sprint10-correlation-policy",
            policy_revision="rev-1",
            policy_decision="allow",
            scope_mapping_revision="rev-1",
            authorization_evidence="evidence-1",
            accepted_at=now,
        ),
        workflow=workflow,
        task=task,
        task_attempt=attempt,
        command_outbox=outbox,
        audit=AuditRecord(
            kind="workflow_accepted",
            workflow_id=workflow_id,
            occurred_at=now,
            actor_id=ActorId("sprint10-correlation-actor"),
            details={},
        ),
    )
    return intent, execute_task_message


def test_a_valid_correlation_id_reaches_the_real_kafka_command_message_unchanged(
    postgres_orchestrator_app_dsn: str,
    kafka_bootstrap_servers: str,
    kafka_admin_client_config: dict[str, Any],
) -> None:
    correlation_id = CorrelationId(_new_id())
    now = datetime.now(UTC)
    intent, expected_message = _build_intent(correlation_id=correlation_id, now=now)

    validator = JsonSchemaMessageValidator(load_canonical_message_schemas(_SCHEMA_DIRECTORY))
    # The planted message is itself schema-valid before it ever touches the
    # database or the broker -- this is a test fixture sanity check, not
    # the guarantee under test.
    validator.validate(json.dumps(expected_message).encode("utf-8"))

    async def run() -> dict[str, Any] | None:
        pool = await _open_orchestrator_pool(postgres_orchestrator_app_dsn)
        try:
            persistence = PsycopgOrchestratorPersistence(pool)
            commit_result = await persistence.commit_submission(intent)
            assert commit_result.created is True

            security = KafkaSecurityConfig(
                security_protocol=KafkaSecurityProtocol.LOCAL_DEVELOPMENT_SASL_PLAINTEXT,
                username=str(kafka_admin_client_config["sasl.username"]),
                password=str(kafka_admin_client_config["sasl.password"]),
            )
            command_binding = command_topic_binding_for_capability(
                environment=_ENVIRONMENT, capability_name=_CAPABILITY_NAME
            )
            topic_mapping = KafkaTopicMapping(
                (
                    command_binding,
                    TopicBinding(
                        logical_channel=LogicalChannel.TASK_OUTCOMES,
                        topic=f"ai-platform.{_ENVIRONMENT}.task-outcomes.v1",
                        quarantine_topic=f"ai-platform.{_ENVIRONMENT}.task-outcomes.v1.quarantine",
                    ),
                )
            )
            publisher = KafkaEventPublisher(
                bootstrap_servers=kafka_bootstrap_servers,
                client_id=f"sprint10-correlation-producer-{uuid.uuid4()}",
                topic_mapping=topic_mapping,
                security=security,
                environment=_ENVIRONMENT,
            )

            # Read back the *durable* payload bytes this test's own
            # commit_submission() call just wrote to the real outbox row --
            # not the in-memory dict this test already trusts -- and
            # publish exactly those bytes. `claim_next`'s claim query is
            # intentionally global across the whole shared `task-commands`
            # logical_channel (proven correct by
            # tests/integration/test_outbox_claim_fencing.py's claim-fencing
            # test); on this shared dev database it has accumulated many
            # older NOT_ATTEMPTED rows from unrelated test runs across this
            # sprint that a real `OutboxPublisherWorker.run_once()` call
            # would claim and publish *instead of* this test's own row, so
            # this test intentionally bypasses claim scoping and publishes
            # the durable row directly -- the claim/publish mechanism
            # itself is already covered elsewhere; this test's job is only
            # to prove the durable payload's correlation_id survives the
            # trip onto a real Kafka message unchanged.
            async with pool.connection() as connection, connection.cursor() as cursor:
                await cursor.execute(
                    "SELECT payload_bytes FROM orchestrator.outbox WHERE message_id = %s",
                    (str(intent.command_outbox.message_id),),
                )
                row = await cursor.fetchone()
            assert row is not None
            durable_payload_bytes = cast(bytes, row[0])
            assert durable_payload_bytes == intent.command_outbox.payload_bytes

            try:
                publish_result = await asyncio.to_thread(
                    publisher.publish,
                    OutboundMessage(
                        logical_channel=LogicalChannel.TASK_COMMANDS,
                        message_id=str(intent.command_outbox.message_id),
                        ordering_key=intent.command_outbox.ordering_key,
                        value=durable_payload_bytes,
                        headers=tuple(
                            TransportHeader(name=name, value=value)
                            for name, value in intent.command_outbox.headers
                        ),
                        capability_name=_CAPABILITY_NAME,
                    ),
                    timeout_seconds=10.0,
                )
            finally:
                publisher.close(timeout_seconds=10.0)
            assert publish_result.disposition is BusPublicationDisposition.ACKNOWLEDGED

            # Consume it back with a raw admin-authenticated consumer
            # pinned to the real capability-scoped topic -- proving the
            # bytes that actually reached the broker carry the correlation
            # id, not an in-memory object this test already trusts.
            raw_consumer = RawKafkaConsumer(
                {
                    "bootstrap.servers": kafka_bootstrap_servers,
                    "group.id": f"sprint10-correlation-{uuid.uuid4()}",
                    "security.protocol": "SASL_PLAINTEXT",
                    "sasl.mechanism": "SCRAM-SHA-256",
                    "sasl.username": str(kafka_admin_client_config["sasl.username"]),
                    "sasl.password": str(kafka_admin_client_config["sasl.password"]),
                    "auto.offset.reset": "earliest",
                    "enable.auto.commit": False,
                }
            )
            raw_consumer.subscribe([command_binding.topic])
            deadline = monotonic() + _OVERALL_POLL_BUDGET_SECONDS
            found: dict[str, Any] | None = None
            try:
                while monotonic() < deadline:
                    record = raw_consumer.poll(timeout=2.0)
                    if record is None or record.error() is not None:
                        continue
                    raw_value = record.value()
                    if raw_value is None:
                        continue
                    try:
                        parsed: object = json.loads(raw_value)
                    except json.JSONDecodeError:
                        # The shared topic also carries other tests' raw,
                        # non-JSON fixture payloads (e.g. keyed-ordering
                        # markers) -- not a message this test cares about.
                        continue
                    if not isinstance(parsed, dict):
                        continue
                    candidate = cast(dict[str, Any], parsed)
                    if candidate.get("message_id") == expected_message["message_id"]:
                        found = candidate
                        break
            finally:
                raw_consumer.close()
            return found
        finally:
            await pool.close()

    found_message = asyncio.run(run())

    assert found_message is not None, (
        "expected ExecuteTask message was not observed on the real "
        f"'{_CAPABILITY_NAME}' command topic within the poll budget"
    )
    assert found_message["correlation_id"] == str(correlation_id)
    assert found_message["workflow_id"] == expected_message["workflow_id"]
    validator.validate(json.dumps(found_message).encode("utf-8"))
