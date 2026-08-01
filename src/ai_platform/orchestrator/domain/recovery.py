"""Recovery-oriented records: outbox, inbox, and Agent receipts/outcomes.

Per vertical-slice-01.md Sections 12-13. These are transport-recovery and
deduplication state, not workflow business state (ADR-0006 "Durable
responsibilities" table).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ai_platform.orchestrator.domain.identifiers import (
    AgentId,
    MessageId,
    TaskAttemptId,
    WorkflowId,
)


class PublicationState(Enum):
    """Mutable publication disposition for one outbox record."""

    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    CLAIMED = "CLAIMED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DEFINITIVELY_NOT_ACCEPTED = "DEFINITIVELY_NOT_ACCEPTED"
    ATTEMPTED_UNKNOWN = "ATTEMPTED_UNKNOWN"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class OrchestratorOutboxRecord:
    """One immutable ExecuteTask publication, keyed by (task-commands, workflow_id)."""

    message_id: MessageId
    workflow_id: WorkflowId
    payload: Mapping[str, object]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AgentEventOutboxRecord:
    """One immutable TaskCompleted/TaskFailed publication, keyed by (task-outcomes, workflow_id)."""

    message_id: MessageId
    workflow_id: WorkflowId
    payload: Mapping[str, object]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class OrchestratorInboxRecord:
    """Orchestrator outcome-inbox key: (environment, logical_consumer_id, validated_message_id)."""

    environment: str
    logical_consumer_id: str
    validated_message_id: MessageId
    disposition: str
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class AgentCompletedReceipt:
    """The Agent's durable logical inbox (Section 13).

    Identity and conflict guards: environment, logical Agent
    handler/deployment identity, task_attempt_id, command message_id, and
    the SHA-256 digest of immutable command bytes.
    """

    environment: str
    agent_deployment_id: AgentId
    task_attempt_id: TaskAttemptId
    command_message_id: MessageId
    command_digest: str


@dataclass(frozen=True, slots=True)
class AgentOutcome:
    """The one accepted result for a task_attempt_id.

    Exactly one of `word_count` (success) or `failure_code`/`summary`
    (failure) must be set.
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
