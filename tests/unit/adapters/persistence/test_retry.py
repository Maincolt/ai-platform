"""Deterministic tests for bounded complete-transaction retry."""

import asyncio
from dataclasses import dataclass, field

import pytest

from ai_platform.adapters.persistence.agent import PsycopgAgentPersistence
from ai_platform.adapters.persistence.orchestrator import PsycopgOrchestratorPersistence
from ai_platform.adapters.persistence.outbox import PsycopgOutboxTransaction
from ai_platform.adapters.persistence.recovery import PsycopgTransportRejectionTransaction
from ai_platform.adapters.persistence.retry import TransactionRetryPolicy, retry_transaction
from ai_platform.ports.persistence.errors import (
    PermanentPersistenceError,
    PersistenceConflictError,
    PersistenceUnavailableError,
    RetryableTransactionError,
    UnknownCommitOutcomeError,
)

ZERO_DELAY_POLICY = TransactionRetryPolicy(
    max_attempts=3,
    initial_backoff_seconds=0,
    maximum_backoff_seconds=0,
    jitter_ratio=0,
)


@dataclass(frozen=True, slots=True)
class _StableIntent:
    identity: str


@dataclass
class _RetryFixture:
    failures: list[Exception]
    transaction_retry_policy: TransactionRetryPolicy = ZERO_DELAY_POLICY
    calls: int = 0
    observed_intents: list[_StableIntent] = field(default_factory=list)

    @retry_transaction
    async def transact(self, intent: _StableIntent) -> str:
        self.calls += 1
        self.observed_intents.append(intent)
        if self.failures:
            raise self.failures.pop(0)
        return intent.identity


def test_retry_replays_complete_stable_intent_for_safe_precommit_failures() -> None:
    fixture = _RetryFixture(
        failures=[
            RetryableTransactionError("deadlock"),
            PersistenceUnavailableError("connection lost before commit"),
        ]
    )
    intent = _StableIntent("intent-1")

    result = asyncio.run(fixture.transact(intent))

    assert result == "intent-1"
    assert fixture.calls == 3
    assert fixture.observed_intents == [intent, intent, intent]
    assert all(observed is intent for observed in fixture.observed_intents)


def test_retry_exhaustion_is_bounded_and_preserves_last_classification() -> None:
    fixture = _RetryFixture(
        failures=[
            RetryableTransactionError("deadlock-1"),
            RetryableTransactionError("deadlock-2"),
            RetryableTransactionError("deadlock-3"),
        ]
    )

    with pytest.raises(RetryableTransactionError, match="deadlock-3"):
        asyncio.run(fixture.transact(_StableIntent("intent-1")))

    assert fixture.calls == 3


@pytest.mark.parametrize(
    "failure",
    [
        PersistenceConflictError("unique conflict"),
        PermanentPersistenceError("schema or permission failure"),
        UnknownCommitOutcomeError("commit may have succeeded"),
    ],
)
def test_unsafe_classifications_are_never_retried(failure: Exception) -> None:
    fixture = _RetryFixture(failures=[failure])

    with pytest.raises(type(failure)):
        asyncio.run(fixture.transact(_StableIntent("intent-1")))

    assert fixture.calls == 1


def test_retry_policy_rejects_unbounded_or_invalid_configuration() -> None:
    with pytest.raises(ValueError, match="between 1 and 5"):
        TransactionRetryPolicy(max_attempts=6)
    with pytest.raises(ValueError, match="maximum_backoff"):
        TransactionRetryPolicy(initial_backoff_seconds=1, maximum_backoff_seconds=0.5)


def test_every_persistence_transaction_entrypoint_has_bounded_retry() -> None:
    methods = (
        PsycopgOrchestratorPersistence.commit_submission,
        PsycopgOrchestratorPersistence.apply_terminal_outcome,
        PsycopgOrchestratorPersistence.expire,
        PsycopgOrchestratorPersistence.record_request_access,
        PsycopgAgentPersistence.commit_outcome,
        PsycopgOutboxTransaction.claim_next,
        PsycopgOutboxTransaction.record_publication_result,
        PsycopgOutboxTransaction.release_claim,
        PsycopgTransportRejectionTransaction.create_or_resolve,
        PsycopgTransportRejectionTransaction.record_quarantine_state,
        PsycopgTransportRejectionTransaction.mark_source_offset_completed,
    )

    assert all(hasattr(method, "__wrapped__") for method in methods)
