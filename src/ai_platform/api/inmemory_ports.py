"""Non-production, in-memory reference implementations of the Phase 2/3
ports, used to make the Workflow API actually runnable before Phase 6
introduces real PostgreSQL/Kafka adapters.

Data does not survive process restart. The legacy per-repository fakes have no
cross-store transaction guarantee; the cohesive asynchronous stores at the end
of this module model atomic integrity units under a process-local lock. Neither
is a durable concrete adapter.
"""

import asyncio
import copy
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import cast

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
from ai_platform.orchestrator.domain.results import WorkflowFailure, WorkflowResult
from ai_platform.orchestrator.domain.states import WorkflowState
from ai_platform.orchestrator.domain.task import Task, TaskAttempt
from ai_platform.orchestrator.domain.workflow import Workflow
from ai_platform.ports.persistence.accepted_request import AcceptedRequestRepositoryPort
from ai_platform.ports.persistence.agent import (
    AgentOutcomeRepositoryPort,
    AgentReceiptRepositoryPort,
)
from ai_platform.ports.persistence.audit import AuditRepositoryPort
from ai_platform.ports.persistence.errors import (
    PermanentPersistenceError,
    PersistenceConflictError,
)
from ai_platform.ports.persistence.orchestrator_inbox import OrchestratorInboxRepositoryPort
from ai_platform.ports.persistence.task import TaskAttemptRepositoryPort, TaskRepositoryPort
from ai_platform.ports.persistence.transactions import (
    AcceptedRequestAccessAuditRecord,
    AcceptedRequestResolution,
    AgentOutcomeCommitIntent,
    AgentOutcomeCommitResult,
    CompletedAgentWork,
    DeadlinePersistenceDisposition,
    ExpiredAttempt,
    SubmissionCommitIntent,
    SubmissionCommitResult,
    TerminalOutcomeCommitResult,
    TerminalOutcomeIntent,
    TerminalPersistenceDisposition,
)
from ai_platform.ports.persistence.workflow import WorkflowRepositoryPort
from ai_platform.shared.identifiers import (
    MessageId,
    OwnerSubjectId,
    TaskAttemptId,
    TaskId,
    WorkflowId,
)
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
class InMemoryOrchestratorOutboxRepository:
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
class InMemoryAgentEventOutboxRepository:
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


@dataclass(frozen=True, slots=True)
class _TerminalInboxEntry:
    immutable_message_digest: str
    workflow_id: WorkflowId
    disposition: TerminalPersistenceDisposition


