"""Anthropic Claude provider adapter (ADR-0014 Section 2).

Wraps the official `anthropic` SDK's async Messages API directly -- no
third-party multi-provider abstraction. Every SDK-specific exception and
response shape is translated here; nothing anthropic-specific crosses
this module's boundary.
"""

import time
from dataclasses import dataclass, field

import anthropic

from ai_platform.adapters.ai_router._deadlines import is_past_deadline, seconds_until_deadline
from ai_platform.ports.ai_router import (
    AICompletionFailureCode,
    AICompletionRequest,
    AICompletionResult,
    AICompletionUsage,
)


class AnthropicCredentialError(ValueError):
    """Stable, secret-free credential configuration failure."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _is_nonempty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


@dataclass(frozen=True, slots=True, repr=False)
class AnthropicProviderConfig:
    """Immutable credentials and model binding for one Anthropic adapter instance."""

    api_key: str = field(repr=False)
    model: str

    def __post_init__(self) -> None:
        if not _is_nonempty_text(self.api_key):
            raise AnthropicCredentialError("EMPTY_API_KEY")
        if not _is_nonempty_text(self.model):
            raise AnthropicCredentialError("EMPTY_MODEL")

    def __repr__(self) -> str:
        return f"AnthropicProviderConfig(api_key=<redacted>, model={self.model!r})"


def _classify_exception(exc: Exception) -> AICompletionFailureCode:
    if isinstance(exc, anthropic.APITimeoutError):
        return AICompletionFailureCode.PROVIDER_TIMEOUT
    if isinstance(exc, anthropic.RateLimitError):
        return AICompletionFailureCode.PROVIDER_RATE_LIMITED
    if isinstance(exc, anthropic.APIConnectionError):
        return AICompletionFailureCode.PROVIDER_UNAVAILABLE
    if isinstance(exc, anthropic.InternalServerError):
        return AICompletionFailureCode.PROVIDER_UNAVAILABLE
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return AICompletionFailureCode.PROVIDER_UNAVAILABLE
    if isinstance(
        exc,
        (
            anthropic.BadRequestError,
            anthropic.NotFoundError,
            anthropic.UnprocessableEntityError,
            anthropic.ConflictError,
        ),
    ):
        return AICompletionFailureCode.PROVIDER_REJECTED_INPUT
    if isinstance(exc, anthropic.APIStatusError):
        return (
            AICompletionFailureCode.PROVIDER_UNAVAILABLE
            if exc.status_code >= 500
            else AICompletionFailureCode.PROVIDER_REJECTED_INPUT
        )
    return AICompletionFailureCode.PROVIDER_UNAVAILABLE


def _extract_output_text(message: anthropic.types.Message) -> str | None:
    text_segments = [block.text for block in message.content if block.type == "text"]
    combined = "".join(text_segments)
    return combined if combined else None


class AnthropicProviderAdapter:
    """A single (Anthropic, model) `ProviderAdapter`."""

    provider_name = "anthropic"

    def __init__(
        self,
        config: AnthropicProviderConfig,
        *,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        self._config = config
        self._client = (
            client if client is not None else anthropic.AsyncAnthropic(api_key=config.api_key)
        )

    async def complete(self, request: AICompletionRequest) -> AICompletionResult:
        if is_past_deadline(request.deadline):
            return AICompletionResult(failure_code=AICompletionFailureCode.PROVIDER_TIMEOUT)

        started = time.monotonic()
        try:
            message = await self._client.messages.create(
                model=self._config.model,
                max_tokens=request.max_output_tokens,
                messages=[{"role": "user", "content": request.prompt}],
                timeout=seconds_until_deadline(request.deadline),
                extra_headers={"idempotency-key": request.idempotency_key},
            )
        except anthropic.AnthropicError as exc:
            return AICompletionResult(failure_code=_classify_exception(exc))
        latency_seconds = time.monotonic() - started

        output_text = _extract_output_text(message)
        usage = AICompletionUsage(
            provider=self.provider_name,
            model=self._config.model,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            latency_seconds=latency_seconds,
        )
        if output_text is None:
            return AICompletionResult(
                failure_code=AICompletionFailureCode.PROVIDER_REJECTED_OUTPUT,
                usage=usage,
            )
        return AICompletionResult(output_text=output_text, usage=usage)


__all__ = ["AnthropicCredentialError", "AnthropicProviderAdapter", "AnthropicProviderConfig"]
