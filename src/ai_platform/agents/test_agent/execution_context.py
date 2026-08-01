"""Technology-neutral execution context for one bounded command execution
(vertical-slice-01.md Section 14, step 4).
"""

from dataclasses import dataclass
from datetime import datetime

from ai_platform.shared.identifiers import (
    CorrelationId,
    MessageId,
    TaskAttemptId,
    TaskId,
    WorkflowId,
)


@dataclass(frozen=True, slots=True)
class ExecuteTaskContext:
    """Everything one bounded execution needs, already validated by the
    transport/contract boundary (Phase 6) before this context is built."""

    workflow_id: WorkflowId
    task_id: TaskId
    task_attempt_id: TaskAttemptId
    correlation_id: CorrelationId
    command_message_id: MessageId
    command_digest: str
    input_text: str
    capability_name: str
    capability_version: str
    task_result_deadline: datetime
