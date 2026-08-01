"""Coupled audit record (ADR-0006 "Durable responsibilities" table, ADR-0009).

Audit is mandatory and commits in the same transaction as the business
mutation it accompanies; it is never a best-effort side channel.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from ai_platform.shared.identifiers import ActorId, WorkflowId


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """One immutable, coupled audit entry."""

    kind: str
    workflow_id: WorkflowId
    occurred_at: datetime
    actor_id: ActorId
    details: Mapping[str, str] = field(default_factory=dict[str, str])
