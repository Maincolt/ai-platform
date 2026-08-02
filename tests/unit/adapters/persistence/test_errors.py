"""Stable Psycopg error classification tests."""

import psycopg

from ai_platform.adapters.persistence.errors import classify_psycopg_error
from ai_platform.ports.persistence.errors import (
    PersistenceConflictError,
    PersistenceUnavailableError,
    RetryableTransactionError,
    UnknownCommitOutcomeError,
)


def test_integrity_and_retryable_failures_have_stable_classifications() -> None:
    assert isinstance(
        classify_psycopg_error(psycopg.errors.UniqueViolation()), PersistenceConflictError
    )
    assert isinstance(
        classify_psycopg_error(psycopg.errors.DeadlockDetected()), RetryableTransactionError
    )
    assert isinstance(
        classify_psycopg_error(psycopg.errors.SerializationFailure()),
        RetryableTransactionError,
    )


def test_connection_loss_at_commit_is_not_reported_as_definite_failure() -> None:
    error = psycopg.OperationalError("connection lost")
    assert isinstance(classify_psycopg_error(error), PersistenceUnavailableError)
    assert isinstance(classify_psycopg_error(error, commit_started=True), UnknownCommitOutcomeError)
