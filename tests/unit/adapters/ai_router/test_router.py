"""Fallback, retry-budget, and deadline-enforcement tests for `FallbackAIRouter`.

`_FakeProviderAdapter` is an in-process `ProviderAdapter`; no test here
touches a real provider SDK or network. Async tests follow this
repository's existing `asyncio.run(...)` convention.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from ai_platform.adapters.ai_router.router import (
    AIRouterConfigurationError,
    FallbackAIRouter,
)
from ai_platform.ports.ai_router import (
    AICompletionFailureCode,
    AICompletionRequest,
    AICompletionResult,
    AICompletionUsage,
)


class _FakeProviderAdapter:
    def __init__(self, provider_name: str, result: AICompletionResult) -> None:
        self.provider_name = provider_name
        self._result = result
        self.call_count = 0

    async def complete(self, request: AICompletionRequest) -> AICompletionResult:
        self.call_count += 1
        return self._result


def _request(deadline: datetime | None = None) -> AICompletionRequest:
    return AICompletionRequest(
        prompt="summarize this text",
        max_output_tokens=256,
        idempotency_key="attempt-1",
        deadline=deadline if deadline is not None else datetime.now(UTC) + timedelta(seconds=30),
    )


def _usage(provider: str) -> AICompletionUsage:
    return AICompletionUsage(
        provider=provider, model="model-x", input_tokens=1, output_tokens=1, latency_seconds=0.1
    )


def _success(provider: str) -> AICompletionResult:
    return AICompletionResult(output_text=f"summary from {provider}", usage=_usage(provider))


def _failure(code: AICompletionFailureCode, provider: str | None = None) -> AICompletionResult:
    usage = _usage(provider) if provider is not None else None
    return AICompletionResult(failure_code=code, usage=usage)


def test_empty_provider_list_is_rejected() -> None:
    with pytest.raises(AIRouterConfigurationError):
        FallbackAIRouter([])


def test_non_positive_attempt_budget_is_rejected() -> None:
    primary = _FakeProviderAdapter("anthropic", _success("anthropic"))
    with pytest.raises(AIRouterConfigurationError):
        FallbackAIRouter([primary], maximum_total_attempts=0)


def test_successful_first_try_does_not_fall_through() -> None:
    primary = _FakeProviderAdapter("anthropic", _success("anthropic"))
    secondary = _FakeProviderAdapter("openai", _success("openai"))
    router = FallbackAIRouter([primary, secondary])

    result = asyncio.run(router.complete(_request()))

    assert result.output_text == "summary from anthropic"
    assert primary.call_count == 1
    assert secondary.call_count == 0


def test_retryable_failure_falls_through_to_next_provider() -> None:
    primary = _FakeProviderAdapter(
        "anthropic", _failure(AICompletionFailureCode.PROVIDER_RATE_LIMITED, "anthropic")
    )
    secondary = _FakeProviderAdapter("openai", _success("openai"))
    router = FallbackAIRouter([primary, secondary])

    result = asyncio.run(router.complete(_request()))

    assert result.output_text == "summary from openai"
    assert primary.call_count == 1
    assert secondary.call_count == 1


@pytest.mark.parametrize(
    "code",
    [
        AICompletionFailureCode.PROVIDER_UNAVAILABLE,
        AICompletionFailureCode.PROVIDER_RATE_LIMITED,
        AICompletionFailureCode.PROVIDER_TIMEOUT,
    ],
)
def test_every_retryable_code_falls_through(code: AICompletionFailureCode) -> None:
    primary = _FakeProviderAdapter("anthropic", _failure(code, "anthropic"))
    secondary = _FakeProviderAdapter("openai", _success("openai"))
    router = FallbackAIRouter([primary, secondary])

    result = asyncio.run(router.complete(_request()))

    assert result.output_text == "summary from openai"


@pytest.mark.parametrize(
    "code",
    [
        AICompletionFailureCode.PROVIDER_REJECTED_INPUT,
        AICompletionFailureCode.PROVIDER_REJECTED_OUTPUT,
    ],
)
def test_non_retryable_failure_does_not_fall_through(code: AICompletionFailureCode) -> None:
    primary = _FakeProviderAdapter("anthropic", _failure(code, "anthropic"))
    secondary = _FakeProviderAdapter("openai", _success("openai"))
    router = FallbackAIRouter([primary, secondary])

    result = asyncio.run(router.complete(_request()))

    assert result.failure_code is code
    assert primary.call_count == 1
    assert secondary.call_count == 0


def test_exhausting_the_bounded_budget_produces_all_providers_exhausted() -> None:
    first = _FakeProviderAdapter("a", _failure(AICompletionFailureCode.PROVIDER_UNAVAILABLE, "a"))
    second = _FakeProviderAdapter("b", _failure(AICompletionFailureCode.PROVIDER_RATE_LIMITED, "b"))
    third = _FakeProviderAdapter("c", _success("c"))
    router = FallbackAIRouter([first, second, third], maximum_total_attempts=2)

    result = asyncio.run(router.complete(_request()))

    assert result.failure_code is AICompletionFailureCode.ALL_PROVIDERS_EXHAUSTED
    assert first.call_count == 1
    assert second.call_count == 1
    assert third.call_count == 0


def test_exhaustion_result_carries_usage_from_the_last_real_attempt() -> None:
    first = _FakeProviderAdapter("a", _failure(AICompletionFailureCode.PROVIDER_UNAVAILABLE, "a"))
    router = FallbackAIRouter([first], maximum_total_attempts=1)

    result = asyncio.run(router.complete(_request()))

    assert result.failure_code is AICompletionFailureCode.ALL_PROVIDERS_EXHAUSTED
    assert result.usage is not None
    assert result.usage.provider == "a"


def test_deadline_already_passed_bounds_the_whole_sequence() -> None:
    first = _FakeProviderAdapter("a", _success("a"))
    second = _FakeProviderAdapter("b", _success("b"))
    router = FallbackAIRouter([first, second])
    past_deadline_request = _request(deadline=datetime.now(UTC) - timedelta(seconds=1))

    result = asyncio.run(router.complete(past_deadline_request))

    assert result.failure_code is AICompletionFailureCode.ALL_PROVIDERS_EXHAUSTED
    assert first.call_count == 0
    assert second.call_count == 0


def test_deadline_exceeded_between_attempts_stops_further_fallback() -> None:
    deadline = datetime.now(UTC) + timedelta(milliseconds=50)

    class _SlowThenPastDeadlineAdapter:
        provider_name = "a"

        async def complete(self, request: AICompletionRequest) -> AICompletionResult:
            await asyncio.sleep(0.1)
            return _failure(AICompletionFailureCode.PROVIDER_UNAVAILABLE, "a")

    first = _SlowThenPastDeadlineAdapter()
    second = _FakeProviderAdapter("b", _success("b"))
    router = FallbackAIRouter([first, second])

    result = asyncio.run(router.complete(_request(deadline=deadline)))

    assert result.failure_code is AICompletionFailureCode.ALL_PROVIDERS_EXHAUSTED
    assert second.call_count == 0
