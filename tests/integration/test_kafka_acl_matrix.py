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
# Capability-scoped since Sprint 9 (ADR-0014 Section 6): `task-commands`
# stays one logical channel, but its physical topic is computed per
# capability, so a second Agent class's consumer group never receives the
# first class's commands. Both topics exist; the isolation cases below
# (agent-consumer denied on the summarize topic and vice versa) are the
# ACL-level proof of that guarantee.
_TASK_COMMANDS_WORD_COUNT = f"{_PREFIX}.task-commands.text-word-count.v1"
_TASK_COMMANDS_WORD_COUNT_DLQ = f"{_TASK_COMMANDS_WORD_COUNT}.quarantine"
_TASK_COMMANDS_SUMMARIZE = f"{_PREFIX}.task-commands.text-summarize.v1"
_TASK_COMMANDS_SUMMARIZE_DLQ = f"{_TASK_COMMANDS_SUMMARIZE}.quarantine"
_TASK_COMMANDS_REVIEW = f"{_PREFIX}.task-commands.code-review.v1"
_TASK_COMMANDS_REVIEW_DLQ = f"{_TASK_COMMANDS_REVIEW}.quarantine"
_TASK_COMMANDS_UI_REVIEW = f"{_PREFIX}.task-commands.ui-review.v1"
_TASK_COMMANDS_UI_REVIEW_DLQ = f"{_TASK_COMMANDS_UI_REVIEW}.quarantine"
_TASK_COMMANDS_ARCHITECTURE_REVIEW = f"{_PREFIX}.task-commands.architecture-review.v1"
_TASK_COMMANDS_ARCHITECTURE_REVIEW_DLQ = f"{_TASK_COMMANDS_ARCHITECTURE_REVIEW}.quarantine"
_TASK_COMMANDS_DATA_ANALYSIS = f"{_PREFIX}.task-commands.data-analysis.v1"
_TASK_COMMANDS_DATA_ANALYSIS_DLQ = f"{_TASK_COMMANDS_DATA_ANALYSIS}.quarantine"
_TASK_COMMANDS_TECHNICAL_REVIEW = f"{_PREFIX}.task-commands.technical-review.v1"
_TASK_COMMANDS_TECHNICAL_REVIEW_DLQ = f"{_TASK_COMMANDS_TECHNICAL_REVIEW}.quarantine"
_TASK_COMMANDS_SECURITY_REVIEW = f"{_PREFIX}.task-commands.security-review.v1"
_TASK_COMMANDS_SECURITY_REVIEW_DLQ = f"{_TASK_COMMANDS_SECURITY_REVIEW}.quarantine"
_TASK_COMMANDS_ASSIGNMENT_ROUTE = f"{_PREFIX}.task-commands.assignment-route.v1"
_TASK_COMMANDS_ASSIGNMENT_ROUTE_DLQ = f"{_TASK_COMMANDS_ASSIGNMENT_ROUTE}.quarantine"
_TASK_OUTCOMES = f"{_PREFIX}.task-outcomes.v1"
_TASK_OUTCOMES_DLQ = f"{_TASK_OUTCOMES}.quarantine"

