"""Identifier generation port, owned locally by the Test Agent.

Deliberately not shared with ai_platform.orchestrator.application.ids:
the Agent and Orchestrator are separate deployables (ADR-0001, ADR-0007
Section 1) and must not depend on each other's internal modules, only on
portable contracts.
"""

from typing import Protocol


class IdentifierFactory(Protocol):
    def new_id(self) -> str:
        """Return a new lowercase UUIDv7 string."""
        ...
