"""Nonterminal-workflow recovery query port (Section 15/Phase 3 scope).

Deliberately narrow: only the query the deadline reconciler needs (find
DISPATCHED task attempts whose task_result_deadline has elapsed). Broader
outbox/inbox recovery-query capabilities (not-attempted, unknown,
claimed-expired publication rows) depend on concrete adapter claim
mechanics and are deferred to Phase 6 (see docs/sprint-3/consilium.md,
disagreement 1).
"""

from datetime import datetime
from typing import Protocol

from ai_platform.orchestrator.domain.identifiers import TaskAttemptId, WorkflowId


class NonterminalWorkflowQueryPort(Protocol):
    def find_expired_dispatched_attempts(
        self, *, now: datetime
    ) -> list[tuple[WorkflowId, TaskAttemptId]]:
        """Return (workflow_id, task_attempt_id) pairs for every workflow
        currently DISPATCHED whose task_result_deadline is at or before
        `now`. Implementations must not return a workflow that has already
        reached a terminal state."""
        ...
