"""Review Agent domain errors (ADR-0007 Section 2, ADR-0018).

Stable, transport-independent classifications. Not HTTP errors or Problem
Details -- those belong to the Workflow API (Phase 5). Duplicated from
`ai_platform.agents.summarize_agent.errors` (renamed base exception)
rather than imported, per this module's self-contained-deployable
convention -- see `ids.py` for the same rationale.
"""

from ai_platform.shared.identifiers import MessageId, TaskAttemptId


class ReviewAgentError(Exception):
    """Base class for Review Agent domain errors."""


class CapabilityMismatchError(ReviewAgentError):
    """Raised when the command requests a capability/version this Agent
    does not implement. The Agent validates this independently rather
    than trusting the Orchestrator's Registry selection (ADR-0007 Section
    2; see docs/sprint-4/consilium.md, disagreement 1)."""

    def __init__(self, requested_name: str, requested_version: str) -> None:
        self.requested_name = requested_name
        self.requested_version = requested_version
        super().__init__(f"unsupported capability {requested_name!r} version {requested_version!r}")


class CommandIdentityConflictError(ReviewAgentError):
    """Same task_attempt_id, different command message_id -- a permanent
    conflict; the existing receipt's outcome is never replaced."""

    def __init__(self, task_attempt_id: TaskAttemptId, existing_message_id: MessageId) -> None:
        self.task_attempt_id = task_attempt_id
        self.existing_message_id = existing_message_id
        super().__init__(
            f"task_attempt_id {task_attempt_id} already has a completed receipt for a "
            f"different command message_id {existing_message_id}"
        )


class CommandIntegrityError(ReviewAgentError):
    """Same command message_id, different immutable bytes (digest) -- an
    integrity failure requiring quarantine, not ordinary deduplication."""

    def __init__(self, message_id: MessageId) -> None:
        self.message_id = message_id
        super().__init__(
            f"command {message_id} was previously received with different immutable bytes"
        )


class MissingOutcomeInvariantError(ReviewAgentError):
    """A completed receipt exists but its outcome does not.

    The receipt, outcome, terminal event, and event outbox row commit
    together in one transaction (ADR-0006 Section 5, Section 11 "Agent
    Outcome Transaction"); a receipt without an outcome means that
    invariant was violated by the persistence layer. Fail closed rather
    than silently returning an incomplete result.
    """

    def __init__(self, task_attempt_id: TaskAttemptId) -> None:
        self.task_attempt_id = task_attempt_id
        super().__init__(
            f"task_attempt_id {task_attempt_id} has a completed receipt but no outcome; "
            "this violates the receipt/outcome atomicity invariant"
        )


class ProviderCallReconciliationPendingError(ReviewAgentError):
    """A redelivery found this Agent's own unresolved provider-call claim
    (ADR-0016).

    Deliberately not resolved to a synthetic outcome: the original attempt
    may still be genuinely in flight. Raising lets the existing
    `EventConsumerWorker` retry-then-quarantine path (`DeliveryHandlingDisposition
    .RETRYABLE`) and the Orchestrator's existing `DeadlineReconciler` --
    both already Accepted infrastructure -- provide the bounded
    reconciliation window and operator-review signal ADR-0014 Section 8
    Q1 asked for, without inventing a synthetic outcome that could race a
    late-arriving real completion.
    """

    def __init__(self, task_attempt_id: TaskAttemptId) -> None:
        self.task_attempt_id = task_attempt_id
        super().__init__(
            f"task_attempt_id {task_attempt_id} has an unresolved provider call claim; "
            "not re-calling the provider or resolving synthetically (ADR-0016)"
        )
