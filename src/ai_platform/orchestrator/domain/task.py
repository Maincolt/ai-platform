"""Task and task attempt (vertical-slice-01.md Sections 2, 9, 10).

This slice has exactly one task_id, one task_attempt_id, and
attempt_number == 1 per workflow (Section 2). It does not implement an
Orchestrator application retry.
"""

from dataclasses import dataclass
from datetime import datetime

from ai_platform.orchestrator.domain.identifiers import TaskAttemptId, TaskId, WorkflowId
from ai_platform.orchestrator.domain.selection import SelectionIntent


@dataclass(frozen=True, slots=True)
class Task:
    """Identifies the logical task across application attempts."""

    task_id: TaskId
    workflow_id: WorkflowId
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TaskAttempt:
    """One business execution attempt; also the Agent idempotency key."""

    task_attempt_id: TaskAttemptId
    task_id: TaskId
    attempt_number: int
    selection: SelectionIntent
    task_result_deadline: datetime

    def __post_init__(self) -> None:
        if self.attempt_number != 1:
            raise ValueError(
                "This slice has exactly one attempt per workflow (Section 2); "
                f"got attempt_number={self.attempt_number}"
            )
