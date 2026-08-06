"""Configuration-driven ordered fallback across `ProviderAdapter`s (ADR-0014 Section 2).

Implements `AIRouterPort` by composing an ordered, capability-scoped list
of `ProviderAdapter`s. Routing is deterministic and configuration-driven,
never a scoring model: the first entry is tried, a retryable failure
falls through to the next entry, bounded by a small fixed total-attempt
budget across the whole list (not per-provider unbounded retry). A
non-retryable failure is returned immediately. The request's own
`deadline` bounds the whole fallback sequence, not just one attempt.
"""

from ai_platform.adapters.ai_router._deadlines import is_past_deadline
from ai_platform.adapters.ai_router.provider import ProviderAdapter
from ai_platform.ports.ai_router import (
    RETRYABLE_FAILURE_CODES,
    AICompletionFailureCode,
    AICompletionRequest,
    AICompletionResult,
)

DEFAULT_MAXIMUM_TOTAL_ATTEMPTS = 3


class AIRouterConfigurationError(ValueError):
    """Stable, content-free routing configuration failure."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


class FallbackAIRouter:
    """`AIRouterPort` implementation trying providers in a fixed, configured order."""

    def __init__(
        self,
        providers: list[ProviderAdapter],
        *,
        maximum_total_attempts: int = DEFAULT_MAXIMUM_TOTAL_ATTEMPTS,
    ) -> None:
        if not providers:
            raise AIRouterConfigurationError("EMPTY_PROVIDER_LIST")
        if maximum_total_attempts < 1:
            raise AIRouterConfigurationError("NON_POSITIVE_MAXIMUM_TOTAL_ATTEMPTS")
        self._providers = tuple(providers)
        self._maximum_total_attempts = maximum_total_attempts

    async def complete(self, request: AICompletionRequest) -> AICompletionResult:
        last_result: AICompletionResult | None = None

        for attempt_index, provider in enumerate(self._providers):
            if attempt_index >= self._maximum_total_attempts:
                break
            if is_past_deadline(request.deadline):
                break

            result = await provider.complete(request)

            if result.failure_code is None:
                return result
            if result.failure_code not in RETRYABLE_FAILURE_CODES:
                return result

            last_result = result

        return AICompletionResult(
            failure_code=AICompletionFailureCode.ALL_PROVIDERS_EXHAUSTED,
            usage=last_result.usage if last_result is not None else None,
        )


__all__ = ["DEFAULT_MAXIMUM_TOTAL_ATTEMPTS", "AIRouterConfigurationError", "FallbackAIRouter"]
