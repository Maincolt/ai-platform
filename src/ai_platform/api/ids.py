"""Concrete identifier factory using the standard library's uuid7 generator.

Satisfies both `ai_platform.orchestrator.application.ids.IdentifierFactory`
and `ai_platform.agents.test_agent.ids.IdentifierFactory` (structurally
identical single-method Protocols).
"""

import uuid


class Uuid7IdentifierFactory:
    def new_id(self) -> str:
        return str(uuid.uuid7())
