"""Component tests: in-memory fakes proving the Orchestrator application
services (submission, terminal processing, deadline reconciliation) behave
correctly against the Phase 2 ports and the Sprint 2 Workflow aggregate.

The `CandidateSelectorPort` fake stands in for the Capability Registry
(built independently this sprint); see docs/sprint-3/plan.md task 8 for the
real integration.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from ai_platform.orchestrator.application.candidate_selection import (
    CandidateSelectionConfigurationError,
    CandidateSelectorPort,
    NoEligibleCandidateError,
)
from ai_platform.orchestrator.application.deadline import DeadlineReconciler
from ai_platform.orchestrator.application.ids import IdentifierFactory
from ai_platform.orchestrator.application.submission import (
    SubmissionDisposition,
    SubmissionOrchestrator,
    SubmissionRequest,
)
from ai_platform.orchestrator.application.terminal import (
    TerminalDisposition,
    TerminalEventProcessor,
)
from ai_platform.orchestrator.domain.accepted_request import (
    AcceptanceEvidence,
    AcceptedRequestKey,
)
from ai_platform.orchestrator.domain.audit import AuditRecord
from ai_platform.orchestrator.domain.identifiers import (
    ActorId,
    AgentId,
    CorrelationId,
    IdempotencyScopeId,
    MessageId,
    OwnerSubjectId,
    RequestId,
    TaskAttemptId,
    TaskId,
    WorkflowId,
)
from ai_platform.orchestrator.domain.recovery import (
    AgentOutcome,
    OrchestratorInboxRecord,
    OrchestratorOutboxRecord,
)
from ai_platform.orchestrator.domain.results import WorkflowResult
from ai_platform.orchestrator.domain.selection import SelectionIntent
from ai_platform.orchestrator.domain.task import Task, TaskAttempt
from ai_platform.orchestrator.domain.workflow import Workflow
from ai_platform.ports.persistence.accepted_request import AcceptedRequestRepositoryPort
from ai_platform.ports.persistence.audit import AuditRepositoryPort
from ai_platform.ports.persistence.orchestrator_inbox import OrchestratorInboxRepositoryPort
from ai_platform.ports.persistence.outbox import OrchestratorOutboxRepositoryPort
from ai_platform.ports.persistence.recovery import NonterminalWorkflowQueryPort
from ai_platform.ports.persistence.task import TaskAttemptRepositoryPort, TaskRepositoryPort
from ai_platform.ports.persistence.workflow import WorkflowRepositoryPort

NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)

# ---------------------------------------------------------------------------
# In-memory fakes (test-owned, not adapters)
# ---------------------------------------------------------------------------


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
        raise NotImplementedError("Not exercised by application-service tests")

    def mark_publication_state(
        self, message_id: MessageId, state: object, *, fencing_token: str
    ) -> None:
        raise NotImplementedError("Not exercised by application-service tests")


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
class InMemoryNonterminalWorkflowQueryPort(NonterminalWorkflowQueryPort):
    """Test-owned: holds explicit (workflow_id, task_attempt_id, deadline)
    rows rather than deriving them from a real attempt store."""

    rows: list[tuple[WorkflowId, TaskAttemptId, datetime]] = field(default_factory=list)

    def find_expired_dispatched_attempts(
        self, *, now: datetime
    ) -> list[tuple[WorkflowId, TaskAttemptId]]:
        return [(w, a) for (w, a, deadline) in self.rows if deadline <= now]


@dataclass
class FakeIdentifierFactory(IdentifierFactory):
    _next: int = 0

    def new_id(self) -> str:
        self._next += 1
        return f"id-{self._next:04d}"


@dataclass
class FakeCandidateSelector(CandidateSelectorPort):
    """Stands in for the Capability Registry (built independently this
    sprint; see docs/sprint-3/plan.md task 8)."""

    fixed_selection: SelectionIntent | None = None
    raise_no_eligible: bool = False
    raise_configuration_error: bool = False
    call_count: int = 0

    def select(
        self,
        *,
        capability_name: str,
        capability_version: str,
        command_contract_name: str,
        command_contract_version: str,
        event_contract_names: tuple[str, ...],
        event_contract_versions: tuple[str, ...],
        environment: str,
        now: datetime,
    ) -> SelectionIntent:
        self.call_count += 1
        if self.raise_no_eligible:
            raise NoEligibleCandidateError("no eligible candidate")
        if self.raise_configuration_error:
            raise CandidateSelectionConfigurationError("ambiguous candidate")
        assert self.fixed_selection is not None
        return self.fixed_selection


def _selection_intent() -> SelectionIntent:
    return SelectionIntent(
        agent_id=AgentId("test-agent"),
        capability_name="text.word-count",
        capability_version="1.0",
        implementation_identity="test-agent-impl",
        implementation_version="1.0",
        command_contract_version="1.0",
        event_contract_versions=("1.0",),
        registry_revision="rev-1",
        deployment_declaration_digest="digest-1",
        selection_policy_version="1.0",
        availability_classification="READY",
        observed_at=NOW,
        selected_at=NOW,
    )


def _submission_request(request_id: str = "req-1", fingerprint: str = "fp-a") -> SubmissionRequest:
    return SubmissionRequest(
        environment="local-development",
        operation="workflow.submit",
        idempotency_scope_id=IdempotencyScopeId("scope-1"),
        request_id=RequestId(request_id),
        correlation_id=CorrelationId("corr-1"),
        acceptance_actor_id=ActorId("actor-1"),
        accepted_owner_subject_id=OwnerSubjectId("owner-1"),
        fingerprint=fingerprint,
        fingerprint_policy_version="1.0",
        text="the quick brown fox jumps over the lazy dog",
        capability_name="text.word-count",
        capability_version="1.0",
        command_contract_name="ExecuteTask",
        command_contract_version="1.0",
        event_contract_names=("TaskCompleted", "TaskFailed"),
        event_contract_versions=("1.0", "1.0"),
        task_result_deadline=NOW + timedelta(seconds=30),
    )


def _build_submission_orchestrator(
    *,
    accepted_request_repo: InMemoryAcceptedRequestRepository | None = None,
    workflow_repo: InMemoryWorkflowRepository | None = None,
    outbox_repo: InMemoryOrchestratorOutboxRepository | None = None,
    audit_repo: InMemoryAuditRepository | None = None,
    candidate_selector: FakeCandidateSelector | None = None,
) -> tuple[
    SubmissionOrchestrator,
    InMemoryAcceptedRequestRepository,
    InMemoryWorkflowRepository,
    InMemoryOrchestratorOutboxRepository,
    InMemoryAuditRepository,
    FakeCandidateSelector,
]:
    accepted_request_repo = accepted_request_repo or InMemoryAcceptedRequestRepository()
    workflow_repo = workflow_repo or InMemoryWorkflowRepository()
    outbox_repo = outbox_repo or InMemoryOrchestratorOutboxRepository()
    audit_repo = audit_repo or InMemoryAuditRepository()
    candidate_selector = candidate_selector or FakeCandidateSelector(
        fixed_selection=_selection_intent()
    )

    orchestrator = SubmissionOrchestrator(
        accepted_request_repo=accepted_request_repo,
        workflow_repo=workflow_repo,
        task_repo=InMemoryTaskRepository(),
        task_attempt_repo=InMemoryTaskAttemptRepository(),
        outbox_repo=outbox_repo,
        audit_repo=audit_repo,
        candidate_selector=candidate_selector,
        id_factory=FakeIdentifierFactory(),
    )
    return (
        orchestrator,
        accepted_request_repo,
        workflow_repo,
        outbox_repo,
        audit_repo,
        candidate_selector,
    )


# ---------------------------------------------------------------------------
# SubmissionOrchestrator
# ---------------------------------------------------------------------------


def test_submission_new_request_creates_workflow_and_enqueues_outbox() -> None:
    orchestrator, _, workflow_repo, outbox_repo, audit_repo, _ = _build_submission_orchestrator()

    result = orchestrator.submit(_submission_request(), now=NOW)

    assert result.disposition == SubmissionDisposition.NEW
    assert result.workflow_id is not None
    assert result.workflow is not None
    assert result.workflow.state is not None
    assert result.workflow.state.value == "DISPATCHED"
    assert workflow_repo.get_by_id(result.workflow_id) is not None
    assert len(outbox_repo.records) == 1
    assert outbox_repo.records[0].workflow_id == result.workflow_id
    assert len(audit_repo.records) == 1


def test_submission_equivalent_replay_never_checks_candidate_selector() -> None:
    orchestrator, _, _, outbox_repo, _, selector = _build_submission_orchestrator()
    request = _submission_request()

    first = orchestrator.submit(request, now=NOW)
    second = orchestrator.submit(request, now=NOW + timedelta(seconds=1))

    assert first.disposition == SubmissionDisposition.NEW
    assert second.disposition == SubmissionDisposition.EQUIVALENT_REPLAY
    assert second.workflow_id == first.workflow_id
    # The selector is invoked exactly once: only for the first (new) request.
    assert selector.call_count == 1
    assert len(outbox_repo.records) == 1


def test_submission_fingerprint_conflict_creates_no_new_workflow() -> None:
    orchestrator, _, _, outbox_repo, _, _ = _build_submission_orchestrator()
    first_request = _submission_request(fingerprint="fp-a")
    conflicting_request = _submission_request(fingerprint="fp-b")

    first = orchestrator.submit(first_request, now=NOW)
    second = orchestrator.submit(conflicting_request, now=NOW)

    assert second.disposition == SubmissionDisposition.FINGERPRINT_CONFLICT
    assert second.workflow_id == first.workflow_id
    assert second.workflow is None
    assert len(outbox_repo.records) == 1  # no second command was ever enqueued


def test_submission_no_eligible_agent_creates_nothing() -> None:
    orchestrator, _, _, outbox_repo, audit_repo, _ = _build_submission_orchestrator(
        candidate_selector=FakeCandidateSelector(raise_no_eligible=True)
    )

    result = orchestrator.submit(_submission_request(), now=NOW)

    assert result.disposition == SubmissionDisposition.NO_ELIGIBLE_AGENT
    assert result.workflow_id is None
    assert outbox_repo.records == []
    assert audit_repo.records == []


def test_submission_configuration_error_creates_nothing() -> None:
    orchestrator, _, _, outbox_repo, _, _ = _build_submission_orchestrator(
        candidate_selector=FakeCandidateSelector(raise_configuration_error=True)
    )

    result = orchestrator.submit(_submission_request(), now=NOW)

    assert result.disposition == SubmissionDisposition.CONFIGURATION_ERROR
    assert outbox_repo.records == []


# ---------------------------------------------------------------------------
# TerminalEventProcessor
# ---------------------------------------------------------------------------


def _dispatched_workflow() -> Workflow:
    workflow = Workflow(
        workflow_id=WorkflowId("wf-1"),
        request_id=RequestId("req-1"),
        correlation_id=CorrelationId("corr-1"),
    )
    workflow.receive(occurred_at=NOW)
    workflow.prepare(occurred_at=NOW)
    workflow.dispatch(occurred_at=NOW)
    return workflow


def test_terminal_processor_first_completion_applies_transition() -> None:
    workflow_repo = InMemoryWorkflowRepository()
    workflow = _dispatched_workflow()
    workflow_repo.save_new(workflow)
    inbox_repo = InMemoryOrchestratorInboxRepository()
    audit_repo = InMemoryAuditRepository()
    processor = TerminalEventProcessor(
        workflow_repo=workflow_repo, inbox_repo=inbox_repo, audit_repo=audit_repo
    )

    result = processor.process(
        environment="local-development",
        logical_consumer_id="orchestrator-outcome-consumer",
        validated_message_id=MessageId("msg-1"),
        workflow_id=workflow.workflow_id,
        outcome=AgentOutcome(
            task_attempt_id=TaskAttemptId("attempt-1"), completed_at=NOW, word_count=9
        ),
        occurred_at=NOW,
    )

    assert result.disposition == TerminalDisposition.APPLIED
    assert result.workflow is not None
    assert result.workflow.state is not None and result.workflow.state.value == "COMPLETED"
    assert len(audit_repo.records) == 1


def test_terminal_processor_duplicate_message_does_not_reapply() -> None:
    workflow_repo = InMemoryWorkflowRepository()
    workflow = _dispatched_workflow()
    workflow_repo.save_new(workflow)
    inbox_repo = InMemoryOrchestratorInboxRepository()
    audit_repo = InMemoryAuditRepository()
    processor = TerminalEventProcessor(
        workflow_repo=workflow_repo, inbox_repo=inbox_repo, audit_repo=audit_repo
    )
    message_id = MessageId("msg-1")
    outcome = AgentOutcome(
        task_attempt_id=TaskAttemptId("attempt-1"), completed_at=NOW, word_count=9
    )

    first = processor.process(
        environment="local-development",
        logical_consumer_id="orchestrator-outcome-consumer",
        validated_message_id=message_id,
        workflow_id=workflow.workflow_id,
        outcome=outcome,
        occurred_at=NOW,
    )
    second = processor.process(
        environment="local-development",
        logical_consumer_id="orchestrator-outcome-consumer",
        validated_message_id=message_id,
        workflow_id=workflow.workflow_id,
        outcome=outcome,
        occurred_at=NOW + timedelta(seconds=1),
    )

    assert first.disposition == TerminalDisposition.APPLIED
    assert second.disposition == TerminalDisposition.DUPLICATE
    assert len(audit_repo.records) == 1  # not appended a second time


def test_terminal_processor_late_event_after_terminal_does_not_mutate() -> None:
    workflow_repo = InMemoryWorkflowRepository()
    workflow = _dispatched_workflow()
    workflow.complete(WorkflowResult(word_count=9), occurred_at=NOW)
    workflow_repo.save_new(workflow)
    inbox_repo = InMemoryOrchestratorInboxRepository()
    audit_repo = InMemoryAuditRepository()
    processor = TerminalEventProcessor(
        workflow_repo=workflow_repo, inbox_repo=inbox_repo, audit_repo=audit_repo
    )

    # A late TaskFailed arrives after the workflow is already COMPLETED.
    late_result = processor.process(
        environment="local-development",
        logical_consumer_id="orchestrator-outcome-consumer",
        validated_message_id=MessageId("msg-late"),
        workflow_id=workflow.workflow_id,
        outcome=AgentOutcome(
            task_attempt_id=TaskAttemptId("attempt-1"),
            completed_at=NOW,
            failure_code="TASK_EXECUTION_FAILED",
            summary="too late",
        ),
        occurred_at=NOW + timedelta(seconds=5),
    )

    assert late_result.disposition == TerminalDisposition.LATE_AFTER_TERMINAL
    stored = workflow_repo.get_by_id(workflow.workflow_id)
    assert stored is not None
    assert stored.state is not None and stored.state.value == "COMPLETED"
    assert audit_repo.records == []  # no business mutation audit for a rejected late event


# ---------------------------------------------------------------------------
# DeadlineReconciler
# ---------------------------------------------------------------------------


def test_deadline_reconciler_fails_expired_dispatched_workflow() -> None:
    workflow_repo = InMemoryWorkflowRepository()
    workflow = _dispatched_workflow()
    workflow_repo.save_new(workflow)
    recovery_query = InMemoryNonterminalWorkflowQueryPort(
        rows=[(workflow.workflow_id, TaskAttemptId("attempt-1"), NOW)]
    )
    audit_repo = InMemoryAuditRepository()
    reconciler = DeadlineReconciler(
        recovery_query=recovery_query, workflow_repo=workflow_repo, audit_repo=audit_repo
    )

    reconciled = reconciler.reconcile(now=NOW + timedelta(seconds=1))

    assert reconciled == [workflow.workflow_id]
    stored = workflow_repo.get_by_id(workflow.workflow_id)
    assert stored is not None
    assert stored.state is not None and stored.state.value == "FAILED"
    assert stored.history[-1].cause == "deadline_expired"
    assert len(audit_repo.records) == 1


def test_deadline_reconciler_skips_workflow_already_completed_by_real_outcome() -> None:
    workflow_repo = InMemoryWorkflowRepository()
    workflow = _dispatched_workflow()
    workflow.complete(WorkflowResult(word_count=9), occurred_at=NOW)
    workflow_repo.save_new(workflow)
    recovery_query = InMemoryNonterminalWorkflowQueryPort(
        rows=[(workflow.workflow_id, TaskAttemptId("attempt-1"), NOW)]
    )
    audit_repo = InMemoryAuditRepository()
    reconciler = DeadlineReconciler(
        recovery_query=recovery_query, workflow_repo=workflow_repo, audit_repo=audit_repo
    )

    reconciled = reconciler.reconcile(now=NOW + timedelta(seconds=1))

    assert reconciled == []
    stored = workflow_repo.get_by_id(workflow.workflow_id)
    assert stored is not None
    assert stored.state is not None and stored.state.value == "COMPLETED"
    assert audit_repo.records == []


# ---------------------------------------------------------------------------
# End-to-end (submission -> terminal completion) using shared fakes
# ---------------------------------------------------------------------------


def test_submission_then_terminal_completion_end_to_end() -> None:
    accepted_request_repo = InMemoryAcceptedRequestRepository()
    workflow_repo = InMemoryWorkflowRepository()
    outbox_repo = InMemoryOrchestratorOutboxRepository()
    audit_repo = InMemoryAuditRepository()
    orchestrator, *_ = _build_submission_orchestrator(
        accepted_request_repo=accepted_request_repo,
        workflow_repo=workflow_repo,
        outbox_repo=outbox_repo,
        audit_repo=audit_repo,
    )
    inbox_repo = InMemoryOrchestratorInboxRepository()
    terminal_processor = TerminalEventProcessor(
        workflow_repo=workflow_repo, inbox_repo=inbox_repo, audit_repo=audit_repo
    )

    submission_result = orchestrator.submit(_submission_request(), now=NOW)
    assert submission_result.disposition == SubmissionDisposition.NEW
    assert submission_result.workflow_id is not None

    terminal_result = terminal_processor.process(
        environment="local-development",
        logical_consumer_id="orchestrator-outcome-consumer",
        validated_message_id=MessageId("msg-final"),
        workflow_id=submission_result.workflow_id,
        outcome=AgentOutcome(
            task_attempt_id=TaskAttemptId("attempt-1"), completed_at=NOW, word_count=9
        ),
        occurred_at=NOW + timedelta(seconds=1),
    )

    assert terminal_result.disposition == TerminalDisposition.APPLIED
    final_workflow = workflow_repo.get_by_id(submission_result.workflow_id)
    assert final_workflow is not None
    assert final_workflow.state is not None and final_workflow.state.value == "COMPLETED"
    assert final_workflow.result is not None and final_workflow.result.word_count == 9
    # Both the acceptance audit and the completion audit were recorded.
    assert len(audit_repo.records) == 2
