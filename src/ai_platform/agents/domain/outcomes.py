"""Agent-owned recovery records (vertical-slice-01.md Section 13).

These are transport-recovery state owned exclusively by one Agent
deployment: only the Agent itself ever reads or writes them (the
Orchestrator never touches an Agent's completed-receipt or event-outbox
rows directly; it only consumes the resulting Event Bus message). See
ai_platform.shared.outcomes.AgentOutcome for the outcome value shared
across the Agent/Orchestrator boundary.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from ai_platform.shared.identifiers import AgentId, MessageId, TaskAttemptId, WorkflowId


@dataclass(frozen=True, slots=True)
class AgentEventOutboxRecord:
    """One immutable TaskCompleted/TaskFailed publication, keyed by (task-outcomes, workflow_id)."""

    message_id: MessageId
    workflow_id: WorkflowId
    payload: Mapping[str, object]
    created_at: datetime


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
