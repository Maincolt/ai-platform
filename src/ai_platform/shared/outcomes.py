"""The outcome of one task attempt: a shared contract-level value object.

Both the Agent (which persists it via AgentOutcomeRepositoryPort) and the
Orchestrator (whose TerminalEventProcessor receives the deserialized
TaskCompleted/TaskFailed event payload in this shape) depend on this type.
It is deliberately placed under shared/, not under either side's domain
package, since it crosses the Agent/Orchestrator boundary by design
(vertical-slice-01.md Section 10-11).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from ai_platform.shared.identifiers import TaskAttemptId


@dataclass(frozen=True, slots=True)
class AgentOutcome:
    """The one accepted result for a task_attempt_id.

    `result_data` is a capability-owned, JSON-compatible payload (e.g.
    `{"word_count": 9}` for `text.word-count`, `{"summary": "..."}` for
    `text.summarize`) -- see ADR-0015. Exactly one of `result_data`
    (success) or `failure_code` (failure) must be set; `summary` is an
    optional, additional detail on failure only (it is not itself part of
    the enforced exclusivity invariant).
    """

    task_attempt_id: TaskAttemptId
    completed_at: datetime
    result_data: Mapping[str, object] | None = None
    failure_code: str | None = None
    summary: str | None = None

    def __post_init__(self) -> None:
        is_success = self.result_data is not None
        is_failure = self.failure_code is not None
        if is_success == is_failure:
            raise ValueError(
                "AgentOutcome must set exactly one of result_data (success) or "
                "failure_code (failure)"
            )
        if is_success and not self.result_data:
            raise ValueError("result_data must not be empty when set")
