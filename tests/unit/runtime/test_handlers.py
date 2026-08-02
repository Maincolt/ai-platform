"""Broker-free tests for validated command and outcome handlers."""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from ai_platform.agents.test_agent.agent import TestAgentDisposition, TestAgentResult
from ai_platform.agents.test_agent.execution_context import ExecuteTaskContext
from ai_platform.orchestrator.application.terminal import (
    TerminalDisposition,
    TerminalEventResult,
)
from ai_platform.ports.event_bus import (
    DeliveryHandle,
    EventBusDelivery,
    LogicalChannel,
    LogicalSubscription,
)
from ai_platform.runtime.consumer import DeliveryHandlingDisposition
from ai_platform.runtime.contracts import JsonSchemaMessageValidator
from ai_platform.runtime.handlers import (
    ExecuteTaskDeliveryHandler,
    TerminalOutcomeDeliveryHandler,
)
from ai_platform.shared.outcomes import AgentOutcome

MESSAGE_ID = "018f23a7-6b4d-7c91-8a2e-123456789abc"
COMMAND_ID = "018f23a7-6b4d-7c91-8a2e-123456789abd"
WORKFLOW_ID = "018f23a7-6b4d-7c91-8a2e-123456789abe"
TASK_ID = "018f23a7-6b4d-7c91-8a2e-123456789abf"
ATTEMPT_ID = "018f23a7-6b4d-7c91-8a2e-123456789ac0"
AGENT_ID = "018f23a7-6b4d-7c91-8a2e-123456789ac1"
NOW = datetime(2026, 8, 1, 12, tzinfo=UTC)


def _schema(contract_name: str) -> dict[str, object]:
    return {
        "type": "object",
        "required": [
            "message_id",
            "contract_name",
            "contract_version",
            "correlation_id",
            "causation_id",
            "workflow_id",
            "task_id",
            "task_attempt_id",
            "producer",
            "payload",
        ],
        "properties": {
            "contract_name": {"const": contract_name},
            "contract_version": {"const": "1.0"},
        },
    }


def _validator() -> JsonSchemaMessageValidator:
    return JsonSchemaMessageValidator(
        {
            ("ExecuteTask", "1.0"): _schema("ExecuteTask"),
            ("TaskCompleted", "1.0"): _schema("TaskCompleted"),
            ("TaskFailed", "1.0"): _schema("TaskFailed"),
        }
    )


def _delivery(channel: LogicalChannel, value: dict[str, object] | bytes) -> EventBusDelivery:
    raw = value if isinstance(value, bytes) else json.dumps(value).encode()
    return EventBusDelivery(
        handle=DeliveryHandle("delivery"),
        subscription=LogicalSubscription("logical-handler", channel),
        ordering_key=WORKFLOW_ID.encode(),
        value=raw,
        headers=(),
    )


def _command() -> dict[str, object]:
    return {
        "message_id": COMMAND_ID,
        "contract_name": "ExecuteTask",
        "contract_version": "1.0",
        "correlation_id": MESSAGE_ID,
        "causation_id": None,
        "workflow_id": WORKFLOW_ID,
        "task_id": TASK_ID,
        "task_attempt_id": ATTEMPT_ID,
        "producer": {"component": "orchestrator", "instance_id": MESSAGE_ID},
        "payload": {
            "input": "one two",
            "capability": "text.word-count",
            "capability_version": "1.0",
            "selected_agent": {"component": "test-agent", "instance_id": AGENT_ID},
            "task_result_deadline": "2026-08-01T12:01:00Z",
        },
    }


def _outcome() -> dict[str, object]:
    return {
        "message_id": MESSAGE_ID,
        "contract_name": "TaskCompleted",
        "contract_version": "1.0",
        "correlation_id": MESSAGE_ID,
        "causation_id": COMMAND_ID,
        "workflow_id": WORKFLOW_ID,
        "task_id": TASK_ID,
        "task_attempt_id": ATTEMPT_ID,
        "producer": {"component": "test-agent", "instance_id": AGENT_ID},
        "payload": {
            "text": "one two",
            "word_count": 2,
            "completed_at": "2026-08-01T12:00:01Z",
            "capability": "text.word-count",
            "capability_version": "1.0",
        },
    }


@dataclass
class _Quarantine:
    confirmed: bool = True
    reasons: list[str] = field(default_factory=list)

    async def quarantine(self, delivery: EventBusDelivery, **values: object) -> bool:
        del delivery
        self.reasons.append(str(values["safe_failure_code"]))
        return self.confirmed


@dataclass
class _Executor:
    contexts: list[ExecuteTaskContext] = field(default_factory=list)

    async def handle(self, context: ExecuteTaskContext, *, now: datetime) -> TestAgentResult:
        self.contexts.append(context)
        return TestAgentResult(
            disposition=TestAgentDisposition.COMPLETED,
            outcome=AgentOutcome(
                task_attempt_id=context.task_attempt_id,
                completed_at=now,
                word_count=2,
            ),
        )


@dataclass
class _TerminalProcessor:
    disposition: TerminalDisposition
    calls: list[dict[str, object]] = field(default_factory=list)

    async def process(self, **values: object) -> TerminalEventResult:
        self.calls.append(dict(values))
        return TerminalEventResult(disposition=self.disposition, workflow=None)


