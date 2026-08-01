"""Deadline reconciliation (vertical-slice-01.md Section 9, last transition
row, and Section 15).

Uses `NonterminalWorkflowQueryPort` to find DISPATCHED workflows whose
task_result_deadline has elapsed. The Workflow aggregate's terminal-
exclusivity guarantee (Sprint 2) is the race-safety net against a
concurrent genuine TaskCompleted/TaskFailed: this reconciler does not
implement its own locking.
"""

from datetime import datetime

from ai_platform.orchestrator.domain.audit import AuditRecord
from ai_platform.orchestrator.domain.errors import TerminalWorkflowError
from ai_platform.orchestrator.domain.results import WorkflowFailure
from ai_platform.ports.persistence.audit import AuditRepositoryPort
from ai_platform.ports.persistence.recovery import NonterminalWorkflowQueryPort
from ai_platform.ports.persistence.workflow import WorkflowRepositoryPort
from ai_platform.shared.identifiers import ActorId, WorkflowId

_SYSTEM_ACTOR_ID = ActorId("system:deadline-reconciler")
_DEADLINE_FAILURE_CODE = "TASK_RESULT_DEADLINE_EXCEEDED"


class DeadlineReconciler:
    def __init__(
        self,
        *,
        recovery_query: NonterminalWorkflowQueryPort,
        workflow_repo: WorkflowRepositoryPort,
        audit_repo: AuditRepositoryPort,
    ) -> None:
        self._recovery_query = recovery_query
        self._workflow_repo = workflow_repo
        self._audit_repo = audit_repo

    def reconcile(self, *, now: datetime) -> list[WorkflowId]:
        """Fail every still-DISPATCHED workflow whose deadline has elapsed.

        Returns the workflow_ids this call actually transitioned to FAILED.
        A workflow already resolved by a genuine outcome (concurrently, or
        because the query result is stale) is silently skipped rather than
        treated as an error.
        """
        reconciled: list[WorkflowId] = []
        for workflow_id, task_attempt_id in self._recovery_query.find_expired_dispatched_attempts(
            now=now
        ):
            workflow = self._workflow_repo.get_by_id(workflow_id)
            if workflow is None or workflow.is_terminal:
                continue

            expected_revision = workflow.revision
            try:
                workflow.fail(
                    WorkflowFailure(
                        code=_DEADLINE_FAILURE_CODE,
                        detail="No terminal outcome was received before the task result deadline.",
                    ),
                    occurred_at=now,
                    cause="deadline_expired",
                )
            except TerminalWorkflowError:
                # Raced and lost to a genuine outcome between the query and now.
                continue

            self._workflow_repo.save_transition(workflow, expected_revision=expected_revision)
            self._audit_repo.append(
                AuditRecord(
                    kind="workflow_deadline_expired",
                    workflow_id=workflow_id,
                    occurred_at=now,
                    actor_id=_SYSTEM_ACTOR_ID,
                    details={"task_attempt_id": str(task_attempt_id)},
                )
            )
            reconciled.append(workflow_id)
        return reconciled
