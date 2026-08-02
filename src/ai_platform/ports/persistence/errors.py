"""Stable persistence failure classifications visible to application code."""


class PersistenceError(Exception):
    """Base class for stable persistence failures."""


class PersistenceConflictError(PersistenceError):
    """A uniqueness, revision, fencing, or immutable-identity conflict."""


class RetryableTransactionError(PersistenceError):
    """The complete stable transaction intent may be retried."""


class PersistenceUnavailableError(PersistenceError):
    """The configured persistence dependency is temporarily unavailable."""


class UnknownCommitOutcomeError(PersistenceError):
    """Commit may have succeeded; callers must resolve by stable identity."""


class PermanentPersistenceError(PersistenceError):
    """A non-retryable adapter or stored-data failure."""
