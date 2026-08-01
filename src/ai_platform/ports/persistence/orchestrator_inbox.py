"""Orchestrator outcome-inbox repository port (vertical-slice-01.md Section 13).

Key: (environment, logical_consumer_id, validated_message_id).
`logical_consumer_id` is a stable subscription identity, never a process,
consumer-group member, partition assignment, or host.
"""

from typing import Protocol

from ai_platform.orchestrator.domain.recovery import OrchestratorInboxRecord
from ai_platform.shared.identifiers import MessageId


class OrchestratorInboxRepositoryPort(Protocol):
    def get_disposition(
        self, environment: str, logical_consumer_id: str, validated_message_id: MessageId
    ) -> OrchestratorInboxRecord | None: ...

    def record_disposition(self, record: OrchestratorInboxRecord) -> None:
        """Insert or resolve the inbox row in the same transaction as the
        workflow effect it disposes (Section 11, "Result-Consumption
        Transaction")."""
        ...