_ORCHESTRATOR_OUTCOME_GROUP = "ai-platform-orchestrator-outcomes"
_AGENT_COMMAND_GROUP = "ai-platform-agent-commands"
_SUMMARIZE_AGENT_COMMAND_GROUP = "ai-platform-summarize-agent-commands"
_REVIEW_AGENT_COMMAND_GROUP = "ai-platform-review-agent-commands"
_UI_REVIEW_AGENT_COMMAND_GROUP = "ai-platform-ui-review-agent-commands"
_ARCHITECTURE_REVIEW_AGENT_COMMAND_GROUP = "ai-platform-architecture-review-agent-commands"
_DATA_ANALYSIS_AGENT_COMMAND_GROUP = "ai-platform-data-analysis-agent-commands"
_TECHNICAL_REVIEW_AGENT_COMMAND_GROUP = "ai-platform-technical-review-agent-commands"
_SECURITY_REVIEW_AGENT_COMMAND_GROUP = "ai-platform-security-review-agent-commands"
_ASSIGNMENT_ROUTE_AGENT_COMMAND_GROUP = "ai-platform-assignment-route-agent-commands"

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
    # orchestrator-producer: allowed to write task-commands for both
    # capabilities (it routes to whichever one a submission needs), never
    # outcomes or either quarantine topic.
    _WriteCase("orchestrator-producer", _TASK_COMMANDS_WORD_COUNT, True),
    _WriteCase("orchestrator-producer", _TASK_COMMANDS_SUMMARIZE, True),
    _WriteCase("orchestrator-producer", _TASK_COMMANDS_REVIEW, True),
    _WriteCase("orchestrator-producer", _TASK_OUTCOMES, False),
    _WriteCase("orchestrator-producer", _TASK_COMMANDS_WORD_COUNT_DLQ, False),
    _WriteCase("orchestrator-producer", _TASK_COMMANDS_SUMMARIZE_DLQ, False),
    _WriteCase("orchestrator-producer", _TASK_COMMANDS_REVIEW_DLQ, False),
    _WriteCase("orchestrator-producer", _TASK_OUTCOMES_DLQ, False),
    # orchestrator-consumer: allowed to write only the outcomes quarantine topic.
    _WriteCase("orchestrator-consumer", _TASK_OUTCOMES_DLQ, True),
    _WriteCase("orchestrator-consumer", _TASK_OUTCOMES, False),
    _WriteCase("orchestrator-consumer", _TASK_COMMANDS_WORD_COUNT, False),
    _WriteCase("orchestrator-consumer", _TASK_COMMANDS_SUMMARIZE, False),
    _WriteCase("orchestrator-consumer", _TASK_COMMANDS_WORD_COUNT_DLQ, False),
    # agent-producer (text.word-count): allowed to write only task-outcomes,
    # the one topic every Agent class shares regardless of capability.
    _WriteCase("agent-producer", _TASK_OUTCOMES, True),
    _WriteCase("agent-producer", _TASK_COMMANDS_WORD_COUNT, False),
    _WriteCase("agent-producer", _TASK_COMMANDS_SUMMARIZE, False),
    _WriteCase("agent-producer", _TASK_COMMANDS_WORD_COUNT_DLQ, False),
    _WriteCase("agent-producer", _TASK_OUTCOMES_DLQ, False),
    # agent-consumer (text.word-count): allowed to write only its own
    # commands quarantine topic -- never the summarize capability's.
    _WriteCase("agent-consumer", _TASK_COMMANDS_WORD_COUNT_DLQ, True),
    _WriteCase("agent-consumer", _TASK_COMMANDS_SUMMARIZE_DLQ, False),
    _WriteCase("agent-consumer", _TASK_COMMANDS_WORD_COUNT, False),
    _WriteCase("agent-consumer", _TASK_OUTCOMES, False),
    _WriteCase("agent-consumer", _TASK_OUTCOMES_DLQ, False),
    # summarize-agent-producer: same shape as agent-producer, only task-outcomes.
    _WriteCase("summarize-agent-producer", _TASK_OUTCOMES, True),
    _WriteCase("summarize-agent-producer", _TASK_COMMANDS_SUMMARIZE, False),
    _WriteCase("summarize-agent-producer", _TASK_COMMANDS_WORD_COUNT, False),
    _WriteCase("summarize-agent-producer", _TASK_COMMANDS_SUMMARIZE_DLQ, False),
    # summarize-agent-consumer: allowed to write only its own commands
    # quarantine topic -- never the word-count capability's (the isolation
    # guarantee ADR-0014 Section 6 exists for).
    _WriteCase("summarize-agent-consumer", _TASK_COMMANDS_SUMMARIZE_DLQ, True),
    _WriteCase("summarize-agent-consumer", _TASK_COMMANDS_WORD_COUNT_DLQ, False),
    _WriteCase("summarize-agent-consumer", _TASK_COMMANDS_SUMMARIZE, False),
    _WriteCase("summarize-agent-consumer", _TASK_OUTCOMES, False),
    # review-agent-producer: same shape as agent-producer, only task-outcomes.
    _WriteCase("review-agent-producer", _TASK_OUTCOMES, True),
    _WriteCase("review-agent-producer", _TASK_COMMANDS_REVIEW, False),
    _WriteCase("review-agent-producer", _TASK_COMMANDS_WORD_COUNT, False),
    _WriteCase("review-agent-producer", _TASK_COMMANDS_REVIEW_DLQ, False),
    # review-agent-consumer: allowed to write only its own commands
    # quarantine topic -- never another capability's (ADR-0014 Section 6's
    # isolation guarantee, now proven for a third capability).
    _WriteCase("review-agent-consumer", _TASK_COMMANDS_REVIEW_DLQ, True),
    _WriteCase("review-agent-consumer", _TASK_COMMANDS_WORD_COUNT_DLQ, False),
    _WriteCase("review-agent-consumer", _TASK_COMMANDS_SUMMARIZE_DLQ, False),
    _WriteCase("review-agent-consumer", _TASK_COMMANDS_REVIEW, False),
    _WriteCase("review-agent-consumer", _TASK_OUTCOMES, False),
    # ui-review-agent-producer: same shape as agent-producer, only task-outcomes.
    _WriteCase("ui-review-agent-producer", _TASK_OUTCOMES, True),
    _WriteCase("ui-review-agent-producer", _TASK_COMMANDS_UI_REVIEW, False),
    _WriteCase("ui-review-agent-producer", _TASK_COMMANDS_WORD_COUNT, False),
    _WriteCase("ui-review-agent-producer", _TASK_COMMANDS_UI_REVIEW_DLQ, False),
    # ui-review-agent-consumer: allowed to write only its own commands
    # quarantine topic -- never another capability's (ADR-0014 Section 6's
    # isolation guarantee, now proven for a fourth capability).
    _WriteCase("ui-review-agent-consumer", _TASK_COMMANDS_UI_REVIEW_DLQ, True),
    _WriteCase("ui-review-agent-consumer", _TASK_COMMANDS_WORD_COUNT_DLQ, False),
    _WriteCase("ui-review-agent-consumer", _TASK_COMMANDS_REVIEW_DLQ, False),
    _WriteCase("ui-review-agent-consumer", _TASK_COMMANDS_UI_REVIEW, False),
    _WriteCase("ui-review-agent-consumer", _TASK_OUTCOMES, False),
    # architecture-review-agent-producer: same shape as agent-producer, only task-outcomes.
    _WriteCase("architecture-review-agent-producer", _TASK_OUTCOMES, True),
    _WriteCase("architecture-review-agent-producer", _TASK_COMMANDS_ARCHITECTURE_REVIEW, False),
    _WriteCase("architecture-review-agent-producer", _TASK_COMMANDS_WORD_COUNT, False),
    _WriteCase("architecture-review-agent-producer", _TASK_COMMANDS_ARCHITECTURE_REVIEW_DLQ, False),
    # architecture-review-agent-consumer: allowed to write only its own
    # commands quarantine topic -- never another capability's (ADR-0014
    # Section 6's isolation guarantee, now proven for a fifth capability).
    _WriteCase("architecture-review-agent-consumer", _TASK_COMMANDS_ARCHITECTURE_REVIEW_DLQ, True),
    _WriteCase("architecture-review-agent-consumer", _TASK_COMMANDS_WORD_COUNT_DLQ, False),
    _WriteCase("architecture-review-agent-consumer", _TASK_COMMANDS_UI_REVIEW_DLQ, False),
    _WriteCase("architecture-review-agent-consumer", _TASK_COMMANDS_ARCHITECTURE_REVIEW, False),
    _WriteCase("architecture-review-agent-consumer", _TASK_OUTCOMES, False),
    # data-analysis-agent-producer: same shape as agent-producer, only task-outcomes.
    _WriteCase("data-analysis-agent-producer", _TASK_OUTCOMES, True),
    _WriteCase("data-analysis-agent-producer", _TASK_COMMANDS_DATA_ANALYSIS, False),
    _WriteCase("data-analysis-agent-producer", _TASK_COMMANDS_WORD_COUNT, False),
    _WriteCase("data-analysis-agent-producer", _TASK_COMMANDS_DATA_ANALYSIS_DLQ, False),
    # data-analysis-agent-consumer: allowed to write only its own commands
    # quarantine topic -- never another capability's (ADR-0014 Section 6's
    # isolation guarantee, now proven for a sixth capability).
    _WriteCase("data-analysis-agent-consumer", _TASK_COMMANDS_DATA_ANALYSIS_DLQ, True),
    _WriteCase("data-analysis-agent-consumer", _TASK_COMMANDS_WORD_COUNT_DLQ, False),
    _WriteCase("data-analysis-agent-consumer", _TASK_COMMANDS_ARCHITECTURE_REVIEW_DLQ, False),
    _WriteCase("data-analysis-agent-consumer", _TASK_COMMANDS_DATA_ANALYSIS, False),
    _WriteCase("data-analysis-agent-consumer", _TASK_OUTCOMES, False),
    # technical-review-agent-producer: same shape as agent-producer, only task-outcomes.
    _WriteCase("technical-review-agent-producer", _TASK_OUTCOMES, True),
    _WriteCase("technical-review-agent-producer", _TASK_COMMANDS_TECHNICAL_REVIEW, False),
    _WriteCase("technical-review-agent-producer", _TASK_COMMANDS_WORD_COUNT, False),
    _WriteCase("technical-review-agent-producer", _TASK_COMMANDS_TECHNICAL_REVIEW_DLQ, False),
    # technical-review-agent-consumer: allowed to write only its own
    # commands quarantine topic -- never another capability's (ADR-0014
    # Section 6's isolation guarantee, now proven for a seventh capability).
    _WriteCase("technical-review-agent-consumer", _TASK_COMMANDS_TECHNICAL_REVIEW_DLQ, True),
    _WriteCase("technical-review-agent-consumer", _TASK_COMMANDS_WORD_COUNT_DLQ, False),
    _WriteCase("technical-review-agent-consumer", _TASK_COMMANDS_DATA_ANALYSIS_DLQ, False),
    _WriteCase("technical-review-agent-consumer", _TASK_COMMANDS_TECHNICAL_REVIEW, False),
    _WriteCase("technical-review-agent-consumer", _TASK_OUTCOMES, False),
    # security-review-agent-producer: same shape as agent-producer, only task-outcomes.
    _WriteCase("security-review-agent-producer", _TASK_OUTCOMES, True),
    _WriteCase("security-review-agent-producer", _TASK_COMMANDS_SECURITY_REVIEW, False),
    _WriteCase("security-review-agent-producer", _TASK_COMMANDS_WORD_COUNT, False),
    _WriteCase("security-review-agent-producer", _TASK_COMMANDS_SECURITY_REVIEW_DLQ, False),
    # security-review-agent-consumer: allowed to write only its own
    # commands quarantine topic -- never another capability's (ADR-0014
    # Section 6's isolation guarantee, now proven for a ninth capability).
    _WriteCase("security-review-agent-consumer", _TASK_COMMANDS_SECURITY_REVIEW_DLQ, True),
    _WriteCase("security-review-agent-consumer", _TASK_COMMANDS_WORD_COUNT_DLQ, False),
    _WriteCase("security-review-agent-consumer", _TASK_COMMANDS_TECHNICAL_REVIEW_DLQ, False),
    _WriteCase("security-review-agent-consumer", _TASK_COMMANDS_SECURITY_REVIEW, False),
    _WriteCase("security-review-agent-consumer", _TASK_OUTCOMES, False),
    # assignment-route-agent-producer: same shape as agent-producer, only task-outcomes.
    _WriteCase("assignment-route-agent-producer", _TASK_OUTCOMES, True),
    _WriteCase("assignment-route-agent-producer", _TASK_COMMANDS_ASSIGNMENT_ROUTE, False),
    _WriteCase("assignment-route-agent-producer", _TASK_COMMANDS_WORD_COUNT, False),
    _WriteCase("assignment-route-agent-producer", _TASK_COMMANDS_ASSIGNMENT_ROUTE_DLQ, False),
    # assignment-route-agent-consumer: allowed to write only its own
    # commands quarantine topic -- never another capability's (ADR-0014
    # Section 6's isolation guarantee, now proven for a tenth capability).
    _WriteCase("assignment-route-agent-consumer", _TASK_COMMANDS_ASSIGNMENT_ROUTE_DLQ, True),
    _WriteCase("assignment-route-agent-consumer", _TASK_COMMANDS_WORD_COUNT_DLQ, False),
    _WriteCase("assignment-route-agent-consumer", _TASK_COMMANDS_TECHNICAL_REVIEW_DLQ, False),
    _WriteCase("assignment-route-agent-consumer", _TASK_COMMANDS_ASSIGNMENT_ROUTE, False),
    _WriteCase("assignment-route-agent-consumer", _TASK_OUTCOMES, False),
)

