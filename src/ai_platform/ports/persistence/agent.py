"""Agent completed-receipt and outcome repository ports (Section 13)."""

from typing import Protocol

from ai_platform.agents.domain.outcomes import AgentCompletedReceipt
from ai_platform.shared.identifiers import TaskAttemptId
from ai_platform.shared.outcomes import AgentOutcome


class AgentReceiptRepositoryPort(Protocol):
    """The Agent's durable logical inbox (its completed command receipt)."""

    def get_by_attempt(self, task_attempt_id: TaskAttemptId) -> AgentCompletedReceipt | None: ...

    def create_or_resolve(
        self, receipt: AgentCompletedReceipt
    ) -> tuple[AgentCompletedReceipt, bool]:
        """Enforce one accepted receipt per task_attempt_id.

        Returns `(resolved_receipt, is_new)`. `is_new` is required rather
        than inferring creation from value equality: two independently
        constructed receipts for the same real command are equal by value
        even when a concurrent writer won the race to commit first, so
        callers cannot otherwise distinguish "I created it" from "someone
        else already had created an identical one" (see
        docs/sprint-4/consilium.md).
        """
        ...


class AgentOutcomeRepositoryPort(Protocol):
    """The one accepted result for a task_attempt_id."""

    def get_by_attempt(self, task_attempt_id: TaskAttemptId) -> AgentOutcome | None: ...

    def save(self, outcome: AgentOutcome) -> None:
        """Enforce exactly one accepted outcome per task_attempt_id, in the
        same transaction as the completed receipt and event outbox row."""
        ...
