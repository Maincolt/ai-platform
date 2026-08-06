"""Absolute-deadline-to-remaining-seconds conversion shared by AI Router code.

Kept as a tiny, private helper (leading underscore) rather than a public
module: both provider adapters and the routing engine need the identical
"how much time is actually left" calculation, and duplicating it would
risk the two drifting.
"""

from datetime import UTC, datetime

MINIMUM_REMAINING_SECONDS = 0.001


def seconds_until_deadline(deadline: datetime, *, now: datetime | None = None) -> float:
    """Return remaining seconds, floored just above zero rather than negative.

    A floor (instead of zero or a negative value) keeps this usable
    directly as an SDK client timeout, which typically rejects
    non-positive values; callers that must treat "already past deadline"
    as an immediate timeout should compare against `MINIMUM_REMAINING_SECONDS`.
    """
    current = now if now is not None else datetime.now(UTC)
    remaining = (deadline - current).total_seconds()
    return max(remaining, MINIMUM_REMAINING_SECONDS)


def is_past_deadline(deadline: datetime, *, now: datetime | None = None) -> bool:
    current = now if now is not None else datetime.now(UTC)
    return current >= deadline


__all__ = ["MINIMUM_REMAINING_SECONDS", "is_past_deadline", "seconds_until_deadline"]
