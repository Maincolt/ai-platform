"""Submission-transaction orchestration (vertical-slice-01.md Sections 6, 11).

Resolves any existing accepted-request mapping first; an equivalent replay
never touches Registry/Agent readiness. Only a genuinely new request
selects a candidate and atomically constructs workflow/task/attempt/
history/outbox/audit through the Phase 2 ports.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ai_platform.orchestrator.application.candidate_selection import (
    CandidateSelectionConfigurationError,
    CandidateSelectorPort,
    NoEligibleCandidateError,
)
from ai_platform.orchestrator.application.ids import IdentifierFactory
from ai_platform.orchestrator.application.messages import build_execute_task_payload
from ai_platform.orchestrator.domain.accepted_request import (
    AcceptanceEvidence,
    AcceptedRequestKey,
    FingerprintComparison,
    compare_fingerprint,
)
from ai_platform.orchestrator.domain.audit import AuditRecord
from ai_platform.orchestrator.domain.identifiers import (
    ActorId,
    CorrelationId,
    IdempotencyScopeId,
    MessageId,
    OwnerSubjectId,
    RequestId,
    TaskAttemptId,
    TaskId,
    WorkflowId,
)
from ai_platform.orchestrator.domain.recovery import OrchestratorOutboxRecord
from ai_platform.orchestrator.domain.task import Task, TaskAttempt
from ai_platform.orchestrator.domain.workflow import Workflow
from ai_platform.ports.persistence.accepted_request import AcceptedRequestRepositoryPort
from ai_platform.ports.persistence.audit import AuditRepositoryPort
from ai_platform.ports.persistence.outbox import OrchestratorOutboxRepositoryPort
from ai_platform.ports.persistence.task import TaskAttemptRepositoryPort, TaskRepositoryPort
from ai_platform.ports.persistence.workflow import WorkflowRepositoryPort


@dataclass(frozen=True, slots=True)
class SubmissionRequest:
    """Everything the Workflow API (Phase 5) is expected to have already
    validated/resolved before calling `SubmissionOrchestrator.submit`."""

    environment: str
    operation: str
    idempotency_scope_id: IdempotencyScopeId
    request_id: RequestId
    correlation_id: CorrelationId
    acceptance_actor_id: ActorId
    accepted_owner_subject_id: OwnerSubjectId
    fingerprint: str
    fingerprint_policy_version: str
    text: str
    capability_name: str
    capability_version: str
    command_contract_name: str
    command_contract_version: str
    event_contract_names: tuple[str, ...]
    event_contract_versions: tuple[str, ...]
    task_result_deadline: datetime


class SubmissionDisposition(Enum):
    """Domain-level submission outcome. Mapping to HTTP status is Phase 5's
    responsibility, not this service's (see docs/sprint-3/consilium.md)."""

    NEW = "NEW"
    EQUIVALENT_REPLAY = "EQUIVALENT_REPLAY"
    FINGERPRINT_CONFLICT = "FINGERPRINT_CONFLICT"
    NO_ELIGIBLE_AGENT = "NO_ELIGIBLE_AGENT"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    disposition: SubmissionDisposition
    workflow_id: WorkflowId | None
    workflow: Workflow | None


