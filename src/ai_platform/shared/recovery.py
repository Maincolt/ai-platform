"""Publication disposition, shared between the Orchestrator command outbox
and the Agent event outbox (vertical-slice-01.md Section 12).
"""

from enum import Enum


class PublicationState(Enum):
    """Mutable publication disposition for one outbox record."""

    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    CLAIMED = "CLAIMED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DEFINITIVELY_NOT_ACCEPTED = "DEFINITIVELY_NOT_ACCEPTED"
    ATTEMPTED_UNKNOWN = "ATTEMPTED_UNKNOWN"
    FAILED = "FAILED"
