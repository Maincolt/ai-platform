"""End-to-end integration test: real Capability Registry + Orchestrator
application services, wired through `RegistryCandidateSelector`
(docs/sprint-3/plan.md task 8). Still no real database/Kafka adapters —
only in-memory persistence-port fakes and the real Registry/selection
logic.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from ai_platform.orchestrator.application.deadline import DeadlineReconciler
from ai_platform.orchestrator.application.registry_candidate_selector import (
    RegistryCandidateSelector,
)
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
from ai_platform.orchestrator.domain.task import Task, TaskAttempt
from ai_platform.orchestrator.domain.workflow import Workflow
from ai_platform.orchestrator.registry.availability import (
    AvailabilityClassification,
    AvailabilityObservation,
    AvailabilityPort,
)
from ai_platform.orchestrator.registry.declarations import CapabilityBinding
from ai_platform.orchestrator.registry.snapshot import load_registry_snapshot
from ai_platform.ports.persistence.accepted_request import AcceptedRequestRepositoryPort
from ai_platform.ports.persistence.audit import AuditRepositoryPort
from ai_platform.ports.persistence.orchestrator_inbox import OrchestratorInboxRepositoryPort
from ai_platform.ports.persistence.outbox import OrchestratorOutboxRepositoryPort
from ai_platform.ports.persistence.recovery import NonterminalWorkflowQueryPort
from ai_platform.ports.persistence.task import TaskAttemptRepositoryPort, TaskRepositoryPort
from ai_platform.ports.persistence.workflow import WorkflowRepositoryPort

NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
ENVIRONMENT = "local-development"


# ---------------------------------------------------------------------------
# In-memory fakes (identical pattern to test_application_services.py)
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
        raise NotImplementedError("Not exercised by this integration test")

    def mark_publication_state(
        self, message_id: MessageId, state: object, *, fencing_token: str
    ) -> None:
        raise NotImplementedError("Not exercised by this integration test")


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
    rows: list[tuple[WorkflowId, TaskAttemptId, datetime]] = field(default_factory=list)

    def find_expired_dispatched_attempts(
        self, *, now: datetime
    ) -> list[tuple[WorkflowId, TaskAttemptId]]:
        return [(w, a) for (w, a, deadline) in self.rows if deadline <= now]


@dataclass
class FixedAvailabilityPort(AvailabilityPort):
    """Always reports one Agent as READY, fresh at any `now` used in this test."""

    agent_id: AgentId

    def observe(
        self, agent_id: AgentId, capability_name: str, capability_version: str
    ) -> AvailabilityObservation:
        assert agent_id == self.agent_id
        return AvailabilityObservation(
            classification=AvailabilityClassification.READY,
            observed_at=NOW,
            ttl_seconds=3600.0,
        )


@dataclass
class FakeIdentifierFactory:
    _next: int = 0

    def new_id(self) -> str:
        self._next += 1
        return f"id-{self._next:04d}"


def _test_agent_binding() -> CapabilityBinding:
    return CapabilityBinding(
        capability_name="text.word-count",
        capability_version="1.0",
        command_contract_name="ExecuteTask",
        command_contract_versions=("1.0",),
        # Parallel to event_contract_names: TaskCompleted->1.0, TaskFailed->1.0.
        event_contract_names=("TaskCompleted", "TaskFailed"),
        event_contract_versions=("1.0", "1.0"),
        agent_id=AgentId("test-agent"),
        implementation_identity="test-agent-impl",
        implementation_version="1.0",
        deployment_declaration_digest="digest-1",
        environment=ENVIRONMENT,
        enabled=True,
    )


def _submission_request(request_id: str = "req-1") -> SubmissionRequest:
    return SubmissionRequest(
        environment=ENVIRONMENT,
        operation="workflow.submit",
        idempotency_scope_id=IdempotencyScopeId("scope-1"),
        request_id=RequestId(request_id),
        correlation_id=CorrelationId("corr-1"),
        acceptance_actor_id=ActorId("actor-1"),
        accepted_owner_subject_id=OwnerSubjectId("owner-1"),
        fingerprint="fp-a",
        fingerprint_policy_version="1.0",
        text="the quick brown fox jumps over the lazy dog",
        capability_name="text.word-count",
        capability_version="1.0",
        command_contract_name="ExecuteTask",
        command_contract_version="1.0",
        # Parallel to event_contract_names: TaskCompleted->1.0, TaskFailed->1.0.
        event_contract_names=("TaskCompleted", "TaskFailed"),
        event_contract_versions=("1.0", "1.0"),
        task_result_deadline=NOW + timedelta(seconds=30),
    )


def test_submission_selects_real_registry_candidate_and_dispatches() -> None:
    snapshot = load_registry_snapshot([_test_agent_binding()], revision="rev-1")
    selector = RegistryCandidateSelector(
        snapshot=snapshot,
        availability_port=FixedAvailabilityPort(agent_id=AgentId("test-agent")),
        selection_policy_version="1.0",
    )
    outbox_repo = InMemoryOrchestratorOutboxRepository()
    workflow_repo = InMemoryWorkflowRepository()
    orchestrator = SubmissionOrchestrator(
        accepted_request_repo=InMemoryAcceptedRequestRepository(),
        workflow_repo=workflow_repo,
        task_repo=InMemoryTaskRepository(),
        task_attempt_repo=InMemoryTaskAttemptRepository(),
        outbox_repo=outbox_repo,
        audit_repo=InMemoryAuditRepository(),
        candidate_selector=selector,
        id_factory=FakeIdentifierFactory(),
    )

    result = orchestrator.submit(_submission_request(), now=NOW)

    assert result.disposition == SubmissionDisposition.NEW
    assert result.workflow is not None
    assert result.workflow.state is not None and result.workflow.state.value == "DISPATCHED"
    assert len(outbox_repo.records) == 1
    payload = outbox_repo.records[0].payload
    assert payload["contract_name"] == "ExecuteTask"
    inner_payload = payload["payload"]
    assert isinstance(inner_payload, dict)
    assert inner_payload["capability"] == "text.word-count"


def test_submission_no_eligible_agent_when_registry_has_no_matching_binding() -> None:
    snapshot = load_registry_snapshot([], revision="rev-empty")
    selector = RegistryCandidateSelector(
        snapshot=snapshot,
        availability_port=FixedAvailabilityPort(agent_id=AgentId("test-agent")),
        selection_policy_version="1.0",
    )
    orchestrator = SubmissionOrchestrator(
        accepted_request_repo=InMemoryAcceptedRequestRepository(),
        workflow_repo=InMemoryWorkflowRepository(),
        task_repo=InMemoryTaskRepository(),
        task_attempt_repo=InMemoryTaskAttemptRepository(),
        outbox_repo=InMemoryOrchestratorOutboxRepository(),
        audit_repo=InMemoryAuditRepository(),
        candidate_selector=selector,
        id_factory=FakeIdentifierFactory(),
    )

    result = orchestrator.submit(_submission_request(), now=NOW)

    assert result.disposition == SubmissionDisposition.NO_ELIGIBLE_AGENT


def test_full_lifecycle_submit_dispatch_complete_via_real_registry() -> None:
    snapshot = load_registry_snapshot([_test_agent_binding()], revision="rev-1")
    selector = RegistryCandidateSelector(
        snapshot=snapshot,
        availability_port=FixedAvailabilityPort(agent_id=AgentId("test-agent")),
        selection_policy_version="1.0",
    )
    workflow_repo = InMemoryWorkflowRepository()
    audit_repo = InMemoryAuditRepository()
    orchestrator = SubmissionOrchestrator(
        accepted_request_repo=InMemoryAcceptedRequestRepository(),
        workflow_repo=workflow_repo,
        task_repo=InMemoryTaskRepository(),
        task_attempt_repo=InMemoryTaskAttemptRepository(),
        outbox_repo=InMemoryOrchestratorOutboxRepository(),
        audit_repo=audit_repo,
        candidate_selector=selector,
        id_factory=FakeIdentifierFactory(),
    )
    inbox_repo = InMemoryOrchestratorInboxRepository()
    terminal_processor = TerminalEventProcessor(
        workflow_repo=workflow_repo, inbox_repo=inbox_repo, audit_repo=audit_repo
    )

    submission = orchestrator.submit(_submission_request(), now=NOW)
    assert submission.workflow_id is not None

    terminal = terminal_processor.process(
        environment=ENVIRONMENT,
        logical_consumer_id="orchestrator-outcome-consumer",
        validated_message_id=MessageId("msg-final"),
        workflow_id=submission.workflow_id,
        outcome=AgentOutcome(
            task_attempt_id=TaskAttemptId("attempt-1"), completed_at=NOW, word_count=9
        ),
        occurred_at=NOW + timedelta(seconds=1),
    )

    assert terminal.disposition == TerminalDisposition.APPLIED
    final = workflow_repo.get_by_id(submission.workflow_id)
    assert final is not None
    assert final.state is not None and final.state.value == "COMPLETED"
    assert final.result is not None and final.result.word_count == 9


def test_deadline_reconciler_does_not_override_real_completed_workflow() -> None:
    """Proves the Sprint 2 aggregate's terminal-exclusivity guarantee holds
    end-to-end: a real submission + real completion, then a deadline
    reconciler pass that must be a safe no-op."""
    snapshot = load_registry_snapshot([_test_agent_binding()], revision="rev-1")
    selector = RegistryCandidateSelector(
        snapshot=snapshot,
        availability_port=FixedAvailabilityPort(agent_id=AgentId("test-agent")),
        selection_policy_version="1.0",
    )
    workflow_repo = InMemoryWorkflowRepository()
    audit_repo = InMemoryAuditRepository()
    orchestrator = SubmissionOrchestrator(
        accepted_request_repo=InMemoryAcceptedRequestRepository(),
        workflow_repo=workflow_repo,
        task_repo=InMemoryTaskRepository(),
        task_attempt_repo=InMemoryTaskAttemptRepository(),
        outbox_repo=InMemoryOrchestratorOutboxRepository(),
        audit_repo=audit_repo,
        candidate_selector=selector,
        id_factory=FakeIdentifierFactory(),
    )
    inbox_repo = InMemoryOrchestratorInboxRepository()
    terminal_processor = TerminalEventProcessor(
        workflow_repo=workflow_repo, inbox_repo=inbox_repo, audit_repo=audit_repo
    )

    submission = orchestrator.submit(_submission_request(), now=NOW)
    assert submission.workflow_id is not None
    terminal_processor.process(
        environment=ENVIRONMENT,
        logical_consumer_id="orchestrator-outcome-consumer",
        validated_message_id=MessageId("msg-final"),
        workflow_id=submission.workflow_id,
        outcome=AgentOutcome(
            task_attempt_id=TaskAttemptId("attempt-1"), completed_at=NOW, word_count=9
        ),
        occurred_at=NOW + timedelta(seconds=1),
    )

    recovery_query = InMemoryNonterminalWorkflowQueryPort(
        rows=[(submission.workflow_id, TaskAttemptId("attempt-1"), NOW + timedelta(seconds=30))]
    )
    reconciler = DeadlineReconciler(
        recovery_query=recovery_query, workflow_repo=workflow_repo, audit_repo=audit_repo
    )

    reconciled = reconciler.reconcile(now=NOW + timedelta(seconds=60))

    assert reconciled == []  # already-terminal workflow is safely skipped
    final = workflow_repo.get_by_id(submission.workflow_id)
    assert final is not None
    assert final.state is not None and final.state.value == "COMPLETED"
