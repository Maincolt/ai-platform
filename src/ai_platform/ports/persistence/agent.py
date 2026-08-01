"""Agent completed-receipt and outcome repository ports (Section 13)."""

from typing import Protocol

from ai_platform.orchestrator.domain.identifiers import TaskAttemptId
from ai_platform.orchestrator.domain.recovery import AgentCompletedReceipt, AgentOutcome


class AgentReceiptRepositoryPort(Protocol):
    """The Agent's durable logical inbox (its completed command receipt)."""

    def get_by_attempt(self, task_attempt_id: TaskAttemptId) -> AgentCompletedReceipt | None: ...

    def create_or_resolve(self, receipt: AgentCompletedReceipt) -> AgentCompletedReceipt:
        """Enforce one accepted receipt per task_attempt_id; return the
        resolved (possibly pre-existing) receipt."""
        ...


class AgentOutcomeRepositoryPort(Protocol):
    """The one accepted result for a task_attempt_id."""

    def get_by_attempt(self, task_attempt_id: TaskAttemptId) -> AgentOutcome | None: ...

    def save(self, outcome: AgentOutcome) -> None:
        """Enforce exactly one accepted outcome per task_attempt_id, in the
        same transaction as the completed receipt and event outbox row."""
        ...