@dataclass
class InMemoryOrchestratorPersistence:
    """Atomic asynchronous reference store for Orchestrator integrity units.

    This remains a non-production, process-local adapter. Unlike the legacy
    per-repository fakes above, however, its one lock and cohesive state model
    preserve the transaction boundaries exposed by ``transactions.py``. It is
    therefore useful for application wiring and tests that must not normalize
    partial-write behavior which PostgreSQL would reject.
    """

    accepted_requests: dict[AcceptedRequestKey, AcceptedRequestResolution] = field(
        default_factory=dict
    )
    workflows: dict[WorkflowId, Workflow] = field(default_factory=dict)
    tasks: dict[TaskId, Task] = field(default_factory=dict)
    task_attempts: dict[TaskAttemptId, TaskAttempt] = field(default_factory=dict)
    command_outbox: dict[MessageId, OrchestratorOutboxRecord] = field(default_factory=dict)
    audit_records: list[AuditRecord] = field(default_factory=list)
    request_access_audit_records: list[AcceptedRequestAccessAuditRecord] = field(
        default_factory=list
    )
    _terminal_inbox: dict[tuple[str, str, MessageId], _TerminalInboxEntry] = field(
        default_factory=dict, repr=False
    )
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    async def resolve(self, key: AcceptedRequestKey) -> AcceptedRequestResolution | None:
        async with self._lock:
            return self.accepted_requests.get(key)

    async def get(self, workflow_id: WorkflowId) -> Workflow | None:
        async with self._lock:
            workflow = self.workflows.get(workflow_id)
            return copy.deepcopy(workflow) if workflow is not None else None

    async def get_authorized(
        self,
        workflow_id: WorkflowId,
        *,
        environment: str,
        current_owner_subject_id: OwnerSubjectId,
    ) -> Workflow | None:
        async with self._lock:
            authorized = any(
                resolution.workflow_id == workflow_id
                and key.environment == environment
                and resolution.evidence.current_owner_subject_id == current_owner_subject_id
                for key, resolution in self.accepted_requests.items()
            )
            if not authorized:
                return None
            workflow = self.workflows.get(workflow_id)
            return copy.deepcopy(workflow) if workflow is not None else None

    async def record_request_access(self, record: AcceptedRequestAccessAuditRecord) -> None:
        async with self._lock:
            resolution = self.accepted_requests.get(record.key)
            if resolution is None or resolution.workflow_id != record.workflow_id:
                raise PersistenceConflictError(
                    "Request-access audit does not resolve to the accepted request"
                )
            self.request_access_audit_records.append(copy.deepcopy(record))

    async def commit_submission(self, intent: SubmissionCommitIntent) -> SubmissionCommitResult:
        async with self._lock:
            existing = self.accepted_requests.get(intent.key)
            if existing is not None:
                workflow = self.workflows.get(existing.workflow_id)
                if workflow is None:
                    raise PermanentPersistenceError("Accepted request refers to a missing workflow")
                return SubmissionCommitResult(
                    resolution=existing,
                    workflow=copy.deepcopy(workflow),
                    created=False,
                )

            self._validate_submission(intent)
            workflow = copy.deepcopy(intent.workflow)
            resolution = AcceptedRequestResolution(
                key=intent.key,
                workflow_id=workflow.workflow_id,
                evidence=intent.evidence,
            )

            # All fallible validation and copying happens before this write set.
            self.accepted_requests[intent.key] = resolution
            self.workflows[workflow.workflow_id] = workflow
            self.tasks[intent.task.task_id] = intent.task
            self.task_attempts[intent.task_attempt.task_attempt_id] = intent.task_attempt
            self.command_outbox[intent.command_outbox.message_id] = intent.command_outbox
            self.audit_records.append(copy.deepcopy(intent.audit))
            return SubmissionCommitResult(
                resolution=resolution,
                workflow=copy.deepcopy(workflow),
                created=True,
            )

    async def apply_terminal_outcome(
        self, intent: TerminalOutcomeIntent
    ) -> TerminalOutcomeCommitResult:
        async with self._lock:
            inbox_key = (
                intent.environment,
                intent.logical_consumer_id,
                intent.validated_message_id,
            )
            existing = self._terminal_inbox.get(inbox_key)
            if existing is not None:
                if existing.immutable_message_digest != intent.immutable_message_digest:
                    return TerminalOutcomeCommitResult(
                        disposition=TerminalPersistenceDisposition.PERMANENT_CONFLICT,
                        workflow=self._workflow_copy(existing.workflow_id),
                    )
                return TerminalOutcomeCommitResult(
                    disposition=TerminalPersistenceDisposition.DUPLICATE,
                    workflow=self._workflow_copy(existing.workflow_id),
                )

            workflow = self.workflows.get(intent.workflow_id)
            if workflow is None or not self._terminal_identity_matches(intent):
                self._terminal_inbox[inbox_key] = _TerminalInboxEntry(
                    immutable_message_digest=intent.immutable_message_digest,
                    workflow_id=intent.workflow_id,
                    disposition=TerminalPersistenceDisposition.PERMANENT_CONFLICT,
                )
                self.audit_records.append(copy.deepcopy(intent.audit))
                return TerminalOutcomeCommitResult(
                    disposition=TerminalPersistenceDisposition.PERMANENT_CONFLICT,
                    workflow=copy.deepcopy(workflow) if workflow is not None else None,
                )

            if workflow.is_terminal:
                self._terminal_inbox[inbox_key] = _TerminalInboxEntry(
                    immutable_message_digest=intent.immutable_message_digest,
                    workflow_id=intent.workflow_id,
                    disposition=TerminalPersistenceDisposition.LATE_AFTER_TERMINAL,
                )
                self.audit_records.append(copy.deepcopy(intent.audit))
                return TerminalOutcomeCommitResult(
                    disposition=TerminalPersistenceDisposition.LATE_AFTER_TERMINAL,
                    workflow=copy.deepcopy(workflow),
                )

            if workflow.state is not WorkflowState.DISPATCHED:
                self._terminal_inbox[inbox_key] = _TerminalInboxEntry(
                    immutable_message_digest=intent.immutable_message_digest,
                    workflow_id=intent.workflow_id,
                    disposition=TerminalPersistenceDisposition.PERMANENT_CONFLICT,
                )
                self.audit_records.append(copy.deepcopy(intent.audit))
                return TerminalOutcomeCommitResult(
                    disposition=TerminalPersistenceDisposition.PERMANENT_CONFLICT,
                    workflow=copy.deepcopy(workflow),
                )

            transitioned = copy.deepcopy(workflow)
            if intent.outcome.word_count is not None:
                transitioned.complete(
                    WorkflowResult(word_count=intent.outcome.word_count),
                    occurred_at=intent.occurred_at,
                )
            else:
                transitioned.fail(
                    WorkflowFailure(
                        code=intent.outcome.failure_code or "TASK_EXECUTION_FAILED",
                        detail=intent.outcome.summary or "",
                    ),
                    occurred_at=intent.occurred_at,
                )

            self.workflows[intent.workflow_id] = transitioned
            self._terminal_inbox[inbox_key] = _TerminalInboxEntry(
                immutable_message_digest=intent.immutable_message_digest,
                workflow_id=intent.workflow_id,
                disposition=TerminalPersistenceDisposition.APPLIED,
            )
            self.audit_records.append(copy.deepcopy(intent.audit))
            return TerminalOutcomeCommitResult(
                disposition=TerminalPersistenceDisposition.APPLIED,
                workflow=copy.deepcopy(transitioned),
            )

    async def find_expired(self, *, now: datetime, limit: int) -> tuple[ExpiredAttempt, ...]:
        if limit < 1:
            raise ValueError("limit must be positive")
        async with self._lock:
            candidates: list[tuple[datetime, ExpiredAttempt]] = []
            for attempt in self.task_attempts.values():
                task = self.tasks.get(attempt.task_id)
                if task is None:
                    raise PermanentPersistenceError("Task attempt refers to a missing task")
                workflow = self.workflows.get(task.workflow_id)
                if (
                    workflow is not None
                    and workflow.state is WorkflowState.DISPATCHED
                    and attempt.task_result_deadline <= now
                ):
                    candidates.append(
                        (
                            attempt.task_result_deadline,
                            ExpiredAttempt(
                                workflow_id=workflow.workflow_id,
                                task_attempt_id=attempt.task_attempt_id,
                            ),
                        )
                    )
            candidates.sort(key=lambda item: (item[0], str(item[1].workflow_id)))
            return tuple(candidate for _, candidate in candidates[:limit])

    async def expire(
        self,
        candidate: ExpiredAttempt,
        *,
        now: datetime,
        audit: AuditRecord,
    ) -> DeadlinePersistenceDisposition:
        async with self._lock:
            workflow = self.workflows.get(candidate.workflow_id)
            attempt = self.task_attempts.get(candidate.task_attempt_id)
            if workflow is None or attempt is None:
                raise PersistenceConflictError("Deadline candidate no longer resolves")
            task = self.tasks.get(attempt.task_id)
            if task is None or task.workflow_id != candidate.workflow_id:
                raise PersistenceConflictError("Deadline candidate identity does not match")
            if audit.workflow_id != candidate.workflow_id:
                raise PersistenceConflictError("Deadline audit workflow does not match")
            if workflow.is_terminal:
                return DeadlinePersistenceDisposition.ALREADY_TERMINAL
            if workflow.state is not WorkflowState.DISPATCHED or attempt.task_result_deadline > now:
                return DeadlinePersistenceDisposition.NOT_DUE

            transitioned = copy.deepcopy(workflow)
            transitioned.fail(
                WorkflowFailure(
                    code="TASK_RESULT_DEADLINE_EXCEEDED",
                    detail="No terminal outcome was received before the task result deadline.",
                ),
                occurred_at=now,
                cause="deadline_expired",
            )
            self.workflows[candidate.workflow_id] = transitioned
            self.audit_records.append(copy.deepcopy(audit))
            return DeadlinePersistenceDisposition.APPLIED

    def _validate_submission(self, intent: SubmissionCommitIntent) -> None:
        workflow_id = intent.workflow.workflow_id
        if intent.workflow.request_id != intent.key.request_id:
            raise PersistenceConflictError("Workflow request identity does not match")
        if intent.workflow.state is not WorkflowState.DISPATCHED:
            raise PersistenceConflictError("Submission workflow must be DISPATCHED")
        if intent.task.workflow_id != workflow_id:
            raise PersistenceConflictError("Task workflow identity does not match")
        if intent.task_attempt.task_id != intent.task.task_id:
            raise PersistenceConflictError("Task attempt identity does not match")
        if intent.command_outbox.workflow_id != workflow_id:
            raise PersistenceConflictError("Command outbox workflow identity does not match")
        if intent.command_outbox.ordering_key != str(workflow_id):
            raise PersistenceConflictError("Command outbox ordering key does not match")
        if intent.audit.workflow_id != workflow_id:
            raise PersistenceConflictError("Submission audit workflow identity does not match")
        if workflow_id in self.workflows:
            raise PersistenceConflictError("Workflow identity already exists")
        if intent.task.task_id in self.tasks:
            raise PersistenceConflictError("Task identity already exists")
        if intent.task_attempt.task_attempt_id in self.task_attempts:
            raise PersistenceConflictError("Task attempt identity already exists")
        if intent.command_outbox.message_id in self.command_outbox:
            raise PersistenceConflictError("Command message identity already exists")

    def _terminal_identity_matches(self, intent: TerminalOutcomeIntent) -> bool:
        if not intent.immutable_message_digest:
            return False
        task = self.tasks.get(intent.task_id)
        attempt = self.task_attempts.get(intent.task_attempt_id)
        workflow = self.workflows.get(intent.workflow_id)
        if task is None or attempt is None or workflow is None:
            return False
        if task.workflow_id != intent.workflow_id or attempt.task_id != intent.task_id:
            return False
        if intent.outcome.task_attempt_id != intent.task_attempt_id:
            return False
        if workflow.correlation_id != intent.correlation_id:
            return False
        if intent.audit.workflow_id != intent.workflow_id:
            return False
        command = next(
            (
                record
                for record in self.command_outbox.values()
                if record.workflow_id == intent.workflow_id
                and record.message_id == intent.causation_message_id
            ),
            None,
        )
        if command is None:
            return False
        selection = attempt.selection
        if (
            intent.producer_component != selection.implementation_identity
            or intent.producer_instance_id != str(selection.agent_id)
            or intent.capability_name != selection.capability_name
            or intent.capability_version != selection.capability_version
        ):
            return False
        if (
            intent.agent_evidence_component is not None
            and intent.agent_evidence_component != selection.implementation_identity
        ) or (
            intent.agent_evidence_instance_id is not None
            and intent.agent_evidence_instance_id != str(selection.agent_id)
        ):
            return False
        if intent.outcome.word_count is None:
            return intent.result_text is None
        if intent.result_text is None:
            return False
        try:
            command_data: object = json.loads(command.payload_bytes)
            if not isinstance(command_data, dict):
                return False
            payload = cast(dict[str, object], command_data)["payload"]
            if not isinstance(payload, dict):
                return False
            payload_data = cast(dict[str, object], payload)
            return payload_data.get("input") == intent.result_text
        except KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError:
            return False

    def _workflow_copy(self, workflow_id: WorkflowId) -> Workflow | None:
        workflow = self.workflows.get(workflow_id)
        return copy.deepcopy(workflow) if workflow is not None else None