def test_valid_command_is_executed_after_target_and_key_validation() -> None:
    async def run() -> None:
        executor = _Executor()
        handler = ExecuteTaskDeliveryHandler(
            validator=_validator(),
            executor=executor,
            quarantine=_Quarantine(),
            expected_orchestrator_component="orchestrator",
            expected_agent_component="test-agent",
            expected_agent_id=AGENT_ID,
        )
        result = await handler.handle(_delivery(LogicalChannel.TASK_COMMANDS, _command()))
        assert result is DeliveryHandlingDisposition.DURABLY_PROCESSED
        assert executor.contexts[0].input_text == "one two"
        assert len(executor.contexts[0].command_digest) == 64

    asyncio.run(run())


def test_invalid_message_advances_only_after_durable_quarantine() -> None:
    async def run(confirmed: bool) -> DeliveryHandlingDisposition:
        handler = ExecuteTaskDeliveryHandler(
            validator=_validator(),
            executor=_Executor(),
            quarantine=_Quarantine(confirmed=confirmed),
            expected_orchestrator_component="orchestrator",
            expected_agent_component="test-agent",
            expected_agent_id=AGENT_ID,
        )
        return await handler.handle(_delivery(LogicalChannel.TASK_COMMANDS, b"not-json"))

    assert asyncio.run(run(True)) is DeliveryHandlingDisposition.DURABLY_QUARANTINED
    assert asyncio.run(run(False)) is DeliveryHandlingDisposition.PERMANENT


def test_command_target_mismatch_is_quarantined_without_execution() -> None:
    async def run() -> None:
        command = _command()
        payload = command["payload"]
        assert isinstance(payload, dict)
        payload["selected_agent"] = {"component": "other", "instance_id": AGENT_ID}
        quarantine = _Quarantine()
        executor = _Executor()
        handler = ExecuteTaskDeliveryHandler(
            validator=_validator(),
            executor=executor,
            quarantine=quarantine,
            expected_orchestrator_component="orchestrator",
            expected_agent_component="test-agent",
            expected_agent_id=AGENT_ID,
        )
        result = await handler.handle(_delivery(LogicalChannel.TASK_COMMANDS, command))
        assert result is DeliveryHandlingDisposition.DURABLY_QUARANTINED
        assert quarantine.reasons == ["COMMAND_TARGET_MISMATCH"]
        assert executor.contexts == []

    asyncio.run(run())


def test_command_producer_mismatch_is_quarantined_without_execution() -> None:
    async def run() -> None:
        command = _command()
        command["producer"] = {"component": "unexpected", "instance_id": MESSAGE_ID}
        quarantine = _Quarantine()
        executor = _Executor()
        handler = ExecuteTaskDeliveryHandler(
            validator=_validator(),
            executor=executor,
            quarantine=quarantine,
            expected_orchestrator_component="orchestrator",
            expected_agent_component="test-agent",
            expected_agent_id=AGENT_ID,
        )
        result = await handler.handle(_delivery(LogicalChannel.TASK_COMMANDS, command))
        assert result is DeliveryHandlingDisposition.DURABLY_QUARANTINED
        assert quarantine.reasons == ["COMMAND_PRODUCER_MISMATCH"]
        assert executor.contexts == []

    asyncio.run(run())


@pytest.mark.parametrize(
    ("terminal", "expected"),
    [
        (TerminalDisposition.APPLIED, DeliveryHandlingDisposition.DURABLY_PROCESSED),
        (TerminalDisposition.DUPLICATE, DeliveryHandlingDisposition.DUPLICATE),
        (TerminalDisposition.LATE_AFTER_TERMINAL, DeliveryHandlingDisposition.LATE),
    ],
)
def test_terminal_durable_disposition_controls_acknowledgement(
    terminal: TerminalDisposition, expected: DeliveryHandlingDisposition
) -> None:
    async def run() -> None:
        processor = _TerminalProcessor(terminal)
        handler = TerminalOutcomeDeliveryHandler(
            validator=_validator(),
            processor=processor,
            quarantine=_Quarantine(),
            environment="development",
            logical_consumer_id="outcome-handler-v1",
        )
        result = await handler.handle(_delivery(LogicalChannel.TASK_OUTCOMES, _outcome()))
        assert result is expected
        assert processor.calls[0]["task_attempt_id"] == ATTEMPT_ID

    asyncio.run(run())


def test_terminal_identity_conflict_requires_quarantine_confirmation() -> None:
    async def run() -> None:
        quarantine = _Quarantine()
        handler = TerminalOutcomeDeliveryHandler(
            validator=_validator(),
            processor=_TerminalProcessor(TerminalDisposition.PERMANENT_CONFLICT),
            quarantine=quarantine,
            environment="development",
            logical_consumer_id="outcome-handler-v1",
        )
        result = await handler.handle(_delivery(LogicalChannel.TASK_OUTCOMES, _outcome()))
        assert result is DeliveryHandlingDisposition.DURABLY_QUARANTINED
        assert quarantine.reasons == ["TERMINAL_IDENTITY_CONFLICT"]

    asyncio.run(run())


def test_terminal_producer_identity_is_forwarded_for_recorded_selection_validation() -> None:
    async def run() -> None:
        outcome = _outcome()
        outcome["producer"] = {"component": "unexpected", "instance_id": AGENT_ID}
        quarantine = _Quarantine()
        processor = _TerminalProcessor(TerminalDisposition.APPLIED)
        handler = TerminalOutcomeDeliveryHandler(
            validator=_validator(),
            processor=processor,
            quarantine=quarantine,
            environment="development",
            logical_consumer_id="outcome-handler-v1",
        )
        result = await handler.handle(_delivery(LogicalChannel.TASK_OUTCOMES, outcome))
        assert result is DeliveryHandlingDisposition.DURABLY_PROCESSED
        assert quarantine.reasons == []
        assert processor.calls[0]["producer_component"] == "unexpected"

    asyncio.run(run())
