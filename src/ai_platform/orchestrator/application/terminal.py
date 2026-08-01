"""Terminal event processing (vertical-slice-01.md Section 11,
"Result-Consumption Transaction").

Inbox disposition is checked first for idempotency; only a not-yet-seen
message applies a transition through the Workflow aggregate. A late event
that arrives after the workflow is already terminal (e.g. the deadline
reconciler won the race) is recorded but never mutates the aggregate,
relying on `TerminalWorkflowError` as the race-safety net.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ai_platform.orchestrator.domain.audit import AuditRecord
from ai_platform.orchestrator.domain.errors import TerminalWorkflowError
from ai_platform.orchestrator.domain.recovery import OrchestratorInboxRecord
from ai_platform.orchestrator.domain.results import WorkflowFailure, WorkflowResult
from ai_platform.orchestrator.domain.workflow import Workflow
from ai_platform.ports.persistence.audit import AuditRepositoryPort
from ai_platform.ports.persistence.orchestrator_inbox import OrchestratorInboxRepositoryPort
from ai_platform.ports.persistence.workflow import WorkflowRepositoryPort
from ai_platform.shared.identifiers import ActorId, MessageId, WorkflowId
from ai_platform.shared.outcomes import AgentOutcome

_SYSTEM_ACTOR_ID = ActorId("system:agent-outcome-consumer")


class TerminalDisposition(Enum):
    APPLIED = "APPLIED"
    DUPLICATE = "DUPLICATE"
    LATE_AFTER_TERMINAL = "LATE_AFTER_TERMINAL"


@dataclass(frozen=True, slots=True)
class TerminalEventResult:
    disposition: TerminalDisposition
    workflow: Workflow | None


class TerminalEventProcessor:
    def __init__(
        self,
        *,
        workflow_repo: WorkflowRepositoryPort,
        inbox_repo: OrchestratorInboxRepositoryPort,
        audit_repo: AuditRepositoryPort,
    ) -> None:
        self._workflow_repo = workflow_repo
        self._inbox_repo = inbox_repo
        self._audit_repo = audit_repo

    def process(
        self,
        *,
        environment: str,
        logical_consumer_id: str,
        validated_message_id: MessageId,
        workflow_id: WorkflowId,
        outcome: AgentOutcome,
        occurred_at: datetime,
    ) -> TerminalEventResult:
        existing_disposition = self._inbox_repo.get_disposition(
            environment, logical_consumer_id, validated_message_id
        )
        if existing_disposition is not None:
            return TerminalEventResult(
                disposition=TerminalDisposition.DUPLICATE,
                workflow=self._workflow_repo.get_by_id(workflow_id),
            )

        workflow = self._workflow_repo.get_by_id(workflow_id)
        if workflow is None:
            raise ValueError(f"No workflow found for {workflow_id}")

        expected_revision = workflow.revision
        try:
            if outcome.word_count is not None:
                workflow.complete(
                    WorkflowResult(word_count=outcome.word_count), occurred_at=occurred_at
                )
                disposition_label = "completed"
            else:
                workflow.fail(
                    WorkflowFailure(
                        code=outcome.failure_code or "TASK_EXECUTION_FAILED",
                        detail=outcome.summary or "",
                    ),
                    occurred_at=occurred_at,
                )
                disposition_label = "failed"
        except TerminalWorkflowError:
            self._inbox_repo.record_disposition(
                OrchestratorInboxRecord(
                    environment=environment,
                    logical_consumer_id=logical_consumer_id,
                    validated_message_id=validated_message_id,
                    disposition="late_after_terminal",
                    recorded_at=occurred_at,
                )
            )
            return TerminalEventResult(
                disposition=TerminalDisposition.LATE_AFTER_TERMINAL, workflow=workflow
            )

        self._workflow_repo.save_transition(workflow, expected_revision=expected_revision)
        self._inbox_repo.record_disposition(
            OrchestratorInboxRecord(
                environment=environment,
                logical_consumer_id=logical_consumer_id,
                validated_message_id=validated_message_id,
                disposition=disposition_label,
                recorded_at=occurred_at,
            )
        )
        self._audit_repo.append(
            AuditRecord(
                kind=f"workflow_{disposition_label}",
                workflow_id=workflow_id,
                occurred_at=occurred_at,
                actor_id=_SYSTEM_ACTOR_ID,
            )
        )
        return TerminalEventResult(disposition=TerminalDisposition.APPLIED, workflow=workflow)
