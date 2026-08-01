"""Component tests: in-memory fakes proving each persistence port `Protocol`
is implementable and behaviorally correct for its documented capability.

These fakes are test-owned, not adapters. No real database/Kafka is
involved (see docs/sprint-2/consilium.md, Remy's note).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

from ai_platform.agents.domain.outcomes import AgentCompletedReceipt, AgentEventOutboxRecord
from ai_platform.orchestrator.domain.accepted_request import (
    AcceptanceEvidence,
    AcceptedRequestKey,
)
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
from ai_platform.ports.persistence.orchestrator_inbox import OrchestratorInboxRepositoryPort
from ai_platform.ports.persistence.outbox import (
    AgentEventOutboxRepositoryPort,
    OrchestratorOutboxRepositoryPort,
)
from ai_platform.ports.persistence.task import TaskAttemptRepositoryPort, TaskRepositoryPort
from ai_platform.ports.persistence.workflow import WorkflowRepositoryPort
from ai_platform.shared.identifiers import (
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
from ai_platform.shared.outcomes import AgentOutcome
from ai_platform.shared.recovery import PublicationState

NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# AcceptedRequestRepositoryPort fake
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


def _key(request_id: str = "019fbdd6-ab3d-77aa-8e61-4c3903e582ad") -> AcceptedRequestKey:
    return AcceptedRequestKey(
        environment="local-development",
        operation="workflow.submit",
        idempotency_scope_id=IdempotencyScopeId("scope-1"),
        request_id=RequestId(request_id),
    )


def _evidence(fingerprint: str = "aaa") -> AcceptanceEvidence:
    return AcceptanceEvidence(
        acceptance_actor_id=ActorId("actor-1"),
        accepted_owner_subject_id=OwnerSubjectId("owner-1"),
        fingerprint=fingerprint,
        fingerprint_policy_version="1.0",
        accepted_at=NOW,
    )


def test_accepted_request_repository_first_acceptance_is_new() -> None:
    repo = InMemoryAcceptedRequestRepository()
    workflow_id = WorkflowId("019fbdd6-ab3d-77aa-8e61-4c3bc6d53f69")

    resolved_id, resolved_evidence, is_new = repo.create_or_resolve(
        _key(), _evidence(), workflow_id
    )

    assert is_new is True
    assert resolved_id == workflow_id
    assert resolved_evidence.fingerprint == "aaa"


def test_accepted_request_repository_concurrent_duplicate_resolves_one_winner() -> None:
    repo = InMemoryAcceptedRequestRepository()
    key = _key()
    first_workflow_id = WorkflowId("019fbdd6-ab3d-77aa-8e61-4c3bc6d53f69")
    second_workflow_id = WorkflowId("019fbdd6-ab3d-77aa-8e61-4c41f9f4f1a1")

    repo.create_or_resolve(key, _evidence(), first_workflow_id)
    resolved_id, _, is_new = repo.create_or_resolve(key, _evidence(), second_workflow_id)

    # The loser resolves to the first (winning) workflow_id; no second workflow.
    assert is_new is False
    assert resolved_id == first_workflow_id


def test_accepted_request_repository_same_request_id_different_scope_is_independent() -> None:
    repo = InMemoryAcceptedRequestRepository()
    key_a = _key()
    key_b = AcceptedRequestKey(
        environment=key_a.environment,
        operation=key_a.operation,
        idempotency_scope_id=IdempotencyScopeId("scope-2"),
        request_id=key_a.request_id,
    )
    workflow_a = WorkflowId("019fbdd6-ab3d-77aa-8e61-4c3bc6d53f69")
    workflow_b = WorkflowId("019fbdd6-ab3d-77aa-8e61-4c41f9f4f1a1")

    repo.create_or_resolve(key_a, _evidence(), workflow_a)
    resolved_id, _, is_new = repo.create_or_resolve(key_b, _evidence(), workflow_b)

    assert is_new is True
    assert resolved_id == workflow_b


# ---------------------------------------------------------------------------
# AgentReceiptRepositoryPort / AgentOutcomeRepositoryPort fakes
# ---------------------------------------------------------------------------


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


def test_agent_receipt_repository_same_attempt_message_and_bytes_returns_stored() -> None:
    repo = InMemoryAgentReceiptRepository()
    attempt_id = TaskAttemptId("019fbdd6-ab3d-77aa-8e61-4c425fab5f4b")
    receipt = AgentCompletedReceipt(
        environment="local-development",
        agent_deployment_id=AgentId("test-agent"),
        task_attempt_id=attempt_id,
        command_message_id=MessageId("019fbdd6-ab3d-77aa-8e61-4c40d234a3bf"),
        command_digest="digest-1",
    )

    first, first_is_new = repo.create_or_resolve(receipt)
    second, second_is_new = repo.create_or_resolve(receipt)

    assert first == second == receipt
    assert first_is_new is True
    assert second_is_new is False


def test_agent_outcome_repository_enforces_exactly_one_outcome_per_attempt() -> None:
    repo = InMemoryAgentOutcomeRepository()
    attempt_id = TaskAttemptId("019fbdd6-ab3d-77aa-8e61-4c425fab5f4b")
    outcome = AgentOutcome(task_attempt_id=attempt_id, completed_at=NOW, word_count=9)

    repo.save(outcome)

    with pytest.raises(ValueError, match="exactly one accepted outcome"):
        repo.save(AgentOutcome(task_attempt_id=attempt_id, completed_at=NOW, word_count=1))

    assert repo.get_by_attempt(attempt_id) == outcome


# ---------------------------------------------------------------------------
# OrchestratorInboxRepositoryPort fake
# ---------------------------------------------------------------------------


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


def test_orchestrator_inbox_redelivery_after_commit_returns_same_disposition() -> None:
    repo = InMemoryOrchestratorInboxRepository()
    message_id = MessageId("019fbdd7-1000-7000-8000-000000000001")
    record = OrchestratorInboxRecord(
        environment="local-development",
        logical_consumer_id="orchestrator-outcome-consumer",
        validated_message_id=message_id,
        disposition="completed",
        recorded_at=NOW,
    )

    repo.record_disposition(record)
    # Redelivery of the identical message_id must not change the disposition.
    repo.record_disposition(
        OrchestratorInboxRecord(
            environment="local-development",
            logical_consumer_id="orchestrator-outcome-consumer",
            validated_message_id=message_id,
            disposition="THIS_MUST_NOT_WIN",
            recorded_at=NOW,
        )
    )

    resolved = repo.get_disposition(
        "local-development", "orchestrator-outcome-consumer", message_id
    )
    assert resolved is not None
    assert resolved.disposition == "completed"


# ---------------------------------------------------------------------------
# WorkflowRepositoryPort fake
# ---------------------------------------------------------------------------


@dataclass
class InMemoryWorkflowRepository(WorkflowRepositoryPort):
    """Stores an immutable snapshot copy per revision, so mutating the
    caller's live `Workflow` object does not silently change what is
    "durably stored" -- matching how a real compare-and-set adapter behaves.
    """

    _snapshots: dict[WorkflowId, Workflow] = field(default_factory=dict)
    _stored_revisions: dict[WorkflowId, int] = field(default_factory=dict)

    def get_by_id(self, workflow_id: WorkflowId) -> Workflow | None:
        return self._snapshots.get(workflow_id)

    def save_new(self, workflow: Workflow) -> None:
        if workflow.workflow_id in self._snapshots:
            raise ValueError(f"Workflow {workflow.workflow_id} already exists")
        self._snapshots[workflow.workflow_id] = copy.deepcopy(workflow)
        self._stored_revisions[workflow.workflow_id] = workflow.revision

    def save_transition(self, workflow: Workflow, *, expected_revision: int) -> None:
        stored_revision = self._stored_revisions.get(workflow.workflow_id)
        if stored_revision is None:
            raise ValueError(f"Workflow {workflow.workflow_id} does not exist")
        if stored_revision != expected_revision:
            raise ValueError(
                f"Revision conflict: expected {expected_revision}, stored is {stored_revision}"
            )
        self._snapshots[workflow.workflow_id] = copy.deepcopy(workflow)
        self._stored_revisions[workflow.workflow_id] = workflow.revision


def _new_workflow(workflow_id: str = "019fbdd6-ab3d-77aa-8e61-4c3bc6d53f69") -> Workflow:
    return Workflow(
        workflow_id=WorkflowId(workflow_id),
        request_id=RequestId("019fbdd6-ab3d-77aa-8e61-4c3903e582ad"),
        correlation_id=CorrelationId("019fbdd6-ab3d-77aa-8e61-4c3a4e21ad64"),
    )


def test_workflow_repository_save_new_then_get_by_id() -> None:
    repo = InMemoryWorkflowRepository()
    workflow = _new_workflow()
    workflow.receive(occurred_at=NOW)

    repo.save_new(workflow)

    retrieved = repo.get_by_id(workflow.workflow_id)
    assert retrieved is not None
    assert retrieved.workflow_id == workflow.workflow_id
    assert retrieved.state == workflow.state
    assert repo.get_by_id(WorkflowId("does-not-exist")) is None


def test_workflow_repository_save_transition_rejects_stale_revision() -> None:
    repo = InMemoryWorkflowRepository()
    original = _new_workflow()
    original.receive(occurred_at=NOW)
    repo.save_new(original)  # stored_revision == 1

    # A concurrent writer loads a copy at revision 1, transitions it, and
    # commits first -- stored_revision advances to 2.
    concurrent_writer_copy = copy.deepcopy(original)
    concurrent_writer_copy.prepare(occurred_at=NOW)
    repo.save_transition(concurrent_writer_copy, expected_revision=1)

    # Our stale caller still believes the stored revision is 1 and tries to
    # commit its own (different) transition against that stale assumption.
    stale_caller_copy = copy.deepcopy(original)
    stale_caller_copy.prepare(occurred_at=NOW)
    with pytest.raises(ValueError, match="Revision conflict"):
        repo.save_transition(stale_caller_copy, expected_revision=1)

    # The winning writer's state is what is actually stored.
    retrieved = repo.get_by_id(original.workflow_id)
    assert retrieved is not None
    assert retrieved.revision == 2


# ---------------------------------------------------------------------------
# TaskRepositoryPort / TaskAttemptRepositoryPort fakes
# ---------------------------------------------------------------------------


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


def test_task_and_task_attempt_repositories_round_trip() -> None:
    from ai_platform.orchestrator.domain.selection import SelectionIntent

    task_repo = InMemoryTaskRepository()
    attempt_repo = InMemoryTaskAttemptRepository()

    task = Task(
        task_id=TaskId("019fbdd6-ab3d-77aa-8e61-4c41f9f4f1a1"),
        workflow_id=WorkflowId("019fbdd6-ab3d-77aa-8e61-4c3bc6d53f69"),
        created_at=NOW,
    )
    task_repo.save(task)

    attempt = TaskAttempt(
        task_attempt_id=TaskAttemptId("019fbdd6-ab3d-77aa-8e61-4c425fab5f4b"),
        task_id=task.task_id,
        attempt_number=1,
        selection=SelectionIntent(
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
            availability_classification="ready",
            observed_at=NOW,
            selected_at=NOW,
        ),
        task_result_deadline=NOW,
    )
    attempt_repo.save(attempt)

    assert task_repo.get_by_id(task.task_id) == task
    assert attempt_repo.get_by_id(attempt.task_attempt_id) == attempt


# ---------------------------------------------------------------------------
# Outbox port fakes
# ---------------------------------------------------------------------------


@dataclass
class InMemoryOrchestratorOutboxRepository(OrchestratorOutboxRepositoryPort):
    _records: dict[MessageId, OrchestratorOutboxRecord] = field(default_factory=dict)
    _states: dict[MessageId, PublicationState] = field(default_factory=dict)
    _claims: dict[MessageId, str] = field(default_factory=dict)

    def enqueue(self, record: OrchestratorOutboxRecord) -> None:
        self._records[record.message_id] = record
        self._states[record.message_id] = PublicationState.NOT_ATTEMPTED

    def claim_next(
        self, workflow_id: WorkflowId, *, fencing_token: str
    ) -> OrchestratorOutboxRecord | None:
        for message_id, record in self._records.items():
            if (
                record.workflow_id == workflow_id
                and self._states[message_id] == PublicationState.NOT_ATTEMPTED
            ):
                self._states[message_id] = PublicationState.CLAIMED
                self._claims[message_id] = fencing_token
                return record
        return None

    def mark_publication_state(
        self, message_id: MessageId, state: PublicationState, *, fencing_token: str
    ) -> None:
        if self._claims.get(message_id) != fencing_token:
            raise ValueError(f"Stale fencing token for {message_id}")
        self._states[message_id] = state


@dataclass
class InMemoryAgentEventOutboxRepository(AgentEventOutboxRepositoryPort):
    _records: dict[MessageId, AgentEventOutboxRecord] = field(default_factory=dict)
    _states: dict[MessageId, PublicationState] = field(default_factory=dict)
    _claims: dict[MessageId, str] = field(default_factory=dict)

    def enqueue(self, record: AgentEventOutboxRecord) -> None:
        self._records[record.message_id] = record
        self._states[record.message_id] = PublicationState.NOT_ATTEMPTED

    def claim_next(
        self, workflow_id: WorkflowId, *, fencing_token: str
    ) -> AgentEventOutboxRecord | None:
        for message_id, record in self._records.items():
            if (
                record.workflow_id == workflow_id
                and self._states[message_id] == PublicationState.NOT_ATTEMPTED
            ):
                self._states[message_id] = PublicationState.CLAIMED
                self._claims[message_id] = fencing_token
                return record
        return None

    def mark_publication_state(
        self, message_id: MessageId, state: PublicationState, *, fencing_token: str
    ) -> None:
        if self._claims.get(message_id) != fencing_token:
            raise ValueError(f"Stale fencing token for {message_id}")
        self._states[message_id] = state


def test_orchestrator_outbox_claim_publish_acknowledge_cycle() -> None:
    repo = InMemoryOrchestratorOutboxRepository()
    workflow_id = WorkflowId("019fbdd6-ab3d-77aa-8e61-4c3bc6d53f69")
    message_id = MessageId("019fbdd6-ab3d-77aa-8e61-4c40d234a3bf")
    record = OrchestratorOutboxRecord(
        message_id=message_id, workflow_id=workflow_id, payload={}, created_at=NOW
    )
    repo.enqueue(record)

    claimed = repo.claim_next(workflow_id, fencing_token="token-1")
    assert claimed == record
    # A second claim attempt finds nothing new to claim while already claimed.
    assert repo.claim_next(workflow_id, fencing_token="token-2") is None

    repo.mark_publication_state(message_id, PublicationState.ACKNOWLEDGED, fencing_token="token-1")

    with pytest.raises(ValueError, match="Stale fencing token"):
        repo.mark_publication_state(
            message_id, PublicationState.ACKNOWLEDGED, fencing_token="wrong-token"
        )


def test_agent_event_outbox_claim_publish_acknowledge_cycle() -> None:
    repo = InMemoryAgentEventOutboxRepository()
    workflow_id = WorkflowId("019fbdd6-ab3d-77aa-8e61-4c3bc6d53f69")
    message_id = MessageId("019fbdd7-1000-7000-8000-000000000001")
    record = AgentEventOutboxRecord(
        message_id=message_id, workflow_id=workflow_id, payload={}, created_at=NOW
    )
    repo.enqueue(record)

    claimed = repo.claim_next(workflow_id, fencing_token="token-1")
    assert claimed == record

    repo.mark_publication_state(message_id, PublicationState.ACKNOWLEDGED, fencing_token="token-1")

    with pytest.raises(ValueError, match="Stale fencing token"):
        repo.mark_publication_state(
            message_id, PublicationState.ACKNOWLEDGED, fencing_token="wrong-token"
        )
