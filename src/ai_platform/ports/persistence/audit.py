"""Audit repository port (ADR-0006 durable-responsibilities table, ADR-0009)."""

from typing import Protocol

from ai_platform.orchestrator.domain.audit import AuditRecord


class AuditRepositoryPort(Protocol):
    def append(self, record: AuditRecord) -> None:
        """Store the audit record in the same transaction as the business
        mutation it accompanies (coupled audit; ADR-0009)."""
        ...
