"""Task and task-attempt repository ports."""

from typing import Protocol

from ai_platform.orchestrator.domain.identifiers import TaskAttemptId, TaskId
from ai_platform.orchestrator.domain.task import Task, TaskAttempt


class TaskRepositoryPort(Protocol):
    def get_by_id(self, task_id: TaskId) -> Task | None: ...

    def save(self, task: Task) -> None:
        """Store the task in the same submission transaction as the workflow."""
        ...


class TaskAttemptRepositoryPort(Protocol):
    def get_by_id(self, task_attempt_id: TaskAttemptId) -> TaskAttempt | None: ...

    def save(self, attempt: TaskAttempt) -> None:
        """Store the attempt in the same submission transaction as the workflow."""
        ...