@dataclass
class InMemoryAgentPersistence:
    """Atomic asynchronous reference store for Agent completed work."""

    completed_work: dict[TaskAttemptId, CompletedAgentWork] = field(default_factory=dict)
    event_outbox: dict[MessageId, AgentEventOutboxRecord] = field(default_factory=dict)
    audit_records: list[AuditRecord] = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    async def get_completed(self, task_attempt_id: TaskAttemptId) -> CompletedAgentWork | None:
        async with self._lock:
            return self.completed_work.get(task_attempt_id)

    async def commit_outcome(self, intent: AgentOutcomeCommitIntent) -> AgentOutcomeCommitResult:
        work = intent.completed_work
        attempt_id = work.receipt.task_attempt_id
        async with self._lock:
            existing = self.completed_work.get(attempt_id)
            if existing is not None:
                if not self._same_logical_agent_work(existing, work):
                    raise PersistenceConflictError(
                        "A different completed Agent outcome already won this attempt"
                    )
                return AgentOutcomeCommitResult(completed_work=existing, created=False)

            self._validate_agent_outcome(intent)
            self.completed_work[attempt_id] = work
            self.event_outbox[work.event_outbox.message_id] = work.event_outbox
            self.audit_records.append(copy.deepcopy(intent.audit))
            return AgentOutcomeCommitResult(completed_work=work, created=True)

    def _validate_agent_outcome(self, intent: AgentOutcomeCommitIntent) -> None:
        work = intent.completed_work
        receipt = work.receipt
        if work.outcome.task_attempt_id != receipt.task_attempt_id:
            raise PersistenceConflictError("Agent outcome attempt identity does not match")
        if work.event_outbox.message_id != receipt.terminal_event_message_id:
            raise PersistenceConflictError("Agent event identity does not match its receipt")
        if work.event_outbox.ordering_key != str(work.event_outbox.workflow_id):
            raise PersistenceConflictError("Agent event ordering key does not match")
        if intent.audit.workflow_id != work.event_outbox.workflow_id:
            raise PersistenceConflictError("Agent outcome audit workflow does not match")
        if not receipt.command_digest:
            raise PersistenceConflictError("Agent command digest must not be empty")
        owner = next(
            (
                attempt_id
                for attempt_id, existing in self.completed_work.items()
                if existing.receipt.command_message_id == receipt.command_message_id
            ),
            None,
        )
        if owner is not None and owner != receipt.task_attempt_id:
            raise PersistenceConflictError("Command message identity already belongs to an attempt")
        if work.event_outbox.message_id in self.event_outbox:
            raise PersistenceConflictError("Agent event message identity already exists")

    @staticmethod
    def _same_logical_agent_work(
        existing: CompletedAgentWork, candidate: CompletedAgentWork
    ) -> bool:
        """Compare immutable command identity and deterministic outcome content.

        Concurrent computations legitimately create different completion
        timestamps, event message IDs, and canonical event bytes before one
        transaction wins. Those losing artifacts were never durable and must
        not prevent reuse of the winner.
        """
        existing_receipt = existing.receipt
        candidate_receipt = candidate.receipt
        existing_outcome = existing.outcome
        candidate_outcome = candidate.outcome
        existing_event = existing.event_outbox
        candidate_event = candidate.event_outbox
        return (
            existing_receipt.environment == candidate_receipt.environment
            and existing_receipt.agent_deployment_id == candidate_receipt.agent_deployment_id
            and existing_receipt.task_attempt_id == candidate_receipt.task_attempt_id
            and existing_receipt.command_message_id == candidate_receipt.command_message_id
            and existing_receipt.command_digest == candidate_receipt.command_digest
            and existing_outcome.task_attempt_id == candidate_outcome.task_attempt_id
            and existing_outcome.word_count == candidate_outcome.word_count
            and existing_outcome.failure_code == candidate_outcome.failure_code
            and existing_outcome.summary == candidate_outcome.summary
            and existing_event.workflow_id == candidate_event.workflow_id
            and existing_event.logical_channel == candidate_event.logical_channel
            and existing_event.ordering_key == candidate_event.ordering_key
            and existing_event.creation_sequence == candidate_event.creation_sequence
        )
