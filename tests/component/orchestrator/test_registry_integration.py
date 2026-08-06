"""Integration tests for the real Registry selector and application services."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ai_platform.api.inmemory_ports import InMemoryOrchestratorPersistence
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
from ai_platform.orchestrator.registry.availability import (
    AvailabilityClassification,
    AvailabilityObservation,
    AvailabilityPort,
)
from ai_platform.orchestrator.registry.declarations import CapabilityBinding
from ai_platform.orchestrator.registry.snapshot import load_registry_snapshot
from ai_platform.shared.identifiers import (
    ActorId,
    AgentId,
    CorrelationId,
    IdempotencyScopeId,
    MessageId,
    OwnerSubjectId,
    RequestId,
)
from ai_platform.shared.outcomes import AgentOutcome

NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
ENVIRONMENT = "local-development"


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


@dataclass
class FixedAvailabilityPort(AvailabilityPort):
    agent_id: AgentId

    def observe(
        self, agent_id: AgentId, capability_name: str, capability_version: str
    ) -> AvailabilityObservation:
        del capability_name, capability_version
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
        event_contract_names=("TaskCompleted", "TaskFailed"),
        event_contract_versions=("1.0", "1.0"),
        agent_id=AgentId("test-agent"),
        implementation_identity="test-agent-impl",
        implementation_version="1.0",
        deployment_declaration_digest="digest-1",
        environment=ENVIRONMENT,
        enabled=True,
    )


def _submission_request() -> SubmissionRequest:
    return SubmissionRequest(
        environment=ENVIRONMENT,
        operation="workflow.submit",
        idempotency_scope_id=IdempotencyScopeId("scope-1"),
        request_id=RequestId("req-1"),
        correlation_id=CorrelationId("corr-1"),
        acceptance_actor_id=ActorId("actor-1"),
        accepted_owner_subject_id=OwnerSubjectId("owner-1"),
        current_owner_subject_id=OwnerSubjectId("owner-1"),
        fingerprint="fp-a",
        fingerprint_policy_version="1.0",
        policy_identity="local-development-policy",
        policy_revision="rev-1",
        policy_decision="allow",
        scope_mapping_revision="rev-1",
        authorization_evidence="evidence-1",
        text="the quick brown fox jumps over the lazy dog",
        capability_name="text.word-count",
        capability_version="1.0",
        command_contract_name="ExecuteTask",
        command_contract_version="1.0",
        event_contract_names=("TaskCompleted", "TaskFailed"),
        event_contract_versions=("1.0", "1.0"),
        task_result_deadline=NOW + timedelta(seconds=30),
    )


def _orchestrator(
    bindings: list[CapabilityBinding],
) -> tuple[SubmissionOrchestrator, InMemoryOrchestratorPersistence]:
    snapshot = load_registry_snapshot(bindings, revision="rev-1")
    selector = RegistryCandidateSelector(
        snapshot=snapshot,
        availability_port=FixedAvailabilityPort(agent_id=AgentId("test-agent")),
        selection_policy_version="1.0",
    )
    persistence = InMemoryOrchestratorPersistence()
    orchestrator = SubmissionOrchestrator(
        accepted_request_query=persistence,
        request_access_audit=persistence,
        workflow_query=persistence,
        submission_transaction=persistence,
        candidate_selector=selector,
        id_factory=FakeIdentifierFactory(),
    )
    return orchestrator, persistence


def _terminal_arguments(persistence: InMemoryOrchestratorPersistence) -> dict[str, object]:
    workflow = next(iter(persistence.workflows.values()))
    task = next(iter(persistence.tasks.values()))
    attempt = next(iter(persistence.task_attempts.values()))
    command = next(iter(persistence.command_outbox.values()))
    return {
        "environment": ENVIRONMENT,
        "logical_consumer_id": "orchestrator-outcome-consumer",
        "validated_message_id": MessageId("msg-final"),
        "immutable_message_digest": "terminal-digest",
        "workflow_id": workflow.workflow_id,
        "task_id": task.task_id,
        "task_attempt_id": attempt.task_attempt_id,
        "correlation_id": workflow.correlation_id,
        "causation_message_id": command.message_id,
        "producer_component": attempt.selection.implementation_identity,
        "producer_instance_id": str(attempt.selection.agent_id),
        "capability_name": attempt.selection.capability_name,
        "capability_version": attempt.selection.capability_version,
        "result_text": "the quick brown fox jumps over the lazy dog",
        "agent_evidence_component": attempt.selection.implementation_identity,
        "agent_evidence_instance_id": str(attempt.selection.agent_id),
        "outcome": AgentOutcome(
            task_attempt_id=attempt.task_attempt_id,
            completed_at=NOW + timedelta(seconds=1),
            result_data={"word_count": 9},
        ),
        "occurred_at": NOW + timedelta(seconds=1),
    }


def test_submission_selects_real_registry_candidate_and_dispatches() -> None:
    orchestrator, persistence = _orchestrator([_test_agent_binding()])

    result = _run(orchestrator.submit(_submission_request(), now=NOW))

    assert result.disposition == SubmissionDisposition.NEW
    assert result.workflow is not None and result.workflow.state is not None
    assert result.workflow.state.value == "DISPATCHED"
    command = next(iter(persistence.command_outbox.values()))
    payload = json.loads(command.payload_bytes)
    assert payload["contract_name"] == "ExecuteTask"
    assert payload["payload"]["capability"] == "text.word-count"


def test_submission_no_eligible_agent_when_registry_has_no_matching_binding() -> None:
    orchestrator, persistence = _orchestrator([])

    result = _run(orchestrator.submit(_submission_request(), now=NOW))

    assert result.disposition == SubmissionDisposition.NO_ELIGIBLE_AGENT
    assert persistence.accepted_requests == {}
    assert persistence.workflows == {}
    assert persistence.command_outbox == {}


def test_full_lifecycle_submit_dispatch_complete_via_real_registry() -> None:
    orchestrator, persistence = _orchestrator([_test_agent_binding()])
    submission = _run(orchestrator.submit(_submission_request(), now=NOW))
    processor = TerminalEventProcessor(transaction=persistence)

    terminal = _run(processor.process(**_terminal_arguments(persistence)))  # type: ignore[arg-type]

    assert terminal.disposition == TerminalDisposition.APPLIED
    assert submission.workflow_id is not None
    final = _run(persistence.get(submission.workflow_id))
    assert final is not None and final.state is not None
    assert final.state.value == "COMPLETED"
    assert final.result is not None and final.result.result_data == {"word_count": 9}


def test_deadline_reconciler_does_not_override_real_completed_workflow() -> None:
    orchestrator, persistence = _orchestrator([_test_agent_binding()])
    submission = _run(orchestrator.submit(_submission_request(), now=NOW))
    processor = TerminalEventProcessor(transaction=persistence)
    _run(processor.process(**_terminal_arguments(persistence)))  # type: ignore[arg-type]
    reconciler = DeadlineReconciler(transaction=persistence)

    reconciled = _run(reconciler.reconcile(now=NOW + timedelta(seconds=60)))

    assert reconciled == []
    assert submission.workflow_id is not None
    final = _run(persistence.get(submission.workflow_id))
    assert final is not None and final.state is not None
    assert final.state.value == "COMPLETED"
