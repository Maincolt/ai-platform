"""Test Agent domain errors (ADR-0007 Section 2, vertical-slice-01.md Section 13).

Stable, transport-independent classifications. Not HTTP errors or Problem
Details -- those belong to the Workflow API (Phase 5).
"""

from ai_platform.shared.identifiers import MessageId, TaskAttemptId


class TestAgentError(Exception):
    """Base class for Test Agent domain errors."""


class CapabilityMismatchError(TestAgentError):
    """Raised when the command requests a capability/version this Agent
    does not implement. The Agent validates this independently rather
    than trusting the Orchestrator's Registry selection (ADR-0007 Section
    2; see docs/sprint-4/consilium.md, disagreement 1)."""

    def __init__(self, requested_name: str, requested_version: str) -> None:
        self.requested_name = requested_name
        self.requested_version = requested_version
        super().__init__(f"unsupported capability {requested_name!r} version {requested_version!r}")


class CommandIdentityConflictError(TestAgentError):
    """Same task_attempt_id, different command message_id -- a permanent
    conflict; the existing receipt's outcome is never replaced."""

    def __init__(self, task_attempt_id: TaskAttemptId, existing_message_id: MessageId) -> None:
        self.task_attempt_id = task_attempt_id
        self.existing_message_id = existing_message_id
        super().__init__(
            f"task_attempt_id {task_attempt_id} already has a completed receipt for a "
            f"different command message_id {existing_message_id}"
        )


class CommandIntegrityError(TestAgentError):
    """Same command message_id, different immutable bytes (digest) -- an
    integrity failure requiring quarantine, not ordinary deduplication."""

    def __init__(self, message_id: MessageId) -> None:
        self.message_id = message_id
        super().__init__(
            f"command {message_id} was previously received with different immutable bytes"
        )


class MissingOutcomeInvariantError(TestAgentError):
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
