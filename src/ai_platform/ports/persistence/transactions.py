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
from ai_platform.orchestrator.domain.states import WorkflowState
from ai_platform.orchestrator.domain.task import Task, TaskAttempt
from ai_platform.orchestrator.domain.workflow import Workflow
from ai_platform.shared.identifiers import (
    ActorId,
    AgentId,
    CorrelationId,
    MessageId,
    OwnerSubjectId,
    RequestId,
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
    # ADR-0024: written into orchestrator.submission_history in the same
    # atomic transaction, only on the `created=True` (genuinely new
    # submission) path -- never on a replay. Defaulted so the many existing
    # call sites exercising unrelated submission-transaction concerns don't
    # need to change.
    capability_name: str = ""
    capability_version: str = ""
    input_text: str = ""


@dataclass(frozen=True, slots=True)
class SubmissionCommitResult:
    resolution: AcceptedRequestResolution
    workflow: Workflow
    created: bool


@dataclass(frozen=True, slots=True)
class SubmissionHistoryEntry:
    """One past submission (ADR-0024), joined against its workflow's current
    state/result at read time so it can never go stale."""

    workflow_id: WorkflowId
    request_id: RequestId
    correlation_id: CorrelationId
    capability_name: str
    capability_version: str
    input_text: str
    submitted_at: datetime
    state: WorkflowState
    result_data: dict[str, object] | None
    failure_code: str | None
    failure_detail: str | None


class SubmissionHistoryQueryPort(Protocol):
    async def list_recent(
        self,
        *,
        capability_name: str | None,
        limit: int,
        before: datetime | None,
    ) -> list[SubmissionHistoryEntry]:
        """Return up to `limit` submissions, newest first, optionally
        filtered to one capability and/or strictly before a cursor
        timestamp."""
        ...


class SubmissionTransactionPort(Protocol):
    async def commit_submission(self, intent: SubmissionCommitIntent) -> SubmissionCommitResult:
        """Atomically arbitrate and commit the complete submission unit."""
        ...


class InFlightWorkloadQueryPort(Protocol):
    async def count_in_flight_by_agent(self) -> dict[AgentId, int]:
        """Return, per Agent deployment, how many task attempts are
        currently DISPATCHED (claimed, no terminal outcome recorded yet).

        Read fresh on every call, same as `SubmissionHistoryQueryPort` --
        never a cached count. An Agent with no entry has zero in-flight
        work, not an unknown/error state.
        """
        ...


@dataclass(frozen=True, slots=True)
class CompletedAgentWork:
    receipt: AgentCompletedReceipt
    outcome: AgentOutcome
    event_outbox: AgentEventOutboxRecord


@dataclass(frozen=True, slots=True)
class ProviderCallUsageRecord:
    """Durable, redacted usage evidence for one resolved provider call
    (ADR-0014 Section 3).

    Attached to the outcome commit, never surfaced on the public API --
    the public `result` payload comes only from `AgentOutcome.result_data`
    (ADR-0015), consistent with ADR-0010's internal-evidence/
    public-disclosure separation.
    """

    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_seconds: float


@dataclass(frozen=True, slots=True)
class AgentOutcomeCommitIntent:
    completed_work: CompletedAgentWork
    audit: AuditRecord
    usage: ProviderCallUsageRecord | None = None


@dataclass(frozen=True, slots=True)
class AgentOutcomeCommitResult:
    completed_work: CompletedAgentWork
    created: bool


@dataclass(frozen=True, slots=True)
class ProviderCallClaimIntent:
    """A durable pre-call claim for a non-deterministic, provider-backed
    execution step (ADR-0014 Section 5).

    Recorded before the AI Router is invoked so a crash between claiming
    and receiving a provider response is detectable on redelivery --
    unlike `text.word-count`'s safe-to-recompute model, a redelivered
    command must never blindly re-call the provider.
    """

    task_attempt_id: TaskAttemptId
    command_message_id: MessageId
    command_digest: str
    claimed_at: datetime


@dataclass(frozen=True, slots=True)
class ExistingProviderCallClaim:
    command_message_id: MessageId
    command_digest: str
    claimed_at: datetime


@dataclass(frozen=True, slots=True)
class ProviderCallClaimResult:
    created: bool
    """True when this call durably recorded a new claim and the caller may
    proceed to invoke the provider. False when a claim for this
    `task_attempt_id` already existed -- the caller must not call the
    provider again; see `existing` to classify the redelivery."""
    existing: ExistingProviderCallClaim | None


class AgentOutcomeTransactionPort(Protocol):
    async def get_completed(self, task_attempt_id: TaskAttemptId) -> CompletedAgentWork | None: ...

    async def commit_outcome(self, intent: AgentOutcomeCommitIntent) -> AgentOutcomeCommitResult:
        """Atomically commit receipt, outcome, event outbox, audit, and usage."""
        ...

    async def claim_provider_call(self, intent: ProviderCallClaimIntent) -> ProviderCallClaimResult:
        """Durably record a pre-call claim (ADR-0014 Section 5).

        Called only by Agents with a non-deterministic, provider-backed
        execution step, before invoking the AI Router. `text.word-count`
        never calls this -- its execution is deterministic and free to
        recompute, so it has no claim to make.
        """
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
