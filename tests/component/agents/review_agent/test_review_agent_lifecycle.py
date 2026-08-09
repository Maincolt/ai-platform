"""Component tests for the asynchronous Review Agent execution lifecycle
(ADR-0018), mirroring `tests/component/agents/summarize_agent/test_summarize_agent_lifecycle.py`."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from ai_platform.agents.domain.outcomes import AgentCompletedReceipt, AgentEventOutboxRecord
from ai_platform.agents.review_agent.agent import ReviewAgent, ReviewAgentDisposition
from ai_platform.agents.review_agent.errors import (
    CapabilityMismatchError,
    CommandIdentityConflictError,
    CommandIntegrityError,
    MissingOutcomeInvariantError,
    ProviderCallReconciliationPendingError,
)
from ai_platform.agents.test_agent.execution_context import ExecuteTaskContext
from ai_platform.api.inmemory_ports import InMemoryAgentPersistence
from ai_platform.ports.ai_router import (
    AICompletionFailureCode,
    AICompletionRequest,
    AICompletionResult,
    AICompletionUsage,
    AIRouterPort,
)
from ai_platform.ports.persistence.transactions import (
    CompletedAgentWork,
    ExistingProviderCallClaim,
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

_ONE_FINDING_JSON = json.dumps(
    [{"file": "src/a.py", "line": 3, "summary": "Missing null check.", "severity": "medium"}]
)


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


@dataclass
class FakeIdentifierFactory:
    _next: int = 0

    def new_id(self) -> str:
        self._next += 1
        return f"event-id-{self._next:04d}"


@dataclass
class FakeAIRouter:
    """A fixed-response fake `AIRouterPort`; real network/credentials are
    never used in this repository's default test suite."""

    result: AICompletionResult
    calls: list[AICompletionRequest] = field(default_factory=list)

    async def complete(self, request: AICompletionRequest) -> AICompletionResult:
        self.calls.append(request)
        return self.result


class _UnreachableAIRouter:
    async def complete(self, request: AICompletionRequest) -> AICompletionResult:
        del request
        raise AssertionError("The AI Router must not be called on this path")


def _context(
    *,
    task_attempt_id: str = "attempt-1",
    command_message_id: str = "msg-1",
    command_digest: str = "digest-a",
    input_text: str = "diff --git a/src/a.py b/src/a.py\n+x = 1\n",
    capability_name: str = "code.review",
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
    *,
    persistence: InMemoryAgentPersistence | None = None,
    ai_router: AIRouterPort | None = None,
    max_output_tokens: int = 256,
) -> tuple[ReviewAgent, InMemoryAgentPersistence]:
    persistence = persistence or InMemoryAgentPersistence()
    agent = ReviewAgent(
        environment="local-development",
        agent_deployment_id=AgentId("review-agent"),
        agent_component="review-agent",
        outcome_transaction=persistence,
        id_factory=FakeIdentifierFactory(),
        ai_router=ai_router if ai_router is not None else _UnreachableAIRouter(),
        max_output_tokens=max_output_tokens,
    )
    return agent, persistence


def test_successful_completion_commits_completed_outcome_with_usage() -> None:
    router = FakeAIRouter(
        result=AICompletionResult(
            output_text=_ONE_FINDING_JSON,
            usage=AICompletionUsage(
                provider="anthropic",
                model="claude-test",
                input_tokens=10,
                output_tokens=5,
                latency_seconds=0.25,
            ),
        )
    )
    agent, persistence = _build_agent(ai_router=router)

    result = _run(agent.handle(_context(), now=NOW))

    assert result.disposition == ReviewAgentDisposition.COMPLETED
    assert result.outcome.result_data == {
        "findings": [
            {"file": "src/a.py", "line": 3, "summary": "Missing null check.", "severity": "medium"}
        ]
    }
    assert len(router.calls) == 1
    assert router.calls[0].idempotency_key == "attempt-1"
    usage = persistence.provider_call_usage[TaskAttemptId("attempt-1")]
    assert usage.provider == "anthropic"
    assert usage.model == "claude-test"
    payload = json.loads(
        persistence.completed_work[TaskAttemptId("attempt-1")].event_outbox.payload_bytes
    )
    assert payload["contract_name"] == "TaskCompleted"
    assert payload["payload"]["result"]["findings"][0]["severity"] == "medium"


