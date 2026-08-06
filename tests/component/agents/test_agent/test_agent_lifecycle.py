"""Component tests for the asynchronous Test Agent execution lifecycle."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

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
from ai_platform.api.inmemory_ports import InMemoryAgentPersistence
from ai_platform.orchestrator.domain.audit import AuditRecord
from ai_platform.ports.persistence.transactions import (
    AgentOutcomeCommitIntent,
    AgentOutcomeCommitResult,
    CompletedAgentWork,
    ProviderCallClaimIntent,
    ProviderCallClaimResult,
)
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


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


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


def _build_agent(
    persistence: InMemoryAgentPersistence | None = None,
) -> tuple[TestAgent, InMemoryAgentPersistence]:
    persistence = persistence or InMemoryAgentPersistence()
    agent = TestAgent(
        environment="local-development",
        agent_deployment_id=AgentId("test-agent"),
        agent_component="test-agent",
        outcome_transaction=persistence,
        id_factory=FakeIdentifierFactory(),
    )
    return agent, persistence


def _completed_work(
    *,
    task_attempt_id: str = "attempt-1",
    command_message_id: str = "msg-1",
    command_digest: str = "digest-a",
    outcome_attempt_id: str | None = None,
) -> CompletedAgentWork:
    attempt_id = TaskAttemptId(task_attempt_id)
    event_message_id = MessageId("event-existing")
    return CompletedAgentWork(
        receipt=AgentCompletedReceipt(
            environment="local-development",
            agent_deployment_id=AgentId("test-agent"),
            task_attempt_id=attempt_id,
            command_message_id=MessageId(command_message_id),
            command_digest=command_digest,
            terminal_event_message_id=event_message_id,
            completed_at=NOW,
        ),
        outcome=AgentOutcome(
            task_attempt_id=TaskAttemptId(outcome_attempt_id or task_attempt_id),
            completed_at=NOW,
            result_data={"word_count": 4},
        ),
        event_outbox=AgentEventOutboxRecord(
            message_id=event_message_id,
            workflow_id=WorkflowId("wf-1"),
            logical_channel="task-outcomes",
            ordering_key="wf-1",
            payload_bytes=b"{}",
            headers=(),
            creation_sequence=1,
            created_at=NOW,
        ),
    )


def test_first_execution_completes_and_enqueues_one_event() -> None:
    agent, persistence = _build_agent()

    result = _run(agent.handle(_context(), now=NOW))

    assert result.disposition == TestAgentDisposition.COMPLETED
    assert result.outcome.result_data == {"word_count": 4}
    work = persistence.completed_work[TaskAttemptId("attempt-1")]
    assert work.receipt.terminal_event_message_id == work.event_outbox.message_id
    assert work.receipt.completed_at == result.outcome.completed_at
    assert len(persistence.event_outbox) == 1
    payload = json.loads(work.event_outbox.payload_bytes)
    assert payload["contract_name"] == "TaskCompleted"
    assert len(persistence.audit_records) == 1


def test_duplicate_same_message_and_digest_returns_stored_outcome_without_reexecuting() -> None:
    agent, persistence = _build_agent()
    context = _context()

    first = _run(agent.handle(context, now=NOW))
    second = _run(agent.handle(context, now=NOW + timedelta(seconds=1)))

    assert first.disposition == TestAgentDisposition.COMPLETED
    assert second.disposition == TestAgentDisposition.DUPLICATE_RESOLVED
    assert second.outcome == first.outcome
    assert len(persistence.completed_work) == 1
    assert len(persistence.event_outbox) == 1
    assert len(persistence.audit_records) == 1


def test_different_message_id_same_attempt_raises_identity_conflict() -> None:
    agent, _ = _build_agent()
    _run(agent.handle(_context(command_message_id="msg-1"), now=NOW))

    with pytest.raises(CommandIdentityConflictError):
        _run(agent.handle(_context(command_message_id="msg-2"), now=NOW))


def test_same_message_id_different_digest_raises_integrity_error() -> None:
    agent, _ = _build_agent()
    _run(agent.handle(_context(command_digest="digest-a"), now=NOW))

    with pytest.raises(CommandIntegrityError):
        _run(agent.handle(_context(command_digest="digest-b"), now=NOW))


def test_deadline_already_expired_produces_safe_failure_without_executing() -> None:
    agent, persistence = _build_agent()

    result = _run(
        agent.handle(
            _context(task_result_deadline=NOW - timedelta(seconds=1)),
            now=NOW,
        )
    )

    assert result.disposition == TestAgentDisposition.DEADLINE_EXPIRED_BEFORE_EXECUTION
    assert result.outcome.result_data is None
    assert result.outcome.failure_code == "TASK_RESULT_DEADLINE_EXCEEDED"
    work = next(iter(persistence.completed_work.values()))
    assert json.loads(work.event_outbox.payload_bytes)["contract_name"] == "TaskFailed"


def test_capability_mismatch_is_rejected_before_execution() -> None:
    agent, persistence = _build_agent()

    with pytest.raises(CapabilityMismatchError):
        _run(
            agent.handle(
                _context(capability_name="text.other", capability_version="1.0"),
                now=NOW,
            )
        )

    assert persistence.completed_work == {}
    assert persistence.event_outbox == {}


def test_duplicate_completed_work_without_matching_outcome_fails_closed() -> None:
    persistence = InMemoryAgentPersistence()
    persistence.completed_work[TaskAttemptId("attempt-1")] = _completed_work(
        outcome_attempt_id="different-attempt"
    )
    agent, _ = _build_agent(persistence)

    with pytest.raises(MissingOutcomeInvariantError):
        _run(agent.handle(_context(), now=NOW))


def test_concurrent_duplicate_at_commit_time_resolves_to_one_outcome() -> None:
    """A losing computation reuses the atomic transaction winner."""

    winning_work = _completed_work()

    class RaceTransaction:
        async def get_completed(self, task_attempt_id: TaskAttemptId) -> CompletedAgentWork | None:
            del task_attempt_id
            return None

        async def commit_outcome(
            self, intent: AgentOutcomeCommitIntent
        ) -> AgentOutcomeCommitResult:
            assert isinstance(intent.audit, AuditRecord)
            return AgentOutcomeCommitResult(completed_work=winning_work, created=False)

        async def claim_provider_call(
            self, intent: ProviderCallClaimIntent
        ) -> ProviderCallClaimResult:
            del intent
            raise NotImplementedError("text.word-count never claims a provider call")

    agent = TestAgent(
        environment="local-development",
        agent_deployment_id=AgentId("test-agent"),
        agent_component="test-agent",
        outcome_transaction=RaceTransaction(),
        id_factory=FakeIdentifierFactory(),
    )

    result = _run(agent.handle(_context(), now=NOW))

    assert result.disposition == TestAgentDisposition.DUPLICATE_RESOLVED
    assert result.outcome == winning_work.outcome
