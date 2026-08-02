"""Atomic terminal-event processing (Vertical Slice 01, Section 11)."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ai_platform.orchestrator.domain.audit import AuditRecord
from ai_platform.orchestrator.domain.workflow import Workflow
from ai_platform.ports.persistence.transactions import (
    TerminalOutcomeIntent,
    TerminalOutcomeTransactionPort,
)
from ai_platform.shared.identifiers import (
    ActorId,
    CorrelationId,
    MessageId,
    TaskAttemptId,
    TaskId,
    WorkflowId,
)
from ai_platform.shared.outcomes import AgentOutcome

_SYSTEM_ACTOR_ID = ActorId("system:agent-outcome-consumer")


class TerminalDisposition(Enum):
    APPLIED = "APPLIED"
    DUPLICATE = "DUPLICATE"
    LATE_AFTER_TERMINAL = "LATE_AFTER_TERMINAL"
    PERMANENT_CONFLICT = "PERMANENT_CONFLICT"


@dataclass(frozen=True, slots=True)
class TerminalEventResult:
    disposition: TerminalDisposition
    workflow: Workflow | None


class TerminalEventProcessor:
    """Pass one validated immutable event to the atomic persistence boundary."""

    def __init__(self, *, transaction: TerminalOutcomeTransactionPort) -> None:
        self._transaction = transaction

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
    ) -> TerminalEventResult:
        result = await self._transaction.apply_terminal_outcome(
            TerminalOutcomeIntent(
                environment=environment,
                logical_consumer_id=logical_consumer_id,
                validated_message_id=validated_message_id,
                immutable_message_digest=immutable_message_digest,
                workflow_id=workflow_id,
                task_id=task_id,
                task_attempt_id=task_attempt_id,
                correlation_id=correlation_id,
                causation_message_id=causation_message_id,
                producer_component=producer_component,
                producer_instance_id=producer_instance_id,
                capability_name=capability_name,
                capability_version=capability_version,
                result_text=result_text,
                agent_evidence_component=agent_evidence_component,
                agent_evidence_instance_id=agent_evidence_instance_id,
                outcome=outcome,
                occurred_at=occurred_at,
                audit=AuditRecord(
                    kind="workflow_terminal_outcome",
                    workflow_id=workflow_id,
                    occurred_at=occurred_at,
                    actor_id=_SYSTEM_ACTOR_ID,
                    details={
                        "message_id": str(validated_message_id),
                        "task_attempt_id": str(task_attempt_id),
                    },
                ),
            )
        )
        return TerminalEventResult(
            disposition=TerminalDisposition(result.disposition.value),
            workflow=result.workflow,
        )