def test_empty_findings_list_is_a_valid_completion() -> None:
    router = FakeAIRouter(
        result=AICompletionResult(
            output_text="[]",
            usage=AICompletionUsage(
                provider="anthropic",
                model="m",
                input_tokens=1,
                output_tokens=1,
                latency_seconds=0.1,
            ),
        )
    )
    agent, _ = _build_agent(ai_router=router)

    result = _run(agent.handle(_context(), now=NOW))

    assert result.disposition == ReviewAgentDisposition.COMPLETED
    assert result.outcome.result_data == {"findings": []}


def test_malformed_provider_output_commits_failed_outcome_but_still_attaches_usage() -> None:
    """A real, billed provider call happened even though its output could
    not be parsed -- usage must still be recorded, and the raw unparseable
    text must never leak into the outcome's summary."""
    router = FakeAIRouter(
        result=AICompletionResult(
            output_text="Sure, here is my review: looks good to me!",
            usage=AICompletionUsage(
                provider="anthropic",
                model="m",
                input_tokens=12,
                output_tokens=9,
                latency_seconds=0.3,
            ),
        )
    )
    agent, persistence = _build_agent(ai_router=router)

    result = _run(agent.handle(_context(), now=NOW))

    assert result.disposition == ReviewAgentDisposition.FAILED
    assert result.outcome.result_data is None
    assert result.outcome.failure_code == "MALFORMED_REVIEW_OUTPUT"
    assert result.outcome.summary is not None
    assert "looks good to me" not in result.outcome.summary
    usage = persistence.provider_call_usage[TaskAttemptId("attempt-1")]
    assert usage.provider == "anthropic"


def test_provider_failure_commits_failed_outcome_with_provider_failure_code() -> None:
    router = FakeAIRouter(
        result=AICompletionResult(failure_code=AICompletionFailureCode.ALL_PROVIDERS_EXHAUSTED)
    )
    agent, persistence = _build_agent(ai_router=router)

    result = _run(agent.handle(_context(), now=NOW))

    assert result.disposition == ReviewAgentDisposition.FAILED
    assert result.outcome.result_data is None
    assert result.outcome.failure_code == "ALL_PROVIDERS_EXHAUSTED"
    payload = json.loads(
        persistence.completed_work[TaskAttemptId("attempt-1")].event_outbox.payload_bytes
    )
    assert payload["contract_name"] == "TaskFailed"
    assert TaskAttemptId("attempt-1") not in persistence.provider_call_usage


def test_provider_failure_with_usage_still_attaches_usage() -> None:
    router = FakeAIRouter(
        result=AICompletionResult(
            failure_code=AICompletionFailureCode.PROVIDER_REJECTED_OUTPUT,
            usage=AICompletionUsage(
                provider="openai",
                model="gpt-test",
                input_tokens=8,
                output_tokens=0,
                latency_seconds=0.5,
            ),
        )
    )
    agent, persistence = _build_agent(ai_router=router)

    result = _run(agent.handle(_context(), now=NOW))

    assert result.disposition == ReviewAgentDisposition.FAILED
    usage = persistence.provider_call_usage[TaskAttemptId("attempt-1")]
    assert usage.provider == "openai"


def test_deadline_already_expired_never_claims_or_calls_router() -> None:
    agent, persistence = _build_agent()

    result = _run(
        agent.handle(
            _context(task_result_deadline=NOW - timedelta(seconds=1)),
            now=NOW,
        )
    )

    assert result.disposition == ReviewAgentDisposition.DEADLINE_EXPIRED_BEFORE_EXECUTION
    assert result.outcome.failure_code == "TASK_RESULT_DEADLINE_EXCEEDED"
    assert persistence.provider_call_claims == {}
    payload = json.loads(
        persistence.completed_work[TaskAttemptId("attempt-1")].event_outbox.payload_bytes
    )
    assert payload["contract_name"] == "TaskFailed"


def test_redelivery_with_unresolved_matching_claim_raises_reconciliation_pending() -> None:
    """ADR-0016: no synthetic outcome is committed for this case -- the
    exception propagates to the runtime's existing retry-then-quarantine
    and deadline-expiry mechanisms instead."""
    persistence = InMemoryAgentPersistence()
    persistence.provider_call_claims[TaskAttemptId("attempt-1")] = ExistingProviderCallClaim(
        command_message_id=MessageId("msg-1"),
        command_digest="digest-a",
        claimed_at=NOW - timedelta(seconds=5),
    )
    agent, persistence = _build_agent(persistence=persistence)

    with pytest.raises(ProviderCallReconciliationPendingError) as excinfo:
        _run(agent.handle(_context(), now=NOW))

    assert excinfo.value.task_attempt_id == TaskAttemptId("attempt-1")
    assert persistence.completed_work == {}


