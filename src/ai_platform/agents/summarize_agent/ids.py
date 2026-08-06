"""Identifier generation port, owned locally by the Summarize Agent.

Deliberately duplicated from `ai_platform.agents.test_agent.ids` rather than
imported: the Agent and Orchestrator (and each Agent deployable) are
separate deployables (ADR-0001, ADR-0007 Section 1) and must not depend on
each other's internal modules, only on portable contracts. This file has no
test_agent-specific content, so duplicating it verbatim keeps this module
self-contained without inventing a new shared package for one Protocol.
"""

from typing import Protocol


class IdentifierFactory(Protocol):
    def new_id(self) -> str:
        """Return a new lowercase UUIDv7 string."""
        ...
