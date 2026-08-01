"""Identifier generation port.

The Orchestrator creates lowercase UUIDv7 identifiers for workflow_id,
task_id, task_attempt_id, and message_id (ADR-0004 Section 5). Generation
is injected so tests can supply deterministic values.
"""

from typing import Protocol


class IdentifierFactory(Protocol):
    def new_id(self) -> str:
        """Return a new lowercase UUIDv7 string."""
        ...
