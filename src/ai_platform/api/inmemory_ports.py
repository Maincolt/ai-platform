"""Non-production, in-memory reference implementations of the Phase 2/3
ports, used to make the Workflow API actually runnable before Phase 6
introduces real PostgreSQL/Kafka adapters.

Data does not survive process restart and there is no real transactional
guarantee across these in-memory stores; this is explicitly documented as
a Sprint 5 stand-in, not a concrete adapter (see docs/sprint-5/consilium.md).
"""

import copy
from dataclasses import dataclass, field

from ai_platform.agents.domain.outcomes import AgentCompletedReceipt, AgentEventOutboxRecord
from ai_platform.orchestrator.domain.accepted_request import (
    AcceptanceEvidence,
    AcceptedRequestKey,
)
from ai_platform.orchestrator.domain.audit import AuditRecord
from ai_platform.orchestrator.domain.recovery import (
    OrchestratorInboxRecord,
    OrchestratorOutboxRecord,
)
from ai_platform.orchestrator.domain.task import Task, TaskAttempt
from ai_platform.orchestrator.domain.workflow import Workflow
from ai_platform.ports.persistence.accepted_request import AcceptedRequestRepositoryPort
from ai_platform.ports.persistence.agent import (
    AgentOutcomeRepositoryPort,
    AgentReceiptRepositoryPort,
)
from ai_platform.ports.persistence.audit import AuditRepositoryPort
from ai_platform.ports.persistence.orchestrator_inbox import OrchestratorInboxRepositoryPort
from ai_platform.ports.persistence.outbox import (
    AgentEventOutboxRepositoryPort,
    OrchestratorOutboxRepositoryPort,
)
from ai_platform.ports.persistence.task import TaskAttemptRepositoryPort, TaskRepositoryPort
from ai_platform.ports.persistence.workflow import WorkflowRepositoryPort
from ai_platform.shared.identifiers import MessageId, TaskAttemptId, TaskId, WorkflowId
from ai_platform.shared.outcomes import AgentOutcome


@dataclass
class InMemoryAcceptedRequestRepository(AcceptedRequestRepositoryPort):
    _mappings: dict[AcceptedRequestKey, tuple[WorkflowId, AcceptanceEvidence]] = field(
        default_factory=dict
    )

    def create_or_resolve(
        self,
        key: AcceptedRequestKey,
        evidence: AcceptanceEvidence,
        workflow_id: WorkflowId,
    ) -> tuple[WorkflowId, AcceptanceEvidence, bool]:
        existing = self._mappings.get(key)
        if existing is not None:
            return (*existing, False)
        self._mappings[key] = (workflow_id, evidence)
        return (workflow_id, evidence, True)


@dataclass
class InMemoryWorkflowRepository(WorkflowRepositoryPort):
    """Stores an immutable snapshot copy per revision so mutating a live
    `Workflow` object does not silently change what is "durably stored"."""

    _snapshots: dict[WorkflowId, Workflow] = field(default_factory=dict)
    _stored_revisions: dict[WorkflowId, int] = field(default_factory=dict)

    def get_by_id(self, workflow_id: WorkflowId) -> Workflow | None:
        return self._snapshots.get(workflow_id)

    def save_new(self, workflow: Workflow) -> None:
        self._snapshots[workflow.workflow_id] = copy.deepcopy(workflow)
        self._stored_revisions[workflow.workflow_id] = workflow.revision

    def save_transition(self, workflow: Workflow, *, expected_revision: int) -> None:
        stored_revision = self._stored_revisions.get(workflow.workflow_id)
        if stored_revision != expected_revision:
            raise ValueError(
                f"Revision conflict: expected {expected_revision}, stored is {stored_revision}"
            )
        self._snapshots[workflow.workflow_id] = copy.deepcopy(workflow)
        self._stored_revisions[workflow.workflow_id] = workflow.revision


@dataclass
class InMemoryTaskRepository(TaskRepositoryPort):
    _tasks: dict[TaskId, Task] = field(default_factory=dict)

    def get_by_id(self, task_id: TaskId) -> Task | None:
        return self._tasks.get(task_id)

    def save(self, task: Task) -> None:
        self._tasks[task.task_id] = task


