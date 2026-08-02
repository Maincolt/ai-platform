"""Atomic task-result-deadline reconciliation."""

from datetime import datetime

from ai_platform.orchestrator.domain.audit import AuditRecord
from ai_platform.ports.persistence.transactions import (
    DeadlinePersistenceDisposition,
    DeadlineTransactionPort,
)
from ai_platform.shared.identifiers import ActorId, WorkflowId

_SYSTEM_ACTOR_ID = ActorId("system:deadline-reconciler")


class DeadlineReconciler:
    def __init__(self, *, transaction: DeadlineTransactionPort, batch_size: int = 100) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self._transaction = transaction
        self._batch_size = batch_size

    async def reconcile(self, *, now: datetime) -> list[WorkflowId]:
        """Fail due workflows through one lock-and-revalidate transaction each."""

        reconciled: list[WorkflowId] = []
        candidates = await self._transaction.find_expired(now=now, limit=self._batch_size)
        for candidate in candidates:
            disposition = await self._transaction.expire(
                candidate,
                now=now,
                audit=AuditRecord(
                    kind="workflow_deadline_expired",
                    workflow_id=candidate.workflow_id,
                    occurred_at=now,
                    actor_id=_SYSTEM_ACTOR_ID,
                    details={"task_attempt_id": str(candidate.task_attempt_id)},
                ),
            )
            if disposition == DeadlinePersistenceDisposition.APPLIED:
                reconciled.append(candidate.workflow_id)
        return reconciled
