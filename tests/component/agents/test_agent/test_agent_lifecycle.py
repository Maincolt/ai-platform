"""Component tests: in-memory fakes proving the Test Agent's execution
lifecycle behaves correctly per vertical-slice-01.md Section 14 and
ADR-0007 Section 4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from ai_platform.agents.domain.outcomes import AgentCompletedReceipt, AgentEventOutboxRecord
from ai_platform.agents.test_agent.agent import TestAgent, TestAgentDisposition
from ai_platform.agents.test_agent.errors import (
    CapabilityMismatchError,
    CommandIdentityConflictError,
    CommandIntegrityError,
    MissingOutcomeInvariantError,
)
from ai_platform.agents.test_agent.execution_context import ExecuteTaskContext
from ai_platform.ports.persistence.agent import (
    AgentOutcomeRepositoryPort,
    AgentReceiptRepositoryPort,
)
from ai_platform.ports.persistence.outbox import AgentEventOutboxRepositoryPort
from ai_platform.shared.identifiers import (
    AgentId,
    CorrelationId,
    MessageId,
    TaskAttemptId,
    TaskId,
    WorkflowId,
)
from ai_platform.shared.outcomes import AgentOutcome

NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# In-memory fakes (test-owned, not adapters)
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

    def seed(self, receipt: AgentCompletedReceipt) -> None:
        """Test-only helper to pre-populate a receipt as if another
        process instance had already committed it."""
        self._receipts[receipt.task_attempt_id] = receipt


@dataclass
class InMemoryAgentOutcomeRepository(AgentOutcomeRepositoryPort):
    _outcomes: dict[TaskAttemptId, AgentOutcome] = field(default_factory=dict)
    save_call_count: int = 0

    def get_by_attempt(self, task_attempt_id: TaskAttemptId) -> AgentOutcome | None:
        return self._outcomes.get(task_attempt_id)

    def save(self, outcome: AgentOutcome) -> None:
        if outcome.task_attempt_id in self._outcomes:
            raise ValueError(
                f"An outcome already exists for {outcome.task_attempt_id}; "
                "exactly one accepted outcome per attempt is required"
            )
        self.save_call_count += 1
        self._outcomes[outcome.task_attempt_id] = outcome

    def seed(self, outcome: AgentOutcome) -> None:
        """Test-only helper to pre-populate an outcome without going
        through save() (simulating one already committed by another
        process instance, without inflating save_call_count)."""
        self._outcomes[outcome.task_attempt_id] = outcome


@dataclass
class InMemoryAgentEventOutboxRepository(AgentEventOutboxRepositoryPort):
    records: list[AgentEventOutboxRecord] = field(default_factory=list)

    def enqueue(self, record: AgentEventOutboxRecord) -> None:
        self.records.append(record)

    def claim_next(
        self, workflow_id: WorkflowId, *, fencing_token: str
    ) -> AgentEventOutboxRecord | None:
        raise NotImplementedError("Not exercised by lifecycle tests")

    def mark_publication_state(
        self, message_id: MessageId, state: object, *, fencing_token: str
    ) -> None:
        raise NotImplementedError("Not exercised by lifecycle tests")


@dataclass
class FakeIdentifierFactory:
    _next: int = 0

    def new_id(self) -> str:
        self._next += 1
        return f"event-id-{self._next:04d}"


def _context(
    *,
    task_attempt_id: str = "attempt-1",
    command_message_id: str = "msg-1",
    command_digest: str = "digest-a",
    input_text: str = "the quick brown fox",
    capability_name: str = "text.word-count",
    capability_version: str = "1.0",
    task_result_deadline: datetime = NOW + timedelta(seconds=30),
) -> ExecuteTaskContext:
    return ExecuteTaskContext(
        workflow_id=WorkflowId("wf-1"),
        task_id=TaskId("task-1"),
        task_attempt_id=TaskAttemptId(task_attempt_id),
        correlation_id=CorrelationId("corr-1"),
        command_message_id=MessageId(command_message_id),
        command_digest=command_digest,
        input_text=input_text,
        capability_name=capability_name,
        capability_version=capability_version,
        task_result_deadline=task_result_deadline,
    )


def _build_agent() -> tuple[
    TestAgent,
    InMemoryAgentReceiptRepository,
    InMemoryAgentOutcomeRepository,
    InMemoryAgentEventOutboxRepository,
]:
    receipt_repo = InMemoryAgentReceiptRepository()
    outcome_repo = InMemoryAgentOutcomeRepository()
    event_outbox_repo = InMemoryAgentEventOutboxRepository()
    agent = TestAgent(
        environment="local-development",
        agent_deployment_id=AgentId("test-agent"),
        agent_component="test-agent",
        receipt_repo=receipt_repo,
        outcome_repo=outcome_repo,
        event_outbox_repo=event_outbox_repo,
        id_factory=FakeIdentifierFactory(),
    )
    return agent, receipt_repo, outcome_repo, event_outbox_repo


def test_first_execution_completes_and_enqueues_one_event() -> None:
    agent, receipt_repo, outcome_repo, event_outbox_repo = _build_agent()

    result = agent.handle(_context(), now=NOW)

    assert result.disposition == TestAgentDisposition.COMPLETED
    assert result.outcome is not None
    assert result.outcome.word_count == 4
    assert receipt_repo.get_by_attempt(TaskAttemptId("attempt-1")) is not None
    assert outcome_repo.save_call_count == 1
    assert len(event_outbox_repo.records) == 1
    payload = event_outbox_repo.records[0].payload
    assert payload["contract_name"] == "TaskCompleted"


def test_duplicate_same_message_and_digest_returns_stored_outcome_without_reexecuting() -> None:
    agent, _, outcome_repo, event_outbox_repo = _build_agent()
    context = _context()

    first = agent.handle(context, now=NOW)
    second = agent.handle(context, now=NOW + timedelta(seconds=1))

    assert first.disposition == TestAgentDisposition.COMPLETED
    assert second.disposition == TestAgentDisposition.DUPLICATE_RESOLVED
    assert second.outcome == first.outcome
    assert outcome_repo.save_call_count == 1  # not executed/saved a second time
    assert len(event_outbox_repo.records) == 1  # not enqueued a second time


def test_different_message_id_same_attempt_raises_identity_conflict() -> None:
    agent, _, _, _ = _build_agent()
    first_context = _context(command_message_id="msg-1")
    conflicting_context = _context(command_message_id="msg-2")

    agent.handle(first_context, now=NOW)

    with pytest.raises(CommandIdentityConflictError):
        agent.handle(conflicting_context, now=NOW)


def test_same_message_id_different_digest_raises_integrity_error() -> None:
    agent, _, _, _ = _build_agent()
    first_context = _context(command_digest="digest-a")
    corrupted_context = _context(command_digest="digest-b")

    agent.handle(first_context, now=NOW)

    with pytest.raises(CommandIntegrityError):
        agent.handle(corrupted_context, now=NOW)


def test_deadline_already_expired_produces_safe_failure_without_executing() -> None:
    agent, _, outcome_repo, event_outbox_repo = _build_agent()
    context = _context(task_result_deadline=NOW - timedelta(seconds=1))

    result = agent.handle(context, now=NOW)

    assert result.disposition == TestAgentDisposition.DEADLINE_EXPIRED_BEFORE_EXECUTION
    assert result.outcome is not None
    assert result.outcome.word_count is None
    assert result.outcome.failure_code == "TASK_RESULT_DEADLINE_EXCEEDED"
    assert outcome_repo.save_call_count == 1
    payload = event_outbox_repo.records[0].payload
    assert payload["contract_name"] == "TaskFailed"


def test_capability_mismatch_is_rejected_before_execution() -> None:
    agent, _, outcome_repo, event_outbox_repo = _build_agent()
    context = _context(capability_name="text.other", capability_version="1.0")

    with pytest.raises(CapabilityMismatchError):
        agent.handle(context, now=NOW)

    assert outcome_repo.save_call_count == 0
    assert event_outbox_repo.records == []


def test_duplicate_receipt_without_outcome_fails_closed() -> None:
    """A completed receipt should never exist without its outcome (they
    commit together atomically). If persistence is somehow inconsistent,
    the Agent must fail closed rather than silently returning a result
    with no outcome."""
    receipt_repo, outcome_repo, event_outbox_repo = (
        InMemoryAgentReceiptRepository(),
        InMemoryAgentOutcomeRepository(),
        InMemoryAgentEventOutboxRepository(),
    )
    orphaned_receipt = AgentCompletedReceipt(
        environment="local-development",
        agent_deployment_id=AgentId("test-agent"),
        task_attempt_id=TaskAttemptId("attempt-1"),
        command_message_id=MessageId("msg-1"),
        command_digest="digest-a",
    )
    receipt_repo.seed(orphaned_receipt)
    # Deliberately no matching outcome seeded.

    agent = TestAgent(
        environment="local-development",
        agent_deployment_id=AgentId("test-agent"),
        agent_component="test-agent",
        receipt_repo=receipt_repo,
        outcome_repo=outcome_repo,
        event_outbox_repo=event_outbox_repo,
        id_factory=FakeIdentifierFactory(),
    )

    with pytest.raises(MissingOutcomeInvariantError):
        agent.handle(_context(), now=NOW)


def test_concurrent_duplicate_at_commit_time_resolves_to_one_outcome() -> None:
    """Simulates two 'first-time' executions racing for the same attempt:
    the receipt repository's create_or_resolve arbitrates one winner via its
    is_new flag (not value equality -- two independently constructed
    receipts for the same real command are equal by value even when one is
    the race loser), and the loser must reuse that outcome rather than
    saving a second one."""
    outcome_repo = InMemoryAgentOutcomeRepository()
    event_outbox_repo = InMemoryAgentEventOutboxRepository()

    winning_receipt = AgentCompletedReceipt(
        environment="local-development",
        agent_deployment_id=AgentId("test-agent"),
        task_attempt_id=TaskAttemptId("attempt-1"),
        command_message_id=MessageId("msg-1"),
        command_digest="digest-a",
    )
    winning_outcome = AgentOutcome(
        task_attempt_id=TaskAttemptId("attempt-1"), completed_at=NOW, word_count=4
    )
    outcome_repo.seed(winning_outcome)

    class RaceSimulatingReceiptRepository(InMemoryAgentReceiptRepository):
        """Simulates the race window: this agent instance's own pre-check
        (get_by_attempt) ran before a concurrent writer committed, so it
        found nothing, but create_or_resolve discovers the concurrent
        winner and correctly reports is_new=False."""

        def get_by_attempt(self, task_attempt_id: TaskAttemptId) -> AgentCompletedReceipt | None:
            return None

        def create_or_resolve(
            self, receipt: AgentCompletedReceipt
        ) -> tuple[AgentCompletedReceipt, bool]:
            return winning_receipt, False

    receipt_repo = RaceSimulatingReceiptRepository()

    agent = TestAgent(
        environment="local-development",
        agent_deployment_id=AgentId("test-agent"),
        agent_component="test-agent",
        receipt_repo=receipt_repo,
        outcome_repo=outcome_repo,
        event_outbox_repo=event_outbox_repo,
        id_factory=FakeIdentifierFactory(),
    )

    result = agent.handle(_context(), now=NOW)

    assert result.disposition == TestAgentDisposition.DUPLICATE_RESOLVED
    assert result.outcome == winning_outcome
    assert outcome_repo.save_call_count == 0  # the loser never saves its own outcome
    assert event_outbox_repo.records == []  # the loser never enqueues its own event
