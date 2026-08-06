"""The per-provider adapter boundary composed by the routing engine.

Distinct from `AIRouterPort`: a `ProviderAdapter` speaks for exactly one
(provider, model) pair. `router.py` composes an ordered list of these
behind the single `AIRouterPort` the rest of the platform depends on
(ADR-0014 Section 2).
"""

from typing import Protocol

from ai_platform.ports.ai_router import AICompletionRequest, AICompletionResult


class ProviderAdapter(Protocol):
    """One provider SDK, wrapped to speak only in shared port types."""

    provider_name: str

    async def complete(self, request: AICompletionRequest) -> AICompletionResult:
        """Never raise: translate every provider failure into a classified result."""
        ...


__all__ = ["ProviderAdapter"]
