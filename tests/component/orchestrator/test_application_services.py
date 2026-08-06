"""Component tests for the asynchronous Orchestrator application services."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from ai_platform.api.inmemory_ports import InMemoryOrchestratorPersistence
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
from ai_platform.orchestrator.domain.selection import SelectionIntent
from ai_platform.ports.persistence.errors import PersistenceUnavailableError
from ai_platform.ports.persistence.transactions import (
    AcceptedRequestAccessAuditRecord,
    AcceptedRequestAccessDisposition,
)
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


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


@dataclass
class FakeIdentifierFactory(IdentifierFactory):
    _next: int = 0

    def new_id(self) -> str:
        self._next += 1
        return f"id-{self._next:04d}"


@dataclass
class FakeCandidateSelector(CandidateSelectorPort):
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
        del (
            capability_name,
            capability_version,
            command_contract_name,
            command_contract_version,
            event_contract_names,
            event_contract_versions,
            environment,
            now,
        )
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


def _submission_request(
    request_id: str = "req-1",
    fingerprint: str = "fp-a",
    *,
    current_owner_subject_id: str = "owner-1",
) -> SubmissionRequest:
    return SubmissionRequest(
        environment="local-development",
        operation="workflow.submit",
        idempotency_scope_id=IdempotencyScopeId("scope-1"),
        request_id=RequestId(request_id),
        correlation_id=CorrelationId("corr-1"),
        acceptance_actor_id=ActorId("actor-1"),
        accepted_owner_subject_id=OwnerSubjectId("owner-1"),
        current_owner_subject_id=OwnerSubjectId(current_owner_subject_id),
        fingerprint=fingerprint,
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


def _build_submission_orchestrator(
    *,
    candidate_selector: FakeCandidateSelector | None = None,
    persistence: InMemoryOrchestratorPersistence | None = None,
) -> tuple[SubmissionOrchestrator, InMemoryOrchestratorPersistence, FakeCandidateSelector]:
    persistence = persistence or InMemoryOrchestratorPersistence()
    selector = candidate_selector or FakeCandidateSelector(fixed_selection=_selection_intent())
    orchestrator = SubmissionOrchestrator(
        accepted_request_query=persistence,
        request_access_audit=persistence,
        workflow_query=persistence,
        submission_transaction=persistence,
        candidate_selector=selector,
        id_factory=FakeIdentifierFactory(),
    )
    return orchestrator, persistence, selector


@dataclass
class FailingAccessAuditPersistence(InMemoryOrchestratorPersistence):
    async def record_request_access(self, record: AcceptedRequestAccessAuditRecord) -> None:
        del record
        raise PersistenceUnavailableError("required access audit unavailable")


def _terminal_arguments(
    persistence: InMemoryOrchestratorPersistence,
    *,
    validated_message_id: str = "msg-final",
    immutable_message_digest: str = "terminal-digest",
    outcome: AgentOutcome | None = None,
) -> dict[str, object]:
    workflow = next(iter(persistence.workflows.values()))
    task = next(iter(persistence.tasks.values()))
    attempt = next(iter(persistence.task_attempts.values()))
    command = next(iter(persistence.command_outbox.values()))
    resolved_outcome = outcome or AgentOutcome(
        task_attempt_id=attempt.task_attempt_id,
        completed_at=NOW,
        result_data={"word_count": 9},
    )
    return {
        "environment": "local-development",
        "logical_consumer_id": "orchestrator-outcome-consumer",
        "validated_message_id": MessageId(validated_message_id),
        "immutable_message_digest": immutable_message_digest,
        "workflow_id": workflow.workflow_id,
        "task_id": task.task_id,
        "task_attempt_id": attempt.task_attempt_id,
        "correlation_id": workflow.correlation_id,
        "causation_message_id": command.message_id,
        "producer_component": attempt.selection.implementation_identity,
        "producer_instance_id": str(attempt.selection.agent_id),
        "capability_name": attempt.selection.capability_name,
        "capability_version": attempt.selection.capability_version,
        "result_text": (
            "the quick brown fox jumps over the lazy dog"
            if resolved_outcome.result_data is not None
            else None
        ),
        "agent_evidence_component": attempt.selection.implementation_identity,
        "agent_evidence_instance_id": str(attempt.selection.agent_id),
        "outcome": resolved_outcome,
        "occurred_at": NOW + timedelta(seconds=1),
    }


def test_submission_new_request_creates_workflow_and_enqueues_outbox() -> None:
    orchestrator, persistence, _ = _build_submission_orchestrator()

    result = _run(orchestrator.submit(_submission_request(), now=NOW))

    assert result.disposition == SubmissionDisposition.NEW
    assert result.workflow_id is not None
    assert result.workflow is not None and result.workflow.state is not None
    assert result.workflow.state.value == "DISPATCHED"
    assert result.workflow_id in persistence.workflows
    assert len(persistence.command_outbox) == 1
    command = next(iter(persistence.command_outbox.values()))
    assert command.workflow_id == result.workflow_id
    assert command.logical_channel == "task-commands"
    assert json.loads(command.payload_bytes)["contract_name"] == "ExecuteTask"
    assert len(persistence.audit_records) == 1


def test_submission_equivalent_replay_never_checks_candidate_selector() -> None:
    orchestrator, persistence, selector = _build_submission_orchestrator()
    request = _submission_request()

    first = _run(orchestrator.submit(request, now=NOW))
    second = _run(orchestrator.submit(request, now=NOW + timedelta(seconds=1)))

    assert first.disposition == SubmissionDisposition.NEW
    assert second.disposition == SubmissionDisposition.EQUIVALENT_REPLAY
    assert second.workflow_id == first.workflow_id
    assert selector.call_count == 1
    assert len(persistence.command_outbox) == 1
    assert len(persistence.request_access_audit_records) == 1
    access = persistence.request_access_audit_records[0]
    assert access.disposition is AcceptedRequestAccessDisposition.EQUIVALENT_REPLAY_AUTHORIZED
    assert access.current_actor_id == request.acceptance_actor_id
    assert access.workflow_id == first.workflow_id


def test_submission_fingerprint_conflict_creates_no_new_workflow() -> None:
    orchestrator, persistence, _ = _build_submission_orchestrator()
    first = _run(orchestrator.submit(_submission_request(fingerprint="fp-a"), now=NOW))
    second = _run(orchestrator.submit(_submission_request(fingerprint="fp-b"), now=NOW))

    assert second.disposition == SubmissionDisposition.FINGERPRINT_CONFLICT
    assert second.workflow_id == first.workflow_id
    assert second.workflow is None
    assert len(persistence.workflows) == 1
    assert len(persistence.command_outbox) == 1
    assert len(persistence.request_access_audit_records) == 1
    assert (
        persistence.request_access_audit_records[0].disposition
        is AcceptedRequestAccessDisposition.FINGERPRINT_CONFLICT_AUTHORIZED
    )


def test_submission_owner_mismatch_is_audited_before_safe_denial() -> None:
    orchestrator, persistence, _ = _build_submission_orchestrator()
    first = _run(orchestrator.submit(_submission_request(), now=NOW))

    denied = _run(
        orchestrator.submit(
            _submission_request(current_owner_subject_id="owner-2"),
            now=NOW + timedelta(seconds=1),
        )
    )

    assert denied.disposition is SubmissionDisposition.OWNER_INTENT_MISMATCH
    assert denied.workflow_id is None
    assert denied.workflow is None
    assert len(persistence.workflows) == 1
    assert len(persistence.command_outbox) == 1
    assert len(persistence.request_access_audit_records) == 1
    access = persistence.request_access_audit_records[0]
    assert access.disposition is AcceptedRequestAccessDisposition.OWNER_INTENT_MISMATCH
    assert access.workflow_id == first.workflow_id
    assert access.resolved_owner_subject_id == OwnerSubjectId("owner-2")


def test_required_access_audit_failure_denies_replay_disclosure() -> None:
    persistence = FailingAccessAuditPersistence()
    orchestrator, _, _ = _build_submission_orchestrator(persistence=persistence)
    request = _submission_request()
    _run(orchestrator.submit(request, now=NOW))

    with pytest.raises(PersistenceUnavailableError, match="required access audit unavailable"):
        _run(orchestrator.submit(request, now=NOW + timedelta(seconds=1)))

    assert len(persistence.workflows) == 1
    assert len(persistence.command_outbox) == 1


def test_submission_no_eligible_agent_creates_nothing() -> None:
    orchestrator, persistence, _ = _build_submission_orchestrator(
        candidate_selector=FakeCandidateSelector(raise_no_eligible=True)
    )

    result = _run(orchestrator.submit(_submission_request(), now=NOW))

    assert result.disposition == SubmissionDisposition.NO_ELIGIBLE_AGENT
    assert result.workflow_id is None
    assert persistence.accepted_requests == {}
    assert persistence.workflows == {}
    assert persistence.command_outbox == {}
    assert persistence.audit_records == []


def test_submission_configuration_error_creates_nothing() -> None:
    orchestrator, persistence, _ = _build_submission_orchestrator(
        candidate_selector=FakeCandidateSelector(raise_configuration_error=True)
    )

    result = _run(orchestrator.submit(_submission_request(), now=NOW))

    assert result.disposition == SubmissionDisposition.CONFIGURATION_ERROR
    assert persistence.accepted_requests == {}
    assert persistence.workflows == {}
    assert persistence.command_outbox == {}


def test_terminal_processor_first_completion_applies_transition() -> None:
    orchestrator, persistence, _ = _build_submission_orchestrator()
    _run(orchestrator.submit(_submission_request(), now=NOW))
    processor = TerminalEventProcessor(transaction=persistence)

    result = _run(processor.process(**_terminal_arguments(persistence)))  # type: ignore[arg-type]

    assert result.disposition == TerminalDisposition.APPLIED
    assert result.workflow is not None and result.workflow.state is not None
    assert result.workflow.state.value == "COMPLETED"
    assert len(persistence.audit_records) == 2


def test_terminal_processor_duplicate_message_does_not_reapply() -> None:
    orchestrator, persistence, _ = _build_submission_orchestrator()
    _run(orchestrator.submit(_submission_request(), now=NOW))
    processor = TerminalEventProcessor(transaction=persistence)
    arguments = _terminal_arguments(persistence)

    first = _run(processor.process(**arguments))  # type: ignore[arg-type]
    second = _run(processor.process(**arguments))  # type: ignore[arg-type]

    assert first.disposition == TerminalDisposition.APPLIED
    assert second.disposition == TerminalDisposition.DUPLICATE
    assert len(persistence.audit_records) == 2


def test_terminal_processor_late_event_after_terminal_does_not_mutate() -> None:
    orchestrator, persistence, _ = _build_submission_orchestrator()
    _run(orchestrator.submit(_submission_request(), now=NOW))
    processor = TerminalEventProcessor(transaction=persistence)
    first = _terminal_arguments(persistence)
    _run(processor.process(**first))  # type: ignore[arg-type]
    attempt = next(iter(persistence.task_attempts.values()))
    late = _terminal_arguments(
        persistence,
        validated_message_id="msg-late",
        immutable_message_digest="late-digest",
        outcome=AgentOutcome(
            task_attempt_id=attempt.task_attempt_id,
            completed_at=NOW + timedelta(seconds=5),
            failure_code="TASK_EXECUTION_FAILED",
            summary="too late",
        ),
    )

    result = _run(processor.process(**late))  # type: ignore[arg-type]

    assert result.disposition == TerminalDisposition.LATE_AFTER_TERMINAL
    stored = next(iter(persistence.workflows.values()))
    assert stored.state is not None and stored.state.value == "COMPLETED"
    assert len(persistence.audit_records) == 3


def test_deadline_reconciler_fails_expired_dispatched_workflow() -> None:
    orchestrator, persistence, _ = _build_submission_orchestrator()
    submission = _run(orchestrator.submit(_submission_request(), now=NOW))
    reconciler = DeadlineReconciler(transaction=persistence)

    reconciled = _run(reconciler.reconcile(now=NOW + timedelta(seconds=31)))

    assert reconciled == [submission.workflow_id]
    assert submission.workflow_id is not None
    stored = persistence.workflows[submission.workflow_id]
    assert stored.state is not None and stored.state.value == "FAILED"
    assert stored.history[-1].cause == "deadline_expired"
    assert len(persistence.audit_records) == 2


def test_deadline_reconciler_skips_workflow_already_completed_by_real_outcome() -> None:
    orchestrator, persistence, _ = _build_submission_orchestrator()
    submission = _run(orchestrator.submit(_submission_request(), now=NOW))
    processor = TerminalEventProcessor(transaction=persistence)
    _run(processor.process(**_terminal_arguments(persistence)))  # type: ignore[arg-type]
    reconciler = DeadlineReconciler(transaction=persistence)

    reconciled = _run(reconciler.reconcile(now=NOW + timedelta(seconds=31)))

    assert reconciled == []
    assert submission.workflow_id is not None
    stored = persistence.workflows[submission.workflow_id]
    assert stored.state is not None and stored.state.value == "COMPLETED"
    assert len(persistence.audit_records) == 2


def test_submission_then_terminal_completion_end_to_end() -> None:
    orchestrator, persistence, _ = _build_submission_orchestrator()
    submission = _run(orchestrator.submit(_submission_request(), now=NOW))
    processor = TerminalEventProcessor(transaction=persistence)

    terminal = _run(processor.process(**_terminal_arguments(persistence)))  # type: ignore[arg-type]

    assert terminal.disposition == TerminalDisposition.APPLIED
    assert submission.workflow_id is not None
    final = _run(persistence.get(submission.workflow_id))
    assert final is not None and final.state is not None
    assert final.state.value == "COMPLETED"
    assert final.result is not None and final.result.result_data == {"word_count": 9}
    assert len(persistence.audit_records) == 2
