"""SDK-free conformance tests for the OpenAI provider adapter.

No test in this module makes a real network call: `OpenAIProviderAdapter`
is constructed with a fake, in-process client whose `chat.completions.create`
either returns a locally built `ChatCompletion` or raises a locally built
`openai.OpenAIError` subclass. Async tests follow this repository's existing
`asyncio.run(...)` convention (no `pytest-asyncio` dependency).
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast

import httpx
import openai
import pytest
from openai.types import CompletionUsage
from openai.types.chat import ChatCompletion
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_message import ChatCompletionMessage

from ai_platform.adapters.ai_router.openai_adapter import (
    OpenAICredentialError,
    OpenAIProviderAdapter,
    OpenAIProviderConfig,
)
from ai_platform.ports.ai_router import AICompletionFailureCode, AICompletionRequest


class _FakeCompletions:
    def __init__(self, outcome: ChatCompletion | Exception) -> None:
        self._outcome = outcome
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> ChatCompletion:
        self.calls.append(kwargs)
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class _FakeChat:
    def __init__(self, outcome: ChatCompletion | Exception) -> None:
        self.completions = _FakeCompletions(outcome)


class _FakeOpenAIClient:
    def __init__(self, outcome: ChatCompletion | Exception) -> None:
        self.chat = _FakeChat(outcome)


def _request() -> AICompletionRequest:
    return AICompletionRequest(
        prompt="summarize this text",
        max_output_tokens=256,
        idempotency_key="attempt-1",
        deadline=datetime.now(UTC) + timedelta(seconds=30),
    )


def _config() -> OpenAIProviderConfig:
    return OpenAIProviderConfig(api_key="sk-openai-super-secret-value", model="gpt-5")


def _completion(text: str | None = "a concise summary") -> ChatCompletion:
    return ChatCompletion(
        id="cmpl_1",
        choices=[
            Choice(
                finish_reason="stop",
                index=0,
                message=ChatCompletionMessage(role="assistant", content=text),
            )
        ],
        created=0,
        model="gpt-5",
        object="chat.completion",
        usage=CompletionUsage(completion_tokens=6, prompt_tokens=12, total_tokens=18),
    )


def _httpx_response(status_code: int) -> httpx.Response:
    return httpx.Response(
        status_code, request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    )


def _httpx_request() -> httpx.Request:
    return httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


def _adapter(outcome: ChatCompletion | Exception) -> OpenAIProviderAdapter:
    fake_client = _FakeOpenAIClient(outcome)
    return OpenAIProviderAdapter(_config(), client=cast(openai.AsyncOpenAI, fake_client))


def test_successful_completion_normalizes_output_and_usage() -> None:
    adapter = _adapter(_completion("a concise summary"))

    result = asyncio.run(adapter.complete(_request()))

    assert result.output_text == "a concise summary"
    assert result.usage is not None
    assert result.usage.provider == "openai"
    assert result.usage.model == "gpt-5"
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 6
    assert result.usage.latency_seconds >= 0


def test_successful_completion_sends_idempotency_key() -> None:
    fake_client = _FakeOpenAIClient(_completion())
    adapter = OpenAIProviderAdapter(_config(), client=cast(openai.AsyncOpenAI, fake_client))

    asyncio.run(adapter.complete(_request()))

    call = fake_client.chat.completions.calls[0]
    headers = cast(dict[str, str], call["extra_headers"])
    assert headers["Idempotency-Key"] == "attempt-1"


def test_empty_output_is_classified_as_rejected_output() -> None:
    adapter = _adapter(_completion(None))

    result = asyncio.run(adapter.complete(_request()))

    assert result.failure_code is AICompletionFailureCode.PROVIDER_REJECTED_OUTPUT
    assert result.usage is not None


def test_timeout_is_classified_as_provider_timeout() -> None:
    adapter = _adapter(openai.APITimeoutError(request=_httpx_request()))

    result = asyncio.run(adapter.complete(_request()))

    assert result.failure_code is AICompletionFailureCode.PROVIDER_TIMEOUT


def test_rate_limit_is_classified_as_provider_rate_limited() -> None:
    adapter = _adapter(
        openai.RateLimitError("rate limited", response=_httpx_response(429), body=None)
    )

    result = asyncio.run(adapter.complete(_request()))

    assert result.failure_code is AICompletionFailureCode.PROVIDER_RATE_LIMITED


def test_connection_error_is_classified_as_provider_unavailable() -> None:
    adapter = _adapter(openai.APIConnectionError(request=_httpx_request()))

    result = asyncio.run(adapter.complete(_request()))

    assert result.failure_code is AICompletionFailureCode.PROVIDER_UNAVAILABLE


def test_server_error_is_classified_as_provider_unavailable() -> None:
    adapter = _adapter(
        openai.InternalServerError("server error", response=_httpx_response(500), body=None)
    )

    result = asyncio.run(adapter.complete(_request()))

    assert result.failure_code is AICompletionFailureCode.PROVIDER_UNAVAILABLE


def test_authentication_failure_is_classified_as_provider_unavailable() -> None:
    adapter = _adapter(
        openai.AuthenticationError("invalid api key", response=_httpx_response(401), body=None)
    )

    result = asyncio.run(adapter.complete(_request()))

    assert result.failure_code is AICompletionFailureCode.PROVIDER_UNAVAILABLE


def test_bad_request_is_classified_as_rejected_input() -> None:
    adapter = _adapter(
        openai.BadRequestError("malformed request", response=_httpx_response(400), body=None)
    )

    result = asyncio.run(adapter.complete(_request()))

    assert result.failure_code is AICompletionFailureCode.PROVIDER_REJECTED_INPUT


def test_past_deadline_short_circuits_to_provider_timeout() -> None:
    fake_client = _FakeOpenAIClient(_completion())
    adapter = OpenAIProviderAdapter(_config(), client=cast(openai.AsyncOpenAI, fake_client))
    request = AICompletionRequest(
        prompt="summarize this text",
        max_output_tokens=256,
        idempotency_key="attempt-1",
        deadline=datetime.now(UTC) - timedelta(seconds=1),
    )

    result = asyncio.run(adapter.complete(request))

    assert result.failure_code is AICompletionFailureCode.PROVIDER_TIMEOUT
    assert fake_client.chat.completions.calls == []


def test_empty_choices_list_is_classified_as_rejected_output() -> None:
    """Adversarial shape: a well-formed response with no choices at all
    (not merely a choice with empty/None content)."""
    completion = ChatCompletion(
        id="cmpl_1",
        choices=[],
        created=0,
        model="gpt-5",
        object="chat.completion",
        usage=CompletionUsage(completion_tokens=0, prompt_tokens=12, total_tokens=12),
    )
    adapter = _adapter(completion)

    result = asyncio.run(adapter.complete(_request()))

    assert result.failure_code is AICompletionFailureCode.PROVIDER_REJECTED_OUTPUT
    assert result.usage is not None
    assert result.usage.input_tokens == 12


def test_missing_usage_defaults_to_zero_rather_than_crashing() -> None:
    """Adversarial shape: the provider omits `usage` entirely (allowed by
    the SDK's typed response, e.g. some proxy/gateway deployments)."""
    completion = ChatCompletion(
        id="cmpl_1",
        choices=[
            Choice(
                finish_reason="stop",
                index=0,
                message=ChatCompletionMessage(role="assistant", content="a concise summary"),
            )
        ],
        created=0,
        model="gpt-5",
        object="chat.completion",
        usage=None,
    )
    adapter = _adapter(completion)

    result = asyncio.run(adapter.complete(_request()))

    assert result.output_text == "a concise summary"
    assert result.usage is not None
    assert result.usage.input_tokens == 0
    assert result.usage.output_tokens == 0


def test_credential_is_redacted_from_config_repr() -> None:
    config = _config()

    representation = repr(config)

    assert "sk-openai-super-secret-value" not in representation
    assert "redacted" in representation


def test_empty_api_key_is_rejected_without_a_secret_leaking_error() -> None:
    with pytest.raises(OpenAICredentialError) as excinfo:
        OpenAIProviderConfig(api_key="   ", model="gpt-5")

    assert excinfo.value.reason_code == "EMPTY_API_KEY"


def test_provider_error_message_never_leaks_the_api_key() -> None:
    secret = "sk-openai-super-secret-value"
    adapter = OpenAIProviderAdapter(
        OpenAIProviderConfig(api_key=secret, model="gpt-5"),
        client=cast(
            openai.AsyncOpenAI,
            _FakeOpenAIClient(
                openai.BadRequestError(
                    "malformed request", response=_httpx_response(400), body=None
                )
            ),
        ),
    )

    result = asyncio.run(adapter.complete(_request()))

    assert secret not in repr(result)
    assert secret not in repr(adapter)