_READ_MATRIX: tuple[_ReadCase, ...] = (
    # orchestrator-consumer: allowed to read task-outcomes under its own group.
    _ReadCase("orchestrator-consumer", _TASK_OUTCOMES, _ORCHESTRATOR_OUTCOME_GROUP, True),
    _ReadCase(
        "orchestrator-consumer", _TASK_COMMANDS_WORD_COUNT, _ORCHESTRATOR_OUTCOME_GROUP, False
    ),
    # Denied group even against a topic it does have Read on: proves the
    # group-authorization dimension independently of topic authorization.
    _ReadCase("orchestrator-consumer", _TASK_OUTCOMES, _AGENT_COMMAND_GROUP, False),
    # agent-consumer (text.word-count): allowed to read only its own
    # capability's commands topic under its own group -- denied on the
    # summarize capability's topic even under its own group, proving
    # ADR-0014 Section 6's per-capability isolation at the ACL level, not
    # just at the application-routing level.
    _ReadCase("agent-consumer", _TASK_COMMANDS_WORD_COUNT, _AGENT_COMMAND_GROUP, True),
    _ReadCase("agent-consumer", _TASK_COMMANDS_SUMMARIZE, _AGENT_COMMAND_GROUP, False),
    _ReadCase("agent-consumer", _TASK_OUTCOMES, _AGENT_COMMAND_GROUP, False),
    _ReadCase("agent-consumer", _TASK_COMMANDS_WORD_COUNT, _ORCHESTRATOR_OUTCOME_GROUP, False),
    # summarize-agent-consumer: the mirror image -- allowed on its own
    # capability's topic/group, denied on text.word-count's.
    _ReadCase(
        "summarize-agent-consumer",
        _TASK_COMMANDS_SUMMARIZE,
        _SUMMARIZE_AGENT_COMMAND_GROUP,
        True,
    ),
    _ReadCase(
        "summarize-agent-consumer",
        _TASK_COMMANDS_WORD_COUNT,
        _SUMMARIZE_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase("summarize-agent-consumer", _TASK_OUTCOMES, _SUMMARIZE_AGENT_COMMAND_GROUP, False),
    # review-agent-consumer: allowed on its own capability's topic/group,
    # denied on both other capabilities' -- the isolation guarantee proven
    # across all three capabilities now, not just the original two.
    _ReadCase("review-agent-consumer", _TASK_COMMANDS_REVIEW, _REVIEW_AGENT_COMMAND_GROUP, True),
    _ReadCase(
        "review-agent-consumer", _TASK_COMMANDS_WORD_COUNT, _REVIEW_AGENT_COMMAND_GROUP, False
    ),
    _ReadCase(
        "review-agent-consumer", _TASK_COMMANDS_SUMMARIZE, _REVIEW_AGENT_COMMAND_GROUP, False
    ),
    _ReadCase("review-agent-consumer", _TASK_OUTCOMES, _REVIEW_AGENT_COMMAND_GROUP, False),
    # ui-review-agent-consumer: allowed on its own capability's topic/group,
    # denied on the other three -- the isolation guarantee proven across
    # all four capabilities now.
    _ReadCase(
        "ui-review-agent-consumer", _TASK_COMMANDS_UI_REVIEW, _UI_REVIEW_AGENT_COMMAND_GROUP, True
    ),
    _ReadCase(
        "ui-review-agent-consumer",
        _TASK_COMMANDS_WORD_COUNT,
        _UI_REVIEW_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "ui-review-agent-consumer", _TASK_COMMANDS_SUMMARIZE, _UI_REVIEW_AGENT_COMMAND_GROUP, False
    ),
    _ReadCase(
        "ui-review-agent-consumer", _TASK_COMMANDS_REVIEW, _UI_REVIEW_AGENT_COMMAND_GROUP, False
    ),
    _ReadCase("ui-review-agent-consumer", _TASK_OUTCOMES, _UI_REVIEW_AGENT_COMMAND_GROUP, False),
    # architecture-review-agent-consumer: allowed on its own capability's
    # topic/group, denied on the other four -- the isolation guarantee
    # proven across all five capabilities now.
    _ReadCase(
        "architecture-review-agent-consumer",
        _TASK_COMMANDS_ARCHITECTURE_REVIEW,
        _ARCHITECTURE_REVIEW_AGENT_COMMAND_GROUP,
        True,
    ),
    _ReadCase(
        "architecture-review-agent-consumer",
        _TASK_COMMANDS_WORD_COUNT,
        _ARCHITECTURE_REVIEW_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "architecture-review-agent-consumer",
        _TASK_COMMANDS_SUMMARIZE,
        _ARCHITECTURE_REVIEW_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "architecture-review-agent-consumer",
        _TASK_COMMANDS_REVIEW,
        _ARCHITECTURE_REVIEW_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "architecture-review-agent-consumer",
        _TASK_COMMANDS_UI_REVIEW,
        _ARCHITECTURE_REVIEW_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "architecture-review-agent-consumer",
        _TASK_OUTCOMES,
        _ARCHITECTURE_REVIEW_AGENT_COMMAND_GROUP,
        False,
    ),
    # data-analysis-agent-consumer: allowed on its own capability's
    # topic/group, denied on the other five -- the isolation guarantee
    # proven across all six capabilities now.
    _ReadCase(
        "data-analysis-agent-consumer",
        _TASK_COMMANDS_DATA_ANALYSIS,
        _DATA_ANALYSIS_AGENT_COMMAND_GROUP,
        True,
    ),
    _ReadCase(
        "data-analysis-agent-consumer",
        _TASK_COMMANDS_WORD_COUNT,
        _DATA_ANALYSIS_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "data-analysis-agent-consumer",
        _TASK_COMMANDS_SUMMARIZE,
        _DATA_ANALYSIS_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "data-analysis-agent-consumer",
        _TASK_COMMANDS_REVIEW,
        _DATA_ANALYSIS_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "data-analysis-agent-consumer",
        _TASK_COMMANDS_UI_REVIEW,
        _DATA_ANALYSIS_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "data-analysis-agent-consumer",
        _TASK_COMMANDS_ARCHITECTURE_REVIEW,
        _DATA_ANALYSIS_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "data-analysis-agent-consumer",
        _TASK_OUTCOMES,
        _DATA_ANALYSIS_AGENT_COMMAND_GROUP,
        False,
    ),
    # technical-review-agent-consumer: allowed on its own capability's
    # topic/group, denied on the other six -- the isolation guarantee
    # proven across all seven capabilities now.
    _ReadCase(
        "technical-review-agent-consumer",
        _TASK_COMMANDS_TECHNICAL_REVIEW,
        _TECHNICAL_REVIEW_AGENT_COMMAND_GROUP,
        True,
    ),
    _ReadCase(
        "technical-review-agent-consumer",
        _TASK_COMMANDS_WORD_COUNT,
        _TECHNICAL_REVIEW_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "technical-review-agent-consumer",
        _TASK_COMMANDS_SUMMARIZE,
        _TECHNICAL_REVIEW_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "technical-review-agent-consumer",
        _TASK_COMMANDS_REVIEW,
        _TECHNICAL_REVIEW_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "technical-review-agent-consumer",
        _TASK_COMMANDS_UI_REVIEW,
        _TECHNICAL_REVIEW_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "technical-review-agent-consumer",
        _TASK_COMMANDS_ARCHITECTURE_REVIEW,
        _TECHNICAL_REVIEW_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "technical-review-agent-consumer",
        _TASK_COMMANDS_DATA_ANALYSIS,
        _TECHNICAL_REVIEW_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "technical-review-agent-consumer",
        _TASK_OUTCOMES,
        _TECHNICAL_REVIEW_AGENT_COMMAND_GROUP,
        False,
    ),
    # security-review-agent-consumer: allowed on its own capability's
    # topic/group, denied on the other seven -- the isolation guarantee
    # proven across all eight review/analysis capabilities now.
    _ReadCase(
        "security-review-agent-consumer",
        _TASK_COMMANDS_SECURITY_REVIEW,
        _SECURITY_REVIEW_AGENT_COMMAND_GROUP,
        True,
    ),
    _ReadCase(
        "security-review-agent-consumer",
        _TASK_COMMANDS_WORD_COUNT,
        _SECURITY_REVIEW_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "security-review-agent-consumer",
        _TASK_COMMANDS_SUMMARIZE,
        _SECURITY_REVIEW_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "security-review-agent-consumer",
        _TASK_COMMANDS_REVIEW,
        _SECURITY_REVIEW_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "security-review-agent-consumer",
        _TASK_COMMANDS_UI_REVIEW,
        _SECURITY_REVIEW_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "security-review-agent-consumer",
        _TASK_COMMANDS_ARCHITECTURE_REVIEW,
        _SECURITY_REVIEW_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "security-review-agent-consumer",
        _TASK_COMMANDS_DATA_ANALYSIS,
        _SECURITY_REVIEW_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "security-review-agent-consumer",
        _TASK_COMMANDS_TECHNICAL_REVIEW,
        _SECURITY_REVIEW_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "security-review-agent-consumer",
        _TASK_OUTCOMES,
        _SECURITY_REVIEW_AGENT_COMMAND_GROUP,
        False,
    ),
    # assignment-route-agent-consumer: allowed on its own capability's
    # topic/group, denied on the other seven -- the isolation guarantee
    # proven across all eight capabilities now.
    _ReadCase(
        "assignment-route-agent-consumer",
        _TASK_COMMANDS_ASSIGNMENT_ROUTE,
        _ASSIGNMENT_ROUTE_AGENT_COMMAND_GROUP,
        True,
    ),
    _ReadCase(
        "assignment-route-agent-consumer",
        _TASK_COMMANDS_WORD_COUNT,
        _ASSIGNMENT_ROUTE_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "assignment-route-agent-consumer",
        _TASK_COMMANDS_SUMMARIZE,
        _ASSIGNMENT_ROUTE_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "assignment-route-agent-consumer",
        _TASK_COMMANDS_REVIEW,
        _ASSIGNMENT_ROUTE_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "assignment-route-agent-consumer",
        _TASK_COMMANDS_UI_REVIEW,
        _ASSIGNMENT_ROUTE_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "assignment-route-agent-consumer",
        _TASK_COMMANDS_ARCHITECTURE_REVIEW,
        _ASSIGNMENT_ROUTE_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "assignment-route-agent-consumer",
        _TASK_COMMANDS_DATA_ANALYSIS,
        _ASSIGNMENT_ROUTE_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "assignment-route-agent-consumer",
        _TASK_COMMANDS_TECHNICAL_REVIEW,
        _ASSIGNMENT_ROUTE_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "assignment-route-agent-consumer",
        _TASK_OUTCOMES,
        _ASSIGNMENT_ROUTE_AGENT_COMMAND_GROUP,
        False,
    ),
    # The producer principals hold no Read/group grants at all.
    _ReadCase(
        "orchestrator-producer", _TASK_COMMANDS_WORD_COUNT, _ORCHESTRATOR_OUTCOME_GROUP, False
    ),
    _ReadCase("agent-producer", _TASK_OUTCOMES, _AGENT_COMMAND_GROUP, False),
    _ReadCase("summarize-agent-producer", _TASK_OUTCOMES, _SUMMARIZE_AGENT_COMMAND_GROUP, False),
    _ReadCase("review-agent-producer", _TASK_OUTCOMES, _REVIEW_AGENT_COMMAND_GROUP, False),
    _ReadCase("ui-review-agent-producer", _TASK_OUTCOMES, _UI_REVIEW_AGENT_COMMAND_GROUP, False),
    _ReadCase(
        "architecture-review-agent-producer",
        _TASK_OUTCOMES,
        _ARCHITECTURE_REVIEW_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "data-analysis-agent-producer",
        _TASK_OUTCOMES,
        _DATA_ANALYSIS_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "technical-review-agent-producer",
        _TASK_OUTCOMES,
        _TECHNICAL_REVIEW_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "security-review-agent-producer",
        _TASK_OUTCOMES,
        _SECURITY_REVIEW_AGENT_COMMAND_GROUP,
        False,
    ),
    _ReadCase(
        "assignment-route-agent-producer",
        _TASK_OUTCOMES,
        _ASSIGNMENT_ROUTE_AGENT_COMMAND_GROUP,
        False,
    ),
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
