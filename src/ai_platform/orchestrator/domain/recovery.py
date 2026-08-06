"""Orchestrator-owned recovery records: outbox and inbox.

Per vertical-slice-01.md Sections 12-13. These are transport-recovery and
deduplication state, not workflow business state (ADR-0006 "Durable
responsibilities" table). Agent-owned equivalents
(AgentCompletedReceipt, AgentOutcome, AgentEventOutboxRecord) live under
ai_platform.agents.domain.outcomes; the shared PublicationState enum
lives under ai_platform.shared.recovery.
"""

from dataclasses import dataclass
from datetime import datetime

from ai_platform.shared.identifiers import MessageId, TaskAttemptId, WorkflowId


@dataclass(frozen=True, slots=True)
class OrchestratorOutboxRecord:
    """One immutable ExecuteTask publication, keyed by (task-commands, workflow_id).

    `capability_name` is explicit routing metadata (ADR-0014 Section 6): the
    physical task-commands topic is capability-scoped, so the publisher
    needs this alongside the opaque `payload_bytes` rather than parsing the
    immutable bytes to discover it. `None` only for logical channels that
    are not capability-scoped (task-outcomes has none today).
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
class OrchestratorInboxRecord:
    """Orchestrator outcome-inbox key: (environment, logical_consumer_id, validated_message_id)."""

    environment: str
    logical_consumer_id: str
    validated_message_id: MessageId
    immutable_message_digest: str
    workflow_id: WorkflowId
    task_attempt_id: TaskAttemptId
    disposition: str
    recorded_at: datetime
