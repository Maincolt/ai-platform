"""OpenAI provider adapter (ADR-0014 Section 2).

Wraps the official `openai` SDK's async Chat Completions API directly --
no third-party multi-provider abstraction. Every SDK-specific exception
and response shape is translated here; nothing openai-specific crosses
this module's boundary.
"""

import time
from dataclasses import dataclass, field

import openai
from openai.types.chat import ChatCompletion

from ai_platform.adapters.ai_router._deadlines import is_past_deadline, seconds_until_deadline
from ai_platform.ports.ai_router import (
    AICompletionFailureCode,
    AICompletionRequest,
    AICompletionResult,
    AICompletionUsage,
)


class OpenAICredentialError(ValueError):
    """Stable, secret-free credential configuration failure."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _is_nonempty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


@dataclass(frozen=True, slots=True, repr=False)
class OpenAIProviderConfig:
    """Immutable credentials and model binding for one OpenAI adapter instance."""

    api_key: str = field(repr=False)
    model: str

    def __post_init__(self) -> None:
        if not _is_nonempty_text(self.api_key):
            raise OpenAICredentialError("EMPTY_API_KEY")
        if not _is_nonempty_text(self.model):
            raise OpenAICredentialError("EMPTY_MODEL")

    def __repr__(self) -> str:
        return f"OpenAIProviderConfig(api_key=<redacted>, model={self.model!r})"


def _classify_exception(exc: Exception) -> AICompletionFailureCode:
    if isinstance(exc, openai.APITimeoutError):
        return AICompletionFailureCode.PROVIDER_TIMEOUT
    if isinstance(exc, openai.RateLimitError):
        return AICompletionFailureCode.PROVIDER_RATE_LIMITED
    if isinstance(exc, openai.APIConnectionError):
        return AICompletionFailureCode.PROVIDER_UNAVAILABLE
    if isinstance(exc, openai.InternalServerError):
        return AICompletionFailureCode.PROVIDER_UNAVAILABLE
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return AICompletionFailureCode.PROVIDER_UNAVAILABLE
    if isinstance(
        exc,
        (
            openai.BadRequestError,
            openai.NotFoundError,
            openai.UnprocessableEntityError,
            openai.ConflictError,
        ),
    ):
        return AICompletionFailureCode.PROVIDER_REJECTED_INPUT
    if isinstance(exc, openai.APIStatusError):
        return (
            AICompletionFailureCode.PROVIDER_UNAVAILABLE
            if exc.status_code >= 500
            else AICompletionFailureCode.PROVIDER_REJECTED_INPUT
        )
    return AICompletionFailureCode.PROVIDER_UNAVAILABLE


class OpenAIProviderAdapter:
    """A single (OpenAI, model) `ProviderAdapter`."""

    provider_name = "openai"

    def __init__(
        self,
        config: OpenAIProviderConfig,
        *,
        client: openai.AsyncOpenAI | None = None,
    ) -> None:
        self._config = config
        self._client = client if client is not None else openai.AsyncOpenAI(api_key=config.api_key)

    async def complete(self, request: AICompletionRequest) -> AICompletionResult:
        if is_past_deadline(request.deadline):
            return AICompletionResult(failure_code=AICompletionFailureCode.PROVIDER_TIMEOUT)

        started = time.monotonic()
        try:
            response = await self._client.chat.completions.create(
                model=self._config.model,
                max_completion_tokens=request.max_output_tokens,
                messages=[{"role": "user", "content": request.prompt}],
                timeout=seconds_until_deadline(request.deadline),
                extra_headers={"Idempotency-Key": request.idempotency_key},
            )
        except openai.OpenAIError as exc:
            return AICompletionResult(failure_code=_classify_exception(exc))
        latency_seconds = time.monotonic() - started

        if not response.choices:
            return AICompletionResult(
                failure_code=AICompletionFailureCode.PROVIDER_REJECTED_OUTPUT,
                usage=_usage_from_response(response, self._config.model, latency_seconds),
            )
        output_text = response.choices[0].message.content
        usage = _usage_from_response(response, self._config.model, latency_seconds)
        if not output_text:
            return AICompletionResult(
                failure_code=AICompletionFailureCode.PROVIDER_REJECTED_OUTPUT,
                usage=usage,
            )
        return AICompletionResult(output_text=output_text, usage=usage)


def _usage_from_response(
    response: ChatCompletion, model: str, latency_seconds: float
) -> AICompletionUsage:
    reported = response.usage
    input_tokens = reported.prompt_tokens if reported is not None else 0
    output_tokens = reported.completion_tokens if reported is not None else 0
    return AICompletionUsage(
        provider="openai",
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_seconds=latency_seconds,
    )


__all__ = ["OpenAICredentialError", "OpenAIProviderAdapter", "OpenAIProviderConfig"]