def test_redelivery_with_resolved_outcome_short_circuits_without_new_claim() -> None:
    router = FakeAIRouter(
        result=AICompletionResult(
            output_text=_ONE_FINDING_JSON,
            usage=AICompletionUsage(
                provider="anthropic",
                model="claude-test",
                input_tokens=1,
                output_tokens=1,
                latency_seconds=0.1,
            ),
        )
    )
    agent, persistence = _build_agent(ai_router=router)
    context = _context()

    first = _run(agent.handle(context, now=NOW))
    second = _run(agent.handle(context, now=NOW + timedelta(seconds=1)))

    assert first.disposition == ReviewAgentDisposition.COMPLETED
    assert second.disposition == ReviewAgentDisposition.DUPLICATE_RESOLVED
    assert second.outcome == first.outcome
    assert len(router.calls) == 1
    assert len(persistence.completed_work) == 1


def test_different_message_id_same_attempt_via_existing_outcome_raises_identity_conflict() -> None:
    router = FakeAIRouter(
        result=AICompletionResult(
            output_text=_ONE_FINDING_JSON,
            usage=AICompletionUsage(
                provider="anthropic",
                model="m",
                input_tokens=1,
                output_tokens=1,
                latency_seconds=0.1,
            ),
        )
    )
    agent, _ = _build_agent(ai_router=router)
    _run(agent.handle(_context(command_message_id="msg-1"), now=NOW))

    with pytest.raises(CommandIdentityConflictError):
        _run(agent.handle(_context(command_message_id="msg-2"), now=NOW))


def test_same_message_id_different_digest_via_existing_outcome_raises_integrity_error() -> None:
    router = FakeAIRouter(
        result=AICompletionResult(
            output_text=_ONE_FINDING_JSON,
            usage=AICompletionUsage(
                provider="anthropic",
                model="m",
                input_tokens=1,
                output_tokens=1,
                latency_seconds=0.1,
            ),
        )
    )
    agent, _ = _build_agent(ai_router=router)
    _run(agent.handle(_context(command_digest="digest-a"), now=NOW))

    with pytest.raises(CommandIntegrityError):
        _run(agent.handle(_context(command_digest="digest-b"), now=NOW))


def test_different_message_id_via_existing_claim_raises_identity_conflict() -> None:
    persistence = InMemoryAgentPersistence()
    persistence.provider_call_claims[TaskAttemptId("attempt-1")] = ExistingProviderCallClaim(
        command_message_id=MessageId("msg-other"),
        command_digest="digest-a",
        claimed_at=NOW - timedelta(seconds=5),
    )
    agent, _ = _build_agent(persistence=persistence)

    with pytest.raises(CommandIdentityConflictError):
        _run(agent.handle(_context(command_message_id="msg-1"), now=NOW))


def test_different_digest_via_existing_claim_raises_integrity_error() -> None:
    persistence = InMemoryAgentPersistence()
    persistence.provider_call_claims[TaskAttemptId("attempt-1")] = ExistingProviderCallClaim(
        command_message_id=MessageId("msg-1"),
        command_digest="digest-other",
        claimed_at=NOW - timedelta(seconds=5),
    )
    agent, _ = _build_agent(persistence=persistence)

    with pytest.raises(CommandIntegrityError):
        _run(agent.handle(_context(command_message_id="msg-1", command_digest="digest-a"), now=NOW))


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
    assert persistence.provider_call_claims == {}


def test_duplicate_completed_work_without_matching_outcome_fails_closed() -> None:
    persistence = InMemoryAgentPersistence()
    event_message_id = MessageId("event-existing")
    persistence.completed_work[TaskAttemptId("attempt-1")] = CompletedAgentWork(
        receipt=AgentCompletedReceipt(
            environment="local-development",
            agent_deployment_id=AgentId("review-agent"),
            task_attempt_id=TaskAttemptId("attempt-1"),
            command_message_id=MessageId("msg-1"),
            command_digest="digest-a",
            terminal_event_message_id=event_message_id,
            completed_at=NOW,
        ),
        outcome=AgentOutcome(
            task_attempt_id=TaskAttemptId("different-attempt"),
            completed_at=NOW,
            result_data={"findings": []},
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
    agent, _ = _build_agent(persistence=persistence)

    with pytest.raises(MissingOutcomeInvariantError):
        _run(agent.handle(_context(), now=NOW))
