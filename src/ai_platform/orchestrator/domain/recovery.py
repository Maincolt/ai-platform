"""Orchestrator-owned recovery records: outbox and inbox.

Per vertical-slice-01.md Sections 12-13. These are transport-recovery and
deduplication state, not workflow business state (ADR-0006 "Durable
responsibilities" table). Agent-owned equivalents
(AgentCompletedReceipt, AgentOutcome, AgentEventOutboxRecord) live under
ai_platform.agents.domain.outcomes; the shared PublicationState enum
lives under ai_platform.shared.recovery.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from ai_platform.shared.identifiers import MessageId, WorkflowId


@dataclass(frozen=True, slots=True)
class OrchestratorOutboxRecord:
    """One immutable ExecuteTask publication, keyed by (task-commands, workflow_id)."""

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
