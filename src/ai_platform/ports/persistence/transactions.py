"""Asynchronous, transaction-shaped persistence ports.

These ports expose complete application integrity units rather than database
transactions. Concrete adapters own connections, SQL ordering, commits,
rollbacks, locking, and retry classification (ADR-0006 Sections 4-5).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from ai_platform.agents.domain.outcomes import (
    AgentCompletedReceipt,
    AgentEventOutboxRecord,
)
from ai_platform.orchestrator.domain.accepted_request import (
    AcceptanceEvidence,
    AcceptedRequestKey,
)
from ai_platform.orchestrator.domain.audit import AuditRecord
from ai_platform.orchestrator.domain.recovery import OrchestratorOutboxRecord
from ai_platform.orchestrator.domain.task import Task, TaskAttempt
from ai_platform.orchestrator.domain.workflow import Workflow
from ai_platform.shared.identifiers import (
    ActorId,
    CorrelationId,
    MessageId,
    OwnerSubjectId,
    TaskAttemptId,
    TaskId,
    WorkflowId,
)
from ai_platform.shared.outcomes import AgentOutcome


@dataclass(frozen=True, slots=True)
class AcceptedRequestResolution:
    key: AcceptedRequestKey
    workflow_id: WorkflowId
    evidence: AcceptanceEvidence


class AcceptedRequestQueryPort(Protocol):
    async def resolve(self, key: AcceptedRequestKey) -> AcceptedRequestResolution | None: ...


class WorkflowQueryPort(Protocol):
    async def get(self, workflow_id: WorkflowId) -> Workflow | None: ...


class AuthorizedWorkflowQueryPort(Protocol):
    async def get_authorized(
        self,
        workflow_id: WorkflowId,
        *,
        environment: str,
        current_owner_subject_id: OwnerSubjectId,
    ) -> Workflow | None:
        """Return the workflow only when its current owner is authorized."""
        ...


class AcceptedRequestAccessDisposition(Enum):
    EQUIVALENT_REPLAY_AUTHORIZED = "EQUIVALENT_REPLAY_AUTHORIZED"
    FINGERPRINT_CONFLICT_AUTHORIZED = "FINGERPRINT_CONFLICT_AUTHORIZED"
    OWNER_INTENT_MISMATCH = "OWNER_INTENT_MISMATCH"


@dataclass(frozen=True, slots=True)
class AcceptedRequestAccessAuditRecord:
    """Durable current-invocation evidence for an occupied accepted key.

    This record is internal security evidence. It never changes the accepted
    request or workflow and is never included in a public response.
    """

    key: AcceptedRequestKey
    workflow_id: WorkflowId
    current_actor_id: ActorId
    resolved_owner_subject_id: OwnerSubjectId
    effective_correlation_id: CorrelationId
    policy_identity: str
    policy_revision: str
    policy_decision: str
    scope_mapping_revision: str
    authorization_evidence: str
    disposition: AcceptedRequestAccessDisposition
    occurred_at: datetime


class AcceptedRequestAccessAuditPort(Protocol):
    async def record_request_access(self, record: AcceptedRequestAccessAuditRecord) -> None:
        """Durably append access evidence before protected classification/disclosure."""
        ...


@dataclass(frozen=True, slots=True)
class SubmissionCommitIntent:
    key: AcceptedRequestKey
    evidence: AcceptanceEvidence
    workflow: Workflow
    task: Task
    task_attempt: TaskAttempt
    command_outbox: OrchestratorOutboxRecord
    audit: AuditRecord


@dataclass(frozen=True, slots=True)
class SubmissionCommitResult:
    resolution: AcceptedRequestResolution
    workflow: Workflow
    created: bool


class SubmissionTransactionPort(Protocol):
    async def commit_submission(self, intent: SubmissionCommitIntent) -> SubmissionCommitResult:
        """Atomically arbitrate and commit the complete submission unit."""
        ...


@dataclass(frozen=True, slots=True)
class CompletedAgentWork:
    receipt: AgentCompletedReceipt
    outcome: AgentOutcome
    event_outbox: AgentEventOutboxRecord


@dataclass(frozen=True, slots=True)
class AgentOutcomeCommitIntent:
    completed_work: CompletedAgentWork
    audit: AuditRecord


@dataclass(frozen=True, slots=True)
class AgentOutcomeCommitResult:
    completed_work: CompletedAgentWork
    created: bool


class AgentOutcomeTransactionPort(Protocol):
    async def get_completed(self, task_attempt_id: TaskAttemptId) -> CompletedAgentWork | None: ...

    async def commit_outcome(self, intent: AgentOutcomeCommitIntent) -> AgentOutcomeCommitResult:
        """Atomically commit receipt, outcome, event outbox, and audit."""
        ...


@dataclass(frozen=True, slots=True)
class TerminalOutcomeIntent:
    environment: str
    logical_consumer_id: str
    validated_message_id: MessageId
    immutable_message_digest: str
    workflow_id: WorkflowId
    task_id: TaskId
    task_attempt_id: TaskAttemptId
    correlation_id: CorrelationId
    causation_message_id: MessageId
    producer_component: str
    producer_instance_id: str
    capability_name: str
    capability_version: str
    result_text: str | None
    agent_evidence_component: str | None
    agent_evidence_instance_id: str | None
    outcome: AgentOutcome
    occurred_at: datetime
    audit: AuditRecord


class TerminalPersistenceDisposition(Enum):
    APPLIED = "APPLIED"
    DUPLICATE = "DUPLICATE"
    LATE_AFTER_TERMINAL = "LATE_AFTER_TERMINAL"
    PERMANENT_CONFLICT = "PERMANENT_CONFLICT"


@dataclass(frozen=True, slots=True)
class TerminalOutcomeCommitResult:
    disposition: TerminalPersistenceDisposition
    workflow: Workflow | None


class TerminalOutcomeTransactionPort(Protocol):
    async def apply_terminal_outcome(
        self, intent: TerminalOutcomeIntent
    ) -> TerminalOutcomeCommitResult:
        """Atomically resolve inbox identity and apply or reject the outcome."""
        ...


@dataclass(frozen=True, slots=True)
class ExpiredAttempt:
    workflow_id: WorkflowId
    task_attempt_id: TaskAttemptId


class DeadlinePersistenceDisposition(Enum):
    APPLIED = "APPLIED"
    ALREADY_TERMINAL = "ALREADY_TERMINAL"
    NOT_DUE = "NOT_DUE"


class DeadlineTransactionPort(Protocol):
    async def find_expired(self, *, now: datetime, limit: int) -> tuple[ExpiredAttempt, ...]: ...

    async def expire(
        self,
        candidate: ExpiredAttempt,
        *,
        now: datetime,
        audit: AuditRecord,
    ) -> DeadlinePersistenceDisposition:
        """Lock, revalidate, and atomically commit a deadline transition."""
        ...
