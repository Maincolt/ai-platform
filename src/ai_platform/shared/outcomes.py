"""The outcome of one task attempt: a shared contract-level value object.

Both the Agent (which persists it via AgentOutcomeRepositoryPort) and the
Orchestrator (whose TerminalEventProcessor receives the deserialized
TaskCompleted/TaskFailed event payload in this shape) depend on this type.
It is deliberately placed under shared/, not under either side's domain
package, since it crosses the Agent/Orchestrator boundary by design
(vertical-slice-01.md Section 10-11).
"""

from dataclasses import dataclass
from datetime import datetime

from ai_platform.shared.identifiers import TaskAttemptId


@dataclass(frozen=True, slots=True)
class AgentOutcome:
    """The one accepted result for a task_attempt_id.

    Exactly one of `word_count` (success) or `failure_code` (failure) must
    be set; `summary` is an optional, additional detail on failure only
    (it is not itself part of the enforced exclusivity invariant).
    """

    task_attempt_id: TaskAttemptId
    completed_at: datetime
    word_count: int | None = None
    failure_code: str | None = None
    summary: str | None = None

    def __post_init__(self) -> None:
        is_success = self.word_count is not None
        is_failure = self.failure_code is not None
        if is_success == is_failure:
            raise ValueError(
                "AgentOutcome must set exactly one of word_count (success) or "
                "failure_code (failure)"
            )