@dataclass
class InMemoryTaskAttemptRepository(TaskAttemptRepositoryPort):
    _attempts: dict[TaskAttemptId, TaskAttempt] = field(default_factory=dict)

    def get_by_id(self, task_attempt_id: TaskAttemptId) -> TaskAttempt | None:
        return self._attempts.get(task_attempt_id)

    def save(self, attempt: TaskAttempt) -> None:
        self._attempts[attempt.task_attempt_id] = attempt


@dataclass
class InMemoryOrchestratorOutboxRepository(OrchestratorOutboxRepositoryPort):
    records: list[OrchestratorOutboxRecord] = field(default_factory=list)

    def enqueue(self, record: OrchestratorOutboxRecord) -> None:
        self.records.append(record)

    def claim_next(
        self, workflow_id: WorkflowId, *, fencing_token: str
    ) -> OrchestratorOutboxRecord | None:
        raise NotImplementedError("No outbox publisher exists before Phase 6")

    def mark_publication_state(
        self, message_id: MessageId, state: object, *, fencing_token: str
    ) -> None:
        raise NotImplementedError("No outbox publisher exists before Phase 6")


@dataclass
class InMemoryAgentEventOutboxRepository(AgentEventOutboxRepositoryPort):
    records: list[AgentEventOutboxRecord] = field(default_factory=list)

    def enqueue(self, record: AgentEventOutboxRecord) -> None:
        self.records.append(record)

    def claim_next(
        self, workflow_id: WorkflowId, *, fencing_token: str
    ) -> AgentEventOutboxRecord | None:
        raise NotImplementedError("No outbox publisher exists before Phase 6")

    def mark_publication_state(
        self, message_id: MessageId, state: object, *, fencing_token: str
    ) -> None:
        raise NotImplementedError("No outbox publisher exists before Phase 6")


@dataclass
class InMemoryAuditRepository(AuditRepositoryPort):
    records: list[AuditRecord] = field(default_factory=list)

    def append(self, record: AuditRecord) -> None:
        self.records.append(record)


@dataclass
class InMemoryOrchestratorInboxRepository(OrchestratorInboxRepositoryPort):
    _records: dict[tuple[str, str, MessageId], OrchestratorInboxRecord] = field(
        default_factory=dict
    )

    def get_disposition(
        self, environment: str, logical_consumer_id: str, validated_message_id: MessageId
    ) -> OrchestratorInboxRecord | None:
        return self._records.get((environment, logical_consumer_id, validated_message_id))

    def record_disposition(self, record: OrchestratorInboxRecord) -> None:
        key = (record.environment, record.logical_consumer_id, record.validated_message_id)
        self._records.setdefault(key, record)


@dataclass
class InMemoryAgentReceiptRepository(AgentReceiptRepositoryPort):
    _receipts: dict[TaskAttemptId, AgentCompletedReceipt] = field(default_factory=dict)

    def get_by_attempt(self, task_attempt_id: TaskAttemptId) -> AgentCompletedReceipt | None:
        return self._receipts.get(task_attempt_id)

    def create_or_resolve(
        self, receipt: AgentCompletedReceipt
    ) -> tuple[AgentCompletedReceipt, bool]:
        existing = self._receipts.get(receipt.task_attempt_id)
        if existing is not None:
            return existing, False
        self._receipts[receipt.task_attempt_id] = receipt
        return receipt, True


@dataclass
class InMemoryAgentOutcomeRepository(AgentOutcomeRepositoryPort):
    _outcomes: dict[TaskAttemptId, AgentOutcome] = field(default_factory=dict)

    def get_by_attempt(self, task_attempt_id: TaskAttemptId) -> AgentOutcome | None:
        return self._outcomes.get(task_attempt_id)

    def save(self, outcome: AgentOutcome) -> None:
        if outcome.task_attempt_id in self._outcomes:
            raise ValueError(
                f"An outcome already exists for {outcome.task_attempt_id}; "
                "exactly one accepted outcome per attempt is required"
            )
        self._outcomes[outcome.task_attempt_id] = outcome
