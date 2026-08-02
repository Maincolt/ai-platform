"""Process-neutral UUIDv7 identifier generation."""

import uuid


class Uuid7IdentifierFactory:
    """Satisfy the structurally identical Orchestrator and Agent ID ports."""

    def new_id(self) -> str:
        return str(uuid.uuid7())
