"""Submission-transaction orchestration (vertical-slice-01.md Sections 6, 11).

Resolves any existing accepted-request mapping first; an equivalent replay
never touches Registry/Agent readiness. Only a genuinely new request selects a
candidate and passes one complete immutable intent to the submission
transaction port.
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
from ai_platform.orchestrator.domain.recovery import OrchestratorOutboxRecord
from ai_platform.orchestrator.domain.task import Task, TaskAttempt
from ai_platform.orchestrator.domain.workflow import Workflow
from ai_platform.ports.persistence.transactions import (
    AcceptedRequestAccessAuditPort,
    AcceptedRequestAccessAuditRecord,
    AcceptedRequestAccessDisposition,
    AcceptedRequestQueryPort,
    AcceptedRequestResolution,
    SubmissionCommitIntent,
    SubmissionTransactionPort,
    WorkflowQueryPort,
)
from ai_platform.shared.identifiers import (
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
from ai_platform.shared.messages import canonical_message_bytes


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
    current_owner_subject_id: OwnerSubjectId
    fingerprint: str
    fingerprint_policy_version: str
    policy_identity: str
    policy_revision: str
    policy_decision: str
    scope_mapping_revision: str
    authorization_evidence: str
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
    OWNER_INTENT_MISMATCH = "OWNER_INTENT_MISMATCH"
    FINGERPRINT_POLICY_UNAVAILABLE = "FINGERPRINT_POLICY_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    disposition: SubmissionDisposition
    workflow_id: WorkflowId | None
    workflow: Workflow | None


class SubmissionOrchestrator:
    def __init__(
        self,
        *,
        accepted_request_query: AcceptedRequestQueryPort,
        request_access_audit: AcceptedRequestAccessAuditPort,
        workflow_query: WorkflowQueryPort,
        submission_transaction: SubmissionTransactionPort,
        candidate_selector: CandidateSelectorPort,
        id_factory: IdentifierFactory,
        orchestrator_component: str = "orchestrator",
        orchestrator_instance_id: str = "orchestrator-instance",
    ) -> None:
        self._accepted_request_query = accepted_request_query
        self._request_access_audit = request_access_audit
        self._workflow_query = workflow_query
        self._submission_transaction = submission_transaction
        self._candidate_selector = candidate_selector
        self._id_factory = id_factory
        self._orchestrator_component = orchestrator_component
        self._orchestrator_instance_id = orchestrator_instance_id

    async def submit(self, request: SubmissionRequest, *, now: datetime) -> SubmissionResult:
        key = AcceptedRequestKey(
            environment=request.environment,
            operation=request.operation,
            idempotency_scope_id=request.idempotency_scope_id,
            request_id=request.request_id,
        )
        evidence = AcceptanceEvidence(
            acceptance_actor_id=request.acceptance_actor_id,
            accepted_owner_subject_id=request.accepted_owner_subject_id,
            current_owner_subject_id=request.current_owner_subject_id,
            fingerprint=request.fingerprint,
            fingerprint_policy_version=request.fingerprint_policy_version,
            policy_identity=request.policy_identity,
            policy_revision=request.policy_revision,
            policy_decision=request.policy_decision,
            scope_mapping_revision=request.scope_mapping_revision,
            authorization_evidence=request.authorization_evidence,
            accepted_at=now,
        )

        existing = await self._accepted_request_query.resolve(key)
        if existing is not None:
            return await self._classify_existing(request, existing, now=now)

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
            concurrent = await self._accepted_request_query.resolve(key)
            if concurrent is not None:
                return await self._classify_existing(request, concurrent, now=now)
            return SubmissionResult(
                disposition=SubmissionDisposition.NO_ELIGIBLE_AGENT,
                workflow_id=None,
                workflow=None,
            )
        except CandidateSelectionConfigurationError:
            concurrent = await self._accepted_request_query.resolve(key)
            if concurrent is not None:
                return await self._classify_existing(request, concurrent, now=now)
            return SubmissionResult(
                disposition=SubmissionDisposition.CONFIGURATION_ERROR,
                workflow_id=None,
                workflow=None,
            )

        workflow_id = WorkflowId(self._id_factory.new_id())
        workflow = Workflow(
            workflow_id=workflow_id,
            request_id=request.request_id,
            correlation_id=request.correlation_id,
        )
        workflow.receive(occurred_at=now)
        workflow.prepare(occurred_at=now)
        workflow.dispatch(occurred_at=now)

        task_id = TaskId(self._id_factory.new_id())
        task = Task(task_id=task_id, workflow_id=workflow_id, created_at=now)

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
            workflow_id=workflow_id,
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
            workflow_id=workflow_id,
            logical_channel="task-commands",
            ordering_key=str(workflow_id),
            payload_bytes=canonical_message_bytes(payload),
            headers=(),
            creation_sequence=1,
            created_at=now,
            capability_name=selection.capability_name,
        )

        audit = AuditRecord(
            kind="workflow_accepted",
            workflow_id=workflow_id,
            occurred_at=now,
            actor_id=request.acceptance_actor_id,
            details={
                "capability": request.capability_name,
                "fingerprint_policy_version": request.fingerprint_policy_version,
                "policy_identity": request.policy_identity,
                "policy_revision": request.policy_revision,
                "policy_decision": request.policy_decision,
                "scope_mapping_revision": request.scope_mapping_revision,
                "registry_revision": selection.registry_revision,
                "selection_policy_version": selection.selection_policy_version,
                "selected_agent_id": str(selection.agent_id),
            },
        )
        committed = await self._submission_transaction.commit_submission(
            SubmissionCommitIntent(
                key=key,
                evidence=evidence,
                workflow=workflow,
                task=task,
                task_attempt=attempt,
                command_outbox=outbox_record,
                audit=audit,
            )
        )

        if not committed.created:
            return await self._classify_existing(
                request, committed.resolution, committed.workflow, now=now
            )

        return SubmissionResult(
            disposition=SubmissionDisposition.NEW,
            workflow_id=committed.resolution.workflow_id,
            workflow=committed.workflow,
        )

    async def _classify_existing(
        self,
        request: SubmissionRequest,
        resolution: AcceptedRequestResolution,
        workflow: Workflow | None = None,
        *,
        now: datetime,
    ) -> SubmissionResult:
        evidence = resolution.evidence
        if evidence.accepted_owner_subject_id != request.current_owner_subject_id:
            await self._record_request_access(
                request,
                resolution,
                AcceptedRequestAccessDisposition.OWNER_INTENT_MISMATCH,
                now=now,
            )
            return SubmissionResult(
                disposition=SubmissionDisposition.OWNER_INTENT_MISMATCH,
                workflow_id=None,
                workflow=None,
            )
        if evidence.current_owner_subject_id != request.current_owner_subject_id:
            await self._record_request_access(
                request,
                resolution,
                AcceptedRequestAccessDisposition.OWNER_INTENT_MISMATCH,
                now=now,
            )
            return SubmissionResult(
                disposition=SubmissionDisposition.OWNER_INTENT_MISMATCH,
                workflow_id=None,
                workflow=None,
            )
        if evidence.fingerprint_policy_version != request.fingerprint_policy_version:
            return SubmissionResult(
                disposition=SubmissionDisposition.FINGERPRINT_POLICY_UNAVAILABLE,
                workflow_id=None,
                workflow=None,
            )
        comparison = compare_fingerprint(evidence.fingerprint, request.fingerprint)
        if comparison == FingerprintComparison.FINGERPRINT_CONFLICT:
            await self._record_request_access(
                request,
                resolution,
                AcceptedRequestAccessDisposition.FINGERPRINT_CONFLICT_AUTHORIZED,
                now=now,
            )
            return SubmissionResult(
                disposition=SubmissionDisposition.FINGERPRINT_CONFLICT,
                workflow_id=resolution.workflow_id,
                workflow=None,
            )
        await self._record_request_access(
            request,
            resolution,
            AcceptedRequestAccessDisposition.EQUIVALENT_REPLAY_AUTHORIZED,
            now=now,
        )
        if workflow is None:
            workflow = await self._workflow_query.get(resolution.workflow_id)
        return SubmissionResult(
            disposition=SubmissionDisposition.EQUIVALENT_REPLAY,
            workflow_id=resolution.workflow_id,
            workflow=workflow,
        )

    async def _record_request_access(
        self,
        request: SubmissionRequest,
        resolution: AcceptedRequestResolution,
        disposition: AcceptedRequestAccessDisposition,
        *,
        now: datetime,
    ) -> None:
        await self._request_access_audit.record_request_access(
            AcceptedRequestAccessAuditRecord(
                key=resolution.key,
                workflow_id=resolution.workflow_id,
                current_actor_id=request.acceptance_actor_id,
                resolved_owner_subject_id=request.current_owner_subject_id,
                effective_correlation_id=request.correlation_id,
                policy_identity=request.policy_identity,
                policy_revision=request.policy_revision,
                policy_decision=request.policy_decision,
                scope_mapping_revision=request.scope_mapping_revision,
                authorization_evidence=request.authorization_evidence,
                disposition=disposition,
                occurred_at=now,
            )
        )
