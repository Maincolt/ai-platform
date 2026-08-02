"""Translate Psycopg failures into stable persistence-port classifications."""

import psycopg

from ai_platform.ports.persistence.errors import (
    PermanentPersistenceError,
    PersistenceConflictError,
    PersistenceError,
    PersistenceUnavailableError,
    RetryableTransactionError,
    UnknownCommitOutcomeError,
)


def classify_psycopg_error(exc: Exception, *, commit_started: bool = False) -> PersistenceError:
    """Return a stable error without exposing driver details or SQL parameters."""
    if isinstance(
        exc,
        (
            psycopg.errors.UniqueViolation,
            psycopg.errors.CheckViolation,
            psycopg.errors.ForeignKeyViolation,
        ),
    ):
        return PersistenceConflictError("A persistence invariant was violated.")
    if isinstance(
        exc,
        (psycopg.errors.SerializationFailure, psycopg.errors.DeadlockDetected),
    ):
        return RetryableTransactionError("The complete persistence transaction may be retried.")
    if isinstance(exc, psycopg.OperationalError):
        if commit_started:
            return UnknownCommitOutcomeError(
                "The persistence commit outcome is unknown; resolve by stable identity."
            )
        return PersistenceUnavailableError("The persistence dependency is unavailable.")
    if isinstance(exc, psycopg.Error):
        return PermanentPersistenceError("A non-retryable persistence operation failed.")
    return PermanentPersistenceError("Persistence returned invalid or inconsistent data.")


__all__ = [
    "PermanentPersistenceError",
    "PersistenceConflictError",
    "PersistenceError",
    "PersistenceUnavailableError",
    "RetryableTransactionError",
    "UnknownCommitOutcomeError",
    "classify_psycopg_error",
]
