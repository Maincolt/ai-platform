"""Outbox repository ports (vertical-slice-01.md Section 12).

The Orchestrator command outbox and the Agent event outbox share this
capability shape: enqueue within the owning domain transaction, then claim,
publish, and mark disposition as separate short transactions (Section 11,
"Publication-State Transactions").
"""

from typing import Protocol

from ai_platform.orchestrator.domain.identifiers import MessageId, WorkflowId
from ai_platform.orchestrator.domain.recovery import (
    AgentEventOutboxRecord,
    OrchestratorOutboxRecord,
    PublicationState,
)


class OrchestratorOutboxRepositoryPort(Protocol):
    def enqueue(self, record: OrchestratorOutboxRecord) -> None:
        """Store immutable ExecuteTask bytes in the submission transaction."""
        ...

    def claim_next(
        self, workflow_id: WorkflowId, *, fencing_token: str
    ) -> OrchestratorOutboxRecord | None:
        """Claim the earliest eligible record for (task-commands, workflow_id)
        using a short, expiring, fenced token. Returns None if nothing is
        claimable."""
        ...

    def mark_publication_state(
        self, message_id: MessageId, state: PublicationState, *, fencing_token: str
    ) -> None:
        """Record acknowledged, definitively-not-accepted, unknown, or failed
        state for a previously claimed record. Must reject a stale fencing
        token."""
        ...


class AgentEventOutboxRepositoryPort(Protocol):
    def enqueue(self, record: AgentEventOutboxRecord) -> None:
        """Store immutable TaskCompleted/TaskFailed bytes in the Agent's
        outcome transaction."""
        ...

    def claim_next(
        self, workflow_id: WorkflowId, *, fencing_token: str
    ) -> AgentEventOutboxRecord | None:
        """Claim the earliest eligible record for (task-outcomes, workflow_id)
        using a short, expiring, fenced token. Returns None if nothing is
        claimable."""
        ...

    def mark_publication_state(
        self, message_id: MessageId, state: PublicationState, *, fencing_token: str
    ) -> None:
        """Record acknowledged, definitively-not-accepted, unknown, or failed
        state for a previously claimed record. Must reject a stale fencing
        token."""
        ...
