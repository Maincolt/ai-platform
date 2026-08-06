"""Validated command and outcome delivery handlers."""

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum
from typing import Protocol, cast

from ai_platform.agents.test_agent.execution_context import ExecuteTaskContext
from ai_platform.orchestrator.application.terminal import (
    TerminalDisposition,
    TerminalEventResult,
)
from ai_platform.ports.event_bus import EventBusDelivery, LogicalChannel
from ai_platform.runtime.consumer import DeliveryHandlingDisposition
from ai_platform.runtime.contracts import (
    JsonSchemaMessageValidator,
    MessageValidationError,
    ValidatedMessage,
)
from ai_platform.shared.identifiers import (
    CorrelationId,
    MessageId,
    TaskAttemptId,
    TaskId,
    WorkflowId,
)
from ai_platform.shared.outcomes import AgentOutcome


class QuarantineCoordinatorPort(Protocol):
    async def quarantine(
        self,
        delivery: EventBusDelivery,
        *,
        safe_failure_code: str,
        original_bytes_sha256: str,
        validated_message_id: MessageId | None,
    ) -> bool:
        """Return true only after quarantine confirmation is durable."""
        ...


class ExecutorResult(Protocol):
    """Structural result shape shared by every Agent executor's `handle()`.

    Deliberately capability-agnostic: `TestAgentResult` and
    `SummarizeAgentResult` are separate dataclasses with their own
    disposition enums (`TestAgentDisposition`, `SummarizeAgentDisposition`),
    not a shared base type -- each Agent deployable owns its own result
    shape (ADR-0001, ADR-0007 Section 1). Only `disposition` is used here,
    compared by enum member name so this handler needs no per-Agent import.
    """

    @property
    def disposition(self) -> Enum: ...


class CommandExecutorPort(Protocol):
    async def handle(self, context: ExecuteTaskContext, *, now: datetime) -> ExecutorResult: ...


class TerminalProcessorPort(Protocol):
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
    ) -> TerminalEventResult: ...


class ExecuteTaskDeliveryHandler:
    def __init__(
        self,
        *,
        validator: JsonSchemaMessageValidator,
        executor: CommandExecutorPort,
        quarantine: QuarantineCoordinatorPort,
        expected_orchestrator_component: str,
        expected_agent_component: str,
        expected_agent_id: str,
    ) -> None:
        self._validator = validator
        self._executor = executor
        self._quarantine = quarantine
        self._expected_orchestrator_component = expected_orchestrator_component
        self._expected_agent_component = expected_agent_component
        self._expected_agent_id = expected_agent_id

    async def handle(self, delivery: EventBusDelivery) -> DeliveryHandlingDisposition:
        validated = await _validate_or_quarantine(self._validator, self._quarantine, delivery)
        if isinstance(validated, DeliveryHandlingDisposition):
            return validated
        data = validated.data
        if delivery.subscription.channel is not LogicalChannel.TASK_COMMANDS:
            return await _quarantine_validated(
                self._quarantine, delivery, validated, "WRONG_LOGICAL_CHANNEL"
            )
        payload = _mapping(data, "payload")
        producer = _mapping(data, "producer")
        if _string(producer, "component") != self._expected_orchestrator_component:
            return await _quarantine_validated(
                self._quarantine, delivery, validated, "COMMAND_PRODUCER_MISMATCH"
            )
        selected_agent = _mapping(payload, "selected_agent")
        if (
            _string(selected_agent, "component") != self._expected_agent_component
            or _string(selected_agent, "instance_id") != self._expected_agent_id
        ):
            return await _quarantine_validated(
                self._quarantine, delivery, validated, "COMMAND_TARGET_MISMATCH"
            )
        workflow_id = WorkflowId(_string(data, "workflow_id"))
        if delivery.ordering_key != str(workflow_id).encode():
            return await _quarantine_validated(
                self._quarantine, delivery, validated, "ORDERING_KEY_MISMATCH"
            )
        context = ExecuteTaskContext(
            workflow_id=workflow_id,
            task_id=TaskId(_string(data, "task_id")),
            task_attempt_id=TaskAttemptId(_string(data, "task_attempt_id")),
            correlation_id=CorrelationId(_string(data, "correlation_id")),
            command_message_id=validated.message_id,
            command_digest=validated.immutable_sha256,
            input_text=_string(payload, "input"),
            capability_name=_string(payload, "capability"),
            capability_version=_string(payload, "capability_version"),
            task_result_deadline=_datetime(payload, "task_result_deadline"),
        )
        result = await self._executor.handle(context, now=datetime.now(UTC))
        if result.disposition.name == "DUPLICATE_RESOLVED":
            return DeliveryHandlingDisposition.DUPLICATE
        return DeliveryHandlingDisposition.DURABLY_PROCESSED


