"""Agent-owned recovery records (vertical-slice-01.md Section 13).

These are transport-recovery state owned exclusively by one Agent
deployment: only the Agent itself ever reads or writes them (the
Orchestrator never touches an Agent's completed-receipt or event-outbox
rows directly; it only consumes the resulting Event Bus message). See
ai_platform.shared.outcomes.AgentOutcome for the outcome value shared
across the Agent/Orchestrator boundary.
"""

from dataclasses import dataclass
from datetime import datetime

from ai_platform.shared.identifiers import AgentId, MessageId, TaskAttemptId, WorkflowId


@dataclass(frozen=True, slots=True)
class AgentEventOutboxRecord:
    """One immutable TaskCompleted/TaskFailed publication, keyed by (task-outcomes, workflow_id).

    `capability_name` exists only for structural symmetry with
    `OrchestratorOutboxRecord` (shared outbox persistence code handles both
    uniformly); task-outcomes is never capability-scoped (ADR-0014 Section
    6), so this is always `None` here.
    """

    message_id: MessageId
    workflow_id: WorkflowId
    logical_channel: str
    ordering_key: str
    payload_bytes: bytes
    headers: tuple[tuple[str, bytes], ...]
    creation_sequence: int
    created_at: datetime
    capability_name: str | None = None

    def __post_init__(self) -> None:
        if not self.logical_channel:
            raise ValueError("logical_channel must not be empty")
        if not self.ordering_key:
            raise ValueError("ordering_key must not be empty")
        if not self.payload_bytes:
            raise ValueError("payload_bytes must not be empty")
        if self.creation_sequence < 1:
            raise ValueError("creation_sequence must be positive")


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
    terminal_event_message_id: MessageId
    completed_at: datetime
