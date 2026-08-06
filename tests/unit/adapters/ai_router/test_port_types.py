"""Discriminated-outcome and validation invariants for the AI Router port types."""

from datetime import UTC, datetime

import pytest

from ai_platform.ports.ai_router import (
    AICompletionContractError,
    AICompletionFailureCode,
    AICompletionRequest,
    AICompletionResult,
    AICompletionUsage,
    DataClassification,
)


def _deadline() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _usage() -> AICompletionUsage:
    return AICompletionUsage(
        provider="anthropic",
        model="claude-haiku-4-5",
        input_tokens=10,
        output_tokens=5,
        latency_seconds=0.5,
    )


def test_request_accepts_valid_values() -> None:
    request = AICompletionRequest(
        prompt="summarize this",
        max_output_tokens=256,
        idempotency_key="attempt-1",
        deadline=_deadline(),
    )
    assert request.classification is DataClassification.NO_SPECIAL_HANDLING


@pytest.mark.parametrize(
    "kwargs",
    [
        {"prompt": ""},
        {"prompt": "   "},
        {"max_output_tokens": 0},
        {"max_output_tokens": -1},
        {"idempotency_key": ""},
    ],
)
def test_request_rejects_invalid_values(kwargs: dict[str, object]) -> None:
    base: dict[str, object] = {
        "prompt": "summarize this",
        "max_output_tokens": 256,
        "idempotency_key": "attempt-1",
        "deadline": _deadline(),
    }
    base.update(kwargs)
    with pytest.raises(AICompletionContractError):
        AICompletionRequest(**base)  # type: ignore[arg-type]


def test_request_rejects_naive_deadline() -> None:
    with pytest.raises(AICompletionContractError):
        AICompletionRequest(
            prompt="summarize this",
            max_output_tokens=256,
            idempotency_key="attempt-1",
            deadline=datetime(2026, 1, 1),
        )


def test_result_success_requires_usage() -> None:
    with pytest.raises(AICompletionContractError):
        AICompletionResult(output_text="a summary")


def test_result_success_shape_is_valid() -> None:
    result = AICompletionResult(output_text="a summary", usage=_usage())
    assert result.output_text == "a summary"
    assert result.failure_code is None


def test_result_failure_shape_is_valid() -> None:
    result = AICompletionResult(failure_code=AICompletionFailureCode.PROVIDER_TIMEOUT)
    assert result.output_text is None
    assert result.failure_code is AICompletionFailureCode.PROVIDER_TIMEOUT


def test_result_rejects_neither_output_nor_failure() -> None:
    with pytest.raises(AICompletionContractError):
        AICompletionResult()


def test_result_rejects_both_output_and_failure() -> None:
    with pytest.raises(AICompletionContractError):
        AICompletionResult(
            output_text="a summary",
            usage=_usage(),
            failure_code=AICompletionFailureCode.PROVIDER_TIMEOUT,
        )


def test_failure_after_a_real_call_may_carry_usage() -> None:
    result = AICompletionResult(
        failure_code=AICompletionFailureCode.PROVIDER_REJECTED_OUTPUT, usage=_usage()
    )
    assert result.usage is not None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"provider": ""},
        {"model": ""},
        {"input_tokens": -1},
        {"output_tokens": -1},
        {"latency_seconds": -0.1},
    ],
)
def test_usage_rejects_invalid_values(kwargs: dict[str, object]) -> None:
    base: dict[str, object] = {
        "provider": "anthropic",
        "model": "claude-haiku-4-5",
        "input_tokens": 10,
        "output_tokens": 5,
        "latency_seconds": 0.5,
    }
    base.update(kwargs)
    with pytest.raises(AICompletionContractError):
        AICompletionUsage(**base)  # type: ignore[arg-type]