class TerminalOutcomeDeliveryHandler:
    def __init__(
        self,
        *,
        validator: JsonSchemaMessageValidator,
        processor: TerminalProcessorPort,
        quarantine: QuarantineCoordinatorPort,
        environment: str,
        logical_consumer_id: str,
    ) -> None:
        self._validator = validator
        self._processor = processor
        self._quarantine = quarantine
        self._environment = environment
        self._logical_consumer_id = logical_consumer_id

    async def handle(self, delivery: EventBusDelivery) -> DeliveryHandlingDisposition:
        validated = await _validate_or_quarantine(self._validator, self._quarantine, delivery)
        if isinstance(validated, DeliveryHandlingDisposition):
            return validated
        data = validated.data
        if delivery.subscription.channel is not LogicalChannel.TASK_OUTCOMES:
            return await _quarantine_validated(
                self._quarantine, delivery, validated, "WRONG_LOGICAL_CHANNEL"
            )
        workflow_id = WorkflowId(_string(data, "workflow_id"))
        if delivery.ordering_key != str(workflow_id).encode():
            return await _quarantine_validated(
                self._quarantine, delivery, validated, "ORDERING_KEY_MISMATCH"
            )
        payload = _mapping(data, "payload")
        task_attempt_id = TaskAttemptId(_string(data, "task_attempt_id"))
        contract_name = _string(data, "contract_name")
        completed_at_key = "completed_at" if contract_name == "TaskCompleted" else "failed_at"
        outcome = AgentOutcome(
            task_attempt_id=task_attempt_id,
            completed_at=_datetime(payload, completed_at_key),
            result_data=_optional_json_object(payload, "result"),
            failure_code=_optional_string(payload, "failure_code"),
            summary=_optional_string(payload, "summary"),
        )
        producer = _mapping(data, "producer")
        agent_evidence = payload.get("agent")
        evidence_component: str | None = None
        evidence_instance_id: str | None = None
        if agent_evidence is not None:
            evidence = cast(Mapping[str, object], agent_evidence)
            evidence_component = _optional_string(evidence, "component")
            evidence_instance_id = _optional_string(evidence, "instance_id")
        result = await self._processor.process(
            environment=self._environment,
            logical_consumer_id=self._logical_consumer_id,
            validated_message_id=validated.message_id,
            immutable_message_digest=validated.immutable_sha256,
            workflow_id=workflow_id,
            task_id=TaskId(_string(data, "task_id")),
            task_attempt_id=task_attempt_id,
            correlation_id=CorrelationId(_string(data, "correlation_id")),
            causation_message_id=MessageId(_string(data, "causation_id")),
            producer_component=_string(producer, "component"),
            producer_instance_id=_string(producer, "instance_id"),
            capability_name=_string(payload, "capability"),
            capability_version=_string(payload, "capability_version"),
            result_text=_string(payload, "text") if contract_name == "TaskCompleted" else None,
            agent_evidence_component=evidence_component,
            agent_evidence_instance_id=evidence_instance_id,
            outcome=outcome,
            occurred_at=outcome.completed_at,
        )
        if result.disposition is TerminalDisposition.APPLIED:
            return DeliveryHandlingDisposition.DURABLY_PROCESSED
        if result.disposition is TerminalDisposition.DUPLICATE:
            return DeliveryHandlingDisposition.DUPLICATE
        if result.disposition is TerminalDisposition.LATE_AFTER_TERMINAL:
            return DeliveryHandlingDisposition.LATE
        return await _quarantine_validated(
            self._quarantine, delivery, validated, "TERMINAL_IDENTITY_CONFLICT"
        )


async def _validate_or_quarantine(
    validator: JsonSchemaMessageValidator,
    quarantine: QuarantineCoordinatorPort,
    delivery: EventBusDelivery,
) -> ValidatedMessage | DeliveryHandlingDisposition:
    try:
        return validator.validate(delivery.value)
    except MessageValidationError as exc:
        raw = delivery.value or b""
        confirmed = await quarantine.quarantine(
            delivery,
            safe_failure_code=exc.reason_code,
            original_bytes_sha256=hashlib.sha256(raw).hexdigest(),
            validated_message_id=exc.validated_message_id,
        )
        if confirmed:
            return DeliveryHandlingDisposition.DURABLY_QUARANTINED
        return DeliveryHandlingDisposition.PERMANENT


async def _quarantine_validated(
    quarantine: QuarantineCoordinatorPort,
    delivery: EventBusDelivery,
    validated: ValidatedMessage,
    reason_code: str,
) -> DeliveryHandlingDisposition:
    confirmed = await quarantine.quarantine(
        delivery,
        safe_failure_code=reason_code,
        original_bytes_sha256=validated.immutable_sha256,
        validated_message_id=validated.message_id,
    )
    if confirmed:
        return DeliveryHandlingDisposition.DURABLY_QUARANTINED
    return DeliveryHandlingDisposition.PERMANENT


def _mapping(value: Mapping[str, object], key: str) -> Mapping[str, object]:
    nested = value[key]
    if not isinstance(nested, dict):
        raise ValueError(f"Validated property {key} is not an object")
    return cast(dict[str, object], nested)


def _string(value: Mapping[str, object], key: str) -> str:
    item = value[key]
    if not isinstance(item, str):
        raise ValueError(f"Validated property {key} is not a string")
    return item


def _optional_string(value: Mapping[str, object], key: str) -> str | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, str):
        raise ValueError(f"Validated property {key} is not a string")
    return item


def _optional_json_object(value: Mapping[str, object], key: str) -> Mapping[str, object] | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, dict):
        raise ValueError(f"Validated property {key} is not an object")
    return cast(dict[str, object], item)


def _datetime(value: Mapping[str, object], key: str) -> datetime:
    return datetime.fromisoformat(_string(value, key).replace("Z", "+00:00"))