class SubmissionOrchestrator:
    def __init__(
        self,
        *,
        accepted_request_repo: AcceptedRequestRepositoryPort,
        workflow_repo: WorkflowRepositoryPort,
        task_repo: TaskRepositoryPort,
        task_attempt_repo: TaskAttemptRepositoryPort,
        outbox_repo: OrchestratorOutboxRepositoryPort,
        audit_repo: AuditRepositoryPort,
        candidate_selector: CandidateSelectorPort,
        id_factory: IdentifierFactory,
        orchestrator_component: str = "orchestrator",
        orchestrator_instance_id: str = "orchestrator-instance",
    ) -> None:
        self._accepted_request_repo = accepted_request_repo
        self._workflow_repo = workflow_repo
        self._task_repo = task_repo
        self._task_attempt_repo = task_attempt_repo
        self._outbox_repo = outbox_repo
        self._audit_repo = audit_repo
        self._candidate_selector = candidate_selector
        self._id_factory = id_factory
        self._orchestrator_component = orchestrator_component
        self._orchestrator_instance_id = orchestrator_instance_id

    def submit(self, request: SubmissionRequest, *, now: datetime) -> SubmissionResult:
        key = AcceptedRequestKey(
            environment=request.environment,
            operation=request.operation,
            idempotency_scope_id=request.idempotency_scope_id,
            request_id=request.request_id,
        )
        evidence = AcceptanceEvidence(
            acceptance_actor_id=request.acceptance_actor_id,
            accepted_owner_subject_id=request.accepted_owner_subject_id,
            fingerprint=request.fingerprint,
            fingerprint_policy_version=request.fingerprint_policy_version,
            accepted_at=now,
        )
        # A candidate workflow_id is always generated up front; it is
        # discarded if the mapping already existed (ADR-0006 Section 5:
        # database uniqueness, not a precheck, arbitrates acceptance).
        candidate_workflow_id = WorkflowId(self._id_factory.new_id())

        resolved_workflow_id, resolved_evidence, is_new = (
            self._accepted_request_repo.create_or_resolve(key, evidence, candidate_workflow_id)
        )

        if not is_new:
            comparison = compare_fingerprint(resolved_evidence.fingerprint, request.fingerprint)
            if comparison == FingerprintComparison.FINGERPRINT_CONFLICT:
                return SubmissionResult(
                    disposition=SubmissionDisposition.FINGERPRINT_CONFLICT,
                    workflow_id=resolved_workflow_id,
                    workflow=None,
                )
            # Equivalent replay: never evaluate Registry/Agent readiness.
            existing_workflow = self._workflow_repo.get_by_id(resolved_workflow_id)
            return SubmissionResult(
                disposition=SubmissionDisposition.EQUIVALENT_REPLAY,
                workflow_id=resolved_workflow_id,
                workflow=existing_workflow,
            )

        # Only a genuinely new request checks readiness and selects a candidate.
        try:
            selection = self._candidate_selector.select(
                capability_name=request.capability_name,
                capability_version=request.capability_version,
                command_contract_name=request.command_contract_name,
                command_contract_version=request.command_contract_version,
                event_contract_names=request.event_contract_names,
                event_contract_versions=request.event_contract_versions,
                environment=request.environment,
                now=now,
            )
        except NoEligibleCandidateError:
            return SubmissionResult(
                disposition=SubmissionDisposition.NO_ELIGIBLE_AGENT,
                workflow_id=None,
                workflow=None,
            )
        except CandidateSelectionConfigurationError:
            return SubmissionResult(
                disposition=SubmissionDisposition.CONFIGURATION_ERROR,
                workflow_id=None,
                workflow=None,
            )

        workflow = Workflow(
            workflow_id=resolved_workflow_id,
            request_id=request.request_id,
            correlation_id=request.correlation_id,
        )
        workflow.receive(occurred_at=now)
        workflow.prepare(occurred_at=now)
        workflow.dispatch(occurred_at=now)

        task_id = TaskId(self._id_factory.new_id())
        task = Task(task_id=task_id, workflow_id=resolved_workflow_id, created_at=now)

        task_attempt_id = TaskAttemptId(self._id_factory.new_id())
        attempt = TaskAttempt(
            task_attempt_id=task_attempt_id,
            task_id=task_id,
            attempt_number=1,
            selection=selection,
            task_result_deadline=request.task_result_deadline,
        )

        message_id = MessageId(self._id_factory.new_id())
        payload = build_execute_task_payload(
            message_id=message_id,
            correlation_id=request.correlation_id,
            workflow_id=resolved_workflow_id,
            task_id=task_id,
            task_attempt_id=task_attempt_id,
            orchestrator_component=self._orchestrator_component,
            orchestrator_instance_id=self._orchestrator_instance_id,
            request_id=request.request_id,
            input_text=request.text,
            selection=selection,
            task_result_deadline=request.task_result_deadline,
            created_at=now,
        )
        outbox_record = OrchestratorOutboxRecord(
            message_id=message_id,
            workflow_id=resolved_workflow_id,
            payload=payload,
            created_at=now,
        )

        # Atomic submission transaction (Section 11): all commit or none do.
        self._workflow_repo.save_new(workflow)
        self._task_repo.save(task)
        self._task_attempt_repo.save(attempt)
        self._outbox_repo.enqueue(outbox_record)
        self._audit_repo.append(
            AuditRecord(
                kind="workflow_accepted",
                workflow_id=resolved_workflow_id,
                occurred_at=now,
                actor_id=request.acceptance_actor_id,
                details={"capability": request.capability_name},
            )
        )

        return SubmissionResult(
            disposition=SubmissionDisposition.NEW,
            workflow_id=resolved_workflow_id,
            workflow=workflow,
        )
