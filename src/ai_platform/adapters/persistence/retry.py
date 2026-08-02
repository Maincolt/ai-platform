"""Bounded retry of complete, stable persistence transaction intents."""

import asyncio
import random
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from types import CoroutineType
from typing import Any, Concatenate, Protocol

from ai_platform.ports.persistence.errors import (
    PersistenceUnavailableError,
    RetryableTransactionError,
)


@dataclass(frozen=True, slots=True)
class TransactionRetryPolicy:
    """Small bounded retry policy selected for Vertical Slice 01.

    Three total attempts bound lock/dependency amplification. Exponential
    backoff starts at 25 ms, is capped at 250 ms, and adds up to 20% jitter.
    Callers may inject a zero-delay policy in deterministic unit tests.
    """

    max_attempts: int = 3
    initial_backoff_seconds: float = 0.025
    maximum_backoff_seconds: float = 0.250
    jitter_ratio: float = 0.20

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 5:
            raise ValueError("max_attempts must be between 1 and 5")
        if self.initial_backoff_seconds < 0:
            raise ValueError("initial_backoff_seconds must not be negative")
        if self.maximum_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError("maximum_backoff_seconds must not be below initial backoff")
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be between 0 and 1")

    def delay_before_attempt(self, completed_attempts: int) -> float:
        base = min(
            self.maximum_backoff_seconds,
            self.initial_backoff_seconds * (2 ** max(0, completed_attempts - 1)),
        )
        return base + random.random() * base * self.jitter_ratio


DEFAULT_TRANSACTION_RETRY_POLICY = TransactionRetryPolicy()


class _RetryConfigured(Protocol):
    transaction_retry_policy: TransactionRetryPolicy


def retry_transaction[Self: _RetryConfigured, **P, R](
    method: Callable[Concatenate[Self, P], CoroutineType[Any, Any, R]],
) -> Callable[Concatenate[Self, P], CoroutineType[Any, Any, R]]:
    """Replay a complete adapter method only for safe pre-commit classifications."""

    @wraps(method)
    async def wrapped(self: Self, *args: P.args, **kwargs: P.kwargs) -> R:
        attempt = 1
        while True:
            try:
                return await method(self, *args, **kwargs)
            except RetryableTransactionError, PersistenceUnavailableError:
                if attempt >= self.transaction_retry_policy.max_attempts:
                    raise
                delay = self.transaction_retry_policy.delay_before_attempt(attempt)
                attempt += 1
                if delay > 0:
                    await asyncio.sleep(delay)

    return wrapped
