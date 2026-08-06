"""SDK-free conformance tests for the Anthropic provider adapter.

No test in this module makes a real network call: `AnthropicProviderAdapter`
is constructed with a fake, in-process client whose `messages.create` either
returns a locally built `anthropic.types.Message` or raises a locally built
`anthropic.AnthropicError` subclass. Real broker/provider round trips remain
out of scope for this adapter's unit tests. Async tests follow this
repository's existing `asyncio.run(...)` convention (no `pytest-asyncio`
dependency).
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast

import anthropic
import anthropic.types as anthropic_types
import httpx
import pytest

from ai_platform.adapters.ai_router.anthropic_adapter import (
    AnthropicCredentialError,
    AnthropicProviderAdapter,
    AnthropicProviderConfig,
)
from ai_platform.ports.ai_router import AICompletionFailureCode, AICompletionRequest


class _FakeMessages:
    def __init__(self, outcome: anthropic_types.Message | Exception) -> None:
        self._outcome = outcome
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> anthropic_types.Message:
        self.calls.append(kwargs)
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class _FakeAnthropicClient:
    def __init__(self, outcome: anthropic_types.Message | Exception) -> None:
        self.messages = _FakeMessages(outcome)


def _request() -> AICompletionRequest:
    return AICompletionRequest(
        prompt="summarize this text",
        max_output_tokens=256,
        idempotency_key="attempt-1",
        deadline=datetime.now(UTC) + timedelta(seconds=30),
    )


def _config() -> AnthropicProviderConfig:
    return AnthropicProviderConfig(api_key="sk-ant-super-secret-value", model="claude-haiku-4-5")


def _message(text: str = "a concise summary") -> anthropic_types.Message:
    return anthropic_types.Message(
        id="msg_1",
        content=[anthropic_types.TextBlock(type="text", text=text)],
        model="claude-haiku-4-5",
        role="assistant",
        stop_reason="end_turn",
        stop_sequence=None,
        type="message",
        usage=anthropic_types.Usage(input_tokens=12, output_tokens=6),
    )


def _httpx_response(status_code: int) -> httpx.Response:
    return httpx.Response(
        status_code, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    )


def _httpx_request() -> httpx.Request:
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _adapter(outcome: anthropic_types.Message | Exception) -> AnthropicProviderAdapter:
    fake_client = _FakeAnthropicClient(outcome)
    return AnthropicProviderAdapter(_config(), client=cast(anthropic.AsyncAnthropic, fake_client))


def test_successful_completion_normalizes_output_and_usage() -> None:
    adapter = _adapter(_message("a concise summary"))

    result = asyncio.run(adapter.complete(_request()))

    assert result.output_text == "a concise summary"
    assert result.usage is not None
    assert result.usage.provider == "anthropic"
    assert result.usage.model == "claude-haiku-4-5"
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 6
    assert result.usage.latency_seconds >= 0


def test_successful_completion_sends_idempotency_key() -> None:
    fake_client = _FakeAnthropicClient(_message())
    adapter = AnthropicProviderAdapter(
        _config(), client=cast(anthropic.AsyncAnthropic, fake_client)
    )

    asyncio.run(adapter.complete(_request()))

    call = fake_client.messages.calls[0]
    headers = cast(dict[str, str], call["extra_headers"])
    assert headers["idempotency-key"] == "attempt-1"


def test_empty_output_is_classified_as_rejected_output() -> None:
    adapter = _adapter(_message(""))

    result = asyncio.run(adapter.complete(_request()))

    assert result.failure_code is AICompletionFailureCode.PROVIDER_REJECTED_OUTPUT
    assert result.usage is not None


def test_timeout_is_classified_as_provider_timeout() -> None:
    adapter = _adapter(anthropic.APITimeoutError(request=_httpx_request()))

    result = asyncio.run(adapter.complete(_request()))

    assert result.failure_code is AICompletionFailureCode.PROVIDER_TIMEOUT


def test_rate_limit_is_classified_as_provider_rate_limited() -> None:
    adapter = _adapter(
        anthropic.RateLimitError("rate limited", response=_httpx_response(429), body=None)
    )

    result = asyncio.run(adapter.complete(_request()))

    assert result.failure_code is AICompletionFailureCode.PROVIDER_RATE_LIMITED


def test_connection_error_is_classified_as_provider_unavailable() -> None:
    adapter = _adapter(anthropic.APIConnectionError(request=_httpx_request()))

    result = asyncio.run(adapter.complete(_request()))

    assert result.failure_code is AICompletionFailureCode.PROVIDER_UNAVAILABLE


def test_server_error_is_classified_as_provider_unavailable() -> None:
    adapter = _adapter(
        anthropic.InternalServerError("server error", response=_httpx_response(500), body=None)
    )

    result = asyncio.run(adapter.complete(_request()))

    assert result.failure_code is AICompletionFailureCode.PROVIDER_UNAVAILABLE


def test_authentication_failure_is_classified_as_provider_unavailable() -> None:
    adapter = _adapter(
        anthropic.AuthenticationError("invalid api key", response=_httpx_response(401), body=None)
    )

    result = asyncio.run(adapter.complete(_request()))

    assert result.failure_code is AICompletionFailureCode.PROVIDER_UNAVAILABLE


def test_bad_request_is_classified_as_rejected_input() -> None:
    adapter = _adapter(
        anthropic.BadRequestError("malformed request", response=_httpx_response(400), body=None)
    )

    result = asyncio.run(adapter.complete(_request()))

    assert result.failure_code is AICompletionFailureCode.PROVIDER_REJECTED_INPUT


def test_past_deadline_short_circuits_to_provider_timeout() -> None:
    fake_client = _FakeAnthropicClient(_message())
    adapter = AnthropicProviderAdapter(
        _config(), client=cast(anthropic.AsyncAnthropic, fake_client)
    )
    request = AICompletionRequest(
        prompt="summarize this text",
        max_output_tokens=256,
        idempotency_key="attempt-1",
        deadline=datetime.now(UTC) - timedelta(seconds=1),
    )

    result = asyncio.run(adapter.complete(request))

    assert result.failure_code is AICompletionFailureCode.PROVIDER_TIMEOUT
    assert fake_client.messages.calls == []


def test_credential_is_redacted_from_config_repr() -> None:
    config = _config()

    representation = repr(config)

    assert "sk-ant-super-secret-value" not in representation
    assert "redacted" in representation


def test_empty_api_key_is_rejected_without_a_secret_leaking_error() -> None:
    with pytest.raises(AnthropicCredentialError) as excinfo:
        AnthropicProviderConfig(api_key="   ", model="claude-haiku-4-5")

    assert excinfo.value.reason_code == "EMPTY_API_KEY"


def test_provider_error_message_never_leaks_the_api_key() -> None:
    secret = "sk-ant-super-secret-value"
    adapter = AnthropicProviderAdapter(
        AnthropicProviderConfig(api_key=secret, model="claude-haiku-4-5"),
        client=cast(
            anthropic.AsyncAnthropic,
            _FakeAnthropicClient(
                anthropic.BadRequestError(
                    "malformed request", response=_httpx_response(400), body=None
                )
            ),
        ),
    )

    result = asyncio.run(adapter.complete(_request()))

    assert secret not in repr(result)
    assert secret not in repr(adapter)
