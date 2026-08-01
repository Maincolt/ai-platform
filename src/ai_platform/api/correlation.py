"""Correlation-Id normalization (ADR-0012).

Every API invocation establishes one safe effective correlation
identifier: a valid client value is preserved; a missing, malformed,
unsafe, unsupported, or oversized value is discarded and a new
platform-controlled value is generated. The raw invalid value is never
echoed, logged, traced, persisted, or otherwise propagated.
"""

import re
import uuid
from dataclasses import dataclass

from ai_platform.shared.identifiers import CorrelationId

# Canonical lowercase UUIDv7, matching ADR-0004's accepted format.
_CANONICAL_UUIDV7_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
# Bounded before any parsing (ADR-0012: "length-checked before expensive
# parsing"). A canonical UUIDv7 is exactly 36 characters; this is a
# generous upper bound that still rejects grossly oversized input cheaply.
_MAX_RAW_LENGTH = 200


@dataclass(frozen=True, slots=True)
class CorrelationNormalizationResult:
    """The outcome of normalizing one raw Correlation-Id header value."""

    effective_correlation_id: CorrelationId
    was_generated: bool


def _is_valid_canonical_uuidv7(raw_value: str) -> bool:
    if len(raw_value) > _MAX_RAW_LENGTH:
        return False
    # Reject any control character or non-printable content outright,
    # before the regex, per ADR-0012's control-character/injection guard.
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in raw_value):
        return False
    return bool(_CANONICAL_UUIDV7_PATTERN.fullmatch(raw_value))


def generate_correlation_id() -> CorrelationId:
    """Generate a new platform-controlled correlation identifier.

    Uses the standard library's concurrency-safe uuid7 generator, which
    has no telemetry/network/database dependency (ADR-0012 Section 2).
    """
    return CorrelationId(str(uuid.uuid7()))


def normalize_correlation_id(raw_header_value: str | None) -> CorrelationNormalizationResult:
    """Normalize one raw Correlation-Id header value per ADR-0012.

    `raw_header_value` is intentionally the only input -- callers must not
    pass the raw value anywhere else (logs, traces, persistence) before or
    instead of calling this function.
    """
    if raw_header_value is not None and _is_valid_canonical_uuidv7(raw_header_value):
        return CorrelationNormalizationResult(
            effective_correlation_id=CorrelationId(raw_header_value), was_generated=False
        )
    return CorrelationNormalizationResult(
        effective_correlation_id=generate_correlation_id(), was_generated=True
    )
