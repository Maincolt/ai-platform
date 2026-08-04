"""External-service Kafka ACL boundary matrix against the real local broker.

Sprint 6 proved, by hand, one pair (`orchestrator-producer` denied publish to
`task-outcomes`). This module proves the Section 19 "Security boundary" ACL
guarantee across all four provisioned principals
(`orchestrator-producer`/`orchestrator-consumer`/`agent-producer`/
`agent-consumer`) and every topic/consumer-group documented in
`infrastructure/compose/scripts/init-kafka.sh`, confirming each principal can
do only what its allow-list grants and is denied (`TOPIC_AUTHORIZATION_FAILED`/
`GROUP_AUTHORIZATION_FAILED`) everything else -- `StandardAuthorizer`'s
deny-by-default posture holds for the full matrix, not just one hand-checked
pair.

Write checks produce a real record through the broker (authorized) or observe
a real `TOPIC_AUTHORIZATION_FAILED` delivery-report error (denied). Read
checks subscribe and poll once with `enable.auto.commit=False` (so a denied
or allowed probe never advances a real consumer group's committed offset);
an authorized read either returns a record or times out with no error, while
a denied read surfaces `TOPIC_AUTHORIZATION_FAILED`/`GROUP_AUTHORIZATION_FAILED`
promptly, well inside the bounded poll.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from confluent_kafka import Consumer, KafkaError, KafkaException, Message, Producer

pytestmark = pytest.mark.external_service

_ENVIRONMENT = "development"
_PREFIX = f"ai-platform.{_ENVIRONMENT}"
_TASK_COMMANDS = f"{_PREFIX}.task-commands.v1"
_TASK_COMMANDS_DLQ = f"{_TASK_COMMANDS}.quarantine"
_TASK_OUTCOMES = f"{_PREFIX}.task-outcomes.v1"
_TASK_OUTCOMES_DLQ = f"{_TASK_OUTCOMES}.quarantine"

_ORCHESTRATOR_OUTCOME_GROUP = "ai-platform-orchestrator-outcomes"
_AGENT_COMMAND_GROUP = "ai-platform-agent-commands"

_PRODUCE_TIMEOUT_SECONDS = 10.0
_POLL_TIMEOUT_SECONDS = 8.0
_AUTHORIZATION_ERROR_CODES = {
    KafkaError.TOPIC_AUTHORIZATION_FAILED,
    KafkaError.GROUP_AUTHORIZATION_FAILED,
}


def _attempt_write(client_config: dict[str, object], topic: str) -> KafkaError | None:
    """Produce one real record; return the delivery-report error, if any."""
    producer = Producer({**client_config, "client.id": f"sprint7-acl-{uuid.uuid4()}"})
    errors: list[KafkaError | None] = []

    def on_delivery(error: KafkaError | None, _message: Message) -> None:
        errors.append(error)

    try:
        producer.produce(topic, key=b"sprint7-acl-probe", value=b"{}", on_delivery=on_delivery)
    except BufferError:
        return None
    except KafkaException as exc:
        error = exc.args[0]
        assert isinstance(error, KafkaError)
        return error
    producer.flush(_PRODUCE_TIMEOUT_SECONDS)
    assert errors, "delivery report was not observed within the flush budget"
    return errors[0]


def _attempt_read(
    client_config: dict[str, object], *, topic: str, group_id: str
) -> KafkaError | None:
    """Poll once; return the observed record/authorization error, if any."""
    consumer = Consumer(
        {
            **client_config,
            "client.id": f"sprint7-acl-{uuid.uuid4()}",
            "group.id": group_id,
            "enable.auto.commit": False,
            "enable.auto.offset.store": False,
            "auto.offset.reset": "earliest",
        }
    )
    try:
        consumer.subscribe([topic])
        message = consumer.poll(_POLL_TIMEOUT_SECONDS)
    finally:
        consumer.close()
    if message is None:
        return None
    return message.error()


def _assert_allowed(error: KafkaError | None) -> None:
    assert error is None, f"expected allowed operation to succeed, got error: {error}"


def _assert_denied(error: KafkaError | None) -> None:
    assert error is not None, "expected operation to be denied, but it succeeded"
    assert error.code() in _AUTHORIZATION_ERROR_CODES, (
        f"expected an authorization error, got: {error}"
    )


@dataclass(frozen=True, slots=True)
class _WriteCase:
    principal: str
    topic: str
    allowed: bool


@dataclass(frozen=True, slots=True)
class _ReadCase:
    principal: str
    topic: str
    group_id: str
    allowed: bool


_WRITE_MATRIX: tuple[_WriteCase, ...] = (
    # orchestrator-producer: allowed to write only task-commands.
    _WriteCase("orchestrator-producer", _TASK_COMMANDS, True),
    _WriteCase("orchestrator-producer", _TASK_OUTCOMES, False),
    _WriteCase("orchestrator-producer", _TASK_COMMANDS_DLQ, False),
    _WriteCase("orchestrator-producer", _TASK_OUTCOMES_DLQ, False),
    # orchestrator-consumer: allowed to write only the outcomes quarantine topic.
    _WriteCase("orchestrator-consumer", _TASK_OUTCOMES_DLQ, True),
    _WriteCase("orchestrator-consumer", _TASK_OUTCOMES, False),
    _WriteCase("orchestrator-consumer", _TASK_COMMANDS, False),
    _WriteCase("orchestrator-consumer", _TASK_COMMANDS_DLQ, False),
    # agent-producer: allowed to write only task-outcomes.
    _WriteCase("agent-producer", _TASK_OUTCOMES, True),
    _WriteCase("agent-producer", _TASK_COMMANDS, False),
    _WriteCase("agent-producer", _TASK_COMMANDS_DLQ, False),
    _WriteCase("agent-producer", _TASK_OUTCOMES_DLQ, False),
    # agent-consumer: allowed to write only the commands quarantine topic.
    _WriteCase("agent-consumer", _TASK_COMMANDS_DLQ, True),
    _WriteCase("agent-consumer", _TASK_COMMANDS, False),
    _WriteCase("agent-consumer", _TASK_OUTCOMES, False),
    _WriteCase("agent-consumer", _TASK_OUTCOMES_DLQ, False),
)

_READ_MATRIX: tuple[_ReadCase, ...] = (
    # orchestrator-consumer: allowed to read task-outcomes under its own group.
    _ReadCase("orchestrator-consumer", _TASK_OUTCOMES, _ORCHESTRATOR_OUTCOME_GROUP, True),
    _ReadCase("orchestrator-consumer", _TASK_COMMANDS, _ORCHESTRATOR_OUTCOME_GROUP, False),
    # Denied group even against a topic it does have Read on: proves the
    # group-authorization dimension independently of topic authorization.
    _ReadCase("orchestrator-consumer", _TASK_OUTCOMES, _AGENT_COMMAND_GROUP, False),
    # agent-consumer: allowed to read task-commands under its own group.
    _ReadCase("agent-consumer", _TASK_COMMANDS, _AGENT_COMMAND_GROUP, True),
    _ReadCase("agent-consumer", _TASK_OUTCOMES, _AGENT_COMMAND_GROUP, False),
    _ReadCase("agent-consumer", _TASK_COMMANDS, _ORCHESTRATOR_OUTCOME_GROUP, False),
    # The two producer principals hold no Read/group grants at all.
    _ReadCase("orchestrator-producer", _TASK_COMMANDS, _ORCHESTRATOR_OUTCOME_GROUP, False),
    _ReadCase("agent-producer", _TASK_OUTCOMES, _AGENT_COMMAND_GROUP, False),
)


@pytest.mark.parametrize(
    "case", _WRITE_MATRIX, ids=[f"{c.principal}->write:{c.topic}" for c in _WRITE_MATRIX]
)
def test_kafka_write_acl_matrix(
    case: _WriteCase, kafka_principal_client_configs: dict[str, dict[str, object]]
) -> None:
    error = _attempt_write(kafka_principal_client_configs[case.principal], case.topic)
    if case.allowed:
        _assert_allowed(error)
    else:
        _assert_denied(error)


@pytest.mark.parametrize(
    "case", _READ_MATRIX, ids=[f"{c.principal}->read:{c.topic}@{c.group_id}" for c in _READ_MATRIX]
)
def test_kafka_read_acl_matrix(
    case: _ReadCase, kafka_principal_client_configs: dict[str, dict[str, object]]
) -> None:
    error = _attempt_read(
        kafka_principal_client_configs[case.principal],
        topic=case.topic,
        group_id=case.group_id,
    )
    if case.allowed:
        _assert_allowed(error)
    else:
        _assert_denied(error)
