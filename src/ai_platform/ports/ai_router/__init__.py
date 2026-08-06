"""Technology-neutral AI Router boundary (ADR-0014 Section 1).

A synchronous, provider-neutral request/response contract. Callers (an
Agent, during its own command-processing transaction lane) never see a
provider-specific exception type or provider-specific error shape --
adapters behind this port are solely responsible for that translation.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol


class DataClassification(Enum):
    """Handling tag carried on every request (ADR-0014 Section 4).

    Only one value is defined because `text.summarize` -- the only caller
    that exists today -- needs no more than "no special handling
    required." Additional classifications are added when a capability
    actually needs them, not speculatively.
    """

    NO_SPECIAL_HANDLING = "NO_SPECIAL_HANDLING"


class AICompletionContractError(ValueError):
    """Stable, content-free validation failure for a port-level value object."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _is_nonempty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


@dataclass(frozen=True, slots=True)
class AICompletionRequest:
    """A capability-scoped completion request bounded by an absolute deadline.

    `prompt` is a plain string: this boundary is text-in/text-out only
    (ADR-0014 Section 9 excludes tool use and streaming). `deadline` is
    absolute, derived by the caller from the remaining
    `task_result_deadline`, matching this codebase's existing
    absolute-deadline pattern rather than a relative duration.
    """

    prompt: str
    max_output_tokens: int
    idempotency_key: str
    deadline: datetime
    classification: DataClassification = DataClassification.NO_SPECIAL_HANDLING

    def __post_init__(self) -> None:
        if not _is_nonempty_text(self.prompt):
            raise AICompletionContractError("EMPTY_PROMPT")
        if self.max_output_tokens <= 0:
            raise AICompletionContractError("NON_POSITIVE_MAX_OUTPUT_TOKENS")
        if not _is_nonempty_text(self.idempotency_key):
            raise AICompletionContractError("EMPTY_IDEMPOTENCY_KEY")
        if self.deadline.tzinfo is None:
            raise AICompletionContractError("NAIVE_DEADLINE")


class AICompletionFailureCode(Enum):
    """The closed set of failure classifications callers may observe."""

    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    PROVIDER_RATE_LIMITED = "PROVIDER_RATE_LIMITED"
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_REJECTED_INPUT = "PROVIDER_REJECTED_INPUT"
    PROVIDER_REJECTED_OUTPUT = "PROVIDER_REJECTED_OUTPUT"
    ALL_PROVIDERS_EXHAUSTED = "ALL_PROVIDERS_EXHAUSTED"


RETRYABLE_FAILURE_CODES: frozenset[AICompletionFailureCode] = frozenset(
    {
        AICompletionFailureCode.PROVIDER_UNAVAILABLE,
        AICompletionFailureCode.PROVIDER_RATE_LIMITED,
        AICompletionFailureCode.PROVIDER_TIMEOUT,
    }
)


@dataclass(frozen=True, slots=True)
class AICompletionUsage:
    """Structured usage data for one real provider call (ADR-0014 Section 3).

    Deliberately excludes the prompt and completion content -- those stay
    inside the existing redaction boundary. Carries only what a caller
    needs to persist a durable usage entry later.
    """

    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_seconds: float

    def __post_init__(self) -> None:
        if not _is_nonempty_text(self.provider):
            raise AICompletionContractError("EMPTY_PROVIDER")
        if not _is_nonempty_text(self.model):
            raise AICompletionContractError("EMPTY_MODEL")
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise AICompletionContractError("NEGATIVE_TOKEN_COUNT")
        if self.latency_seconds < 0:
            raise AICompletionContractError("NEGATIVE_LATENCY")


@dataclass(frozen=True, slots=True)
class AICompletionResult:
    """A discriminated success/failure outcome, shaped like `AgentOutcome`.

    Exactly one of `output_text` (success) or `failure_code` (failure)
    must be set. `usage` is required on success (a successful completion
    always reflects a real provider call) and optional on failure --
    populated only when the failure followed a real provider call
    (e.g. `PROVIDER_REJECTED_OUTPUT`), absent for failures classified
    before or without one (e.g. `ALL_PROVIDERS_EXHAUSTED`).
    """

    output_text: str | None = None
    usage: AICompletionUsage | None = None
    failure_code: AICompletionFailureCode | None = field(default=None)

    def __post_init__(self) -> None:
        is_success = self.output_text is not None
        is_failure = self.failure_code is not None
        if is_success == is_failure:
            raise AICompletionContractError(
                "AICompletionResult must set exactly one of output_text (success) or "
                "failure_code (failure)"
            )
        if is_success and self.usage is None:
            raise AICompletionContractError("USAGE_REQUIRED_ON_SUCCESS")


class AIRouterPort(Protocol):
    """Synchronous, technology-neutral completion boundary (ADR-0002 Section 2)."""

    async def complete(self, request: AICompletionRequest) -> AICompletionResult:
        """Return a completion, bounded by `request.deadline`, never raising."""
        ...


__all__ = [
    "RETRYABLE_FAILURE_CODES",
    "AICompletionFailureCode",
    "AICompletionRequest",
    "AICompletionContractError",
    "AICompletionResult",
    "AICompletionUsage",
    "AIRouterPort",
    "DataClassification",
]
