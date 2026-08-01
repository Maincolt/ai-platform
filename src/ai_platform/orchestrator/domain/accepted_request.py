"""Accepted-request identity and evidence.

Per vertical-slice-01.md Section 6 and ADR-0011: the database-enforced key
is (environment, operation, idempotency_scope_id, request_id). Global
lookup or uniqueness by request_id alone is prohibited.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ai_platform.shared.identifiers import (
    ActorId,
    IdempotencyScopeId,
    OwnerSubjectId,
    RequestId,
)


@dataclass(frozen=True, slots=True)
class AcceptedRequestKey:
    """The complete composite accepted-request identity (ADR-0011 Section 1).

    All four fields are required for identity and uniqueness. `environment`
    and `operation` are trusted configuration, never client input.
    """

    environment: str
    operation: str
    idempotency_scope_id: IdempotencyScopeId
    request_id: RequestId


@dataclass(frozen=True, slots=True)
class AcceptanceEvidence:
    """Immutable actor/owner/fingerprint evidence recorded at first acceptance.

    `accepted_owner_subject_id` is the owner intent authorized at original
    acceptance. This slice has no ownership-transfer API (Section 21
    deferral), so the current owner is always the accepted owner.
    """

    acceptance_actor_id: ActorId
    accepted_owner_subject_id: OwnerSubjectId
    fingerprint: str
    fingerprint_policy_version: str
    accepted_at: datetime


class FingerprintComparison(Enum):
    """Outcome of comparing a submission's fingerprint to an existing mapping."""

    NEW = "NEW"
    EQUIVALENT_REPLAY = "EQUIVALENT_REPLAY"
    FINGERPRINT_CONFLICT = "FINGERPRINT_CONFLICT"


def compare_fingerprint(
    existing_fingerprint: str | None,
    submitted_fingerprint: str,
) -> FingerprintComparison:
    """Classify a submission against any existing accepted-request mapping.

    Per Section 6: no existing mapping is a new acceptance; the same
    fingerprint is an equivalent replay; a different fingerprint is a
    conflict. Mapping this outcome to an HTTP status (200/202/409/404) is
    Workflow API behavior (Phase 5), not domain logic.
    """
    if existing_fingerprint is None:
        return FingerprintComparison.NEW
    if existing_fingerprint == submitted_fingerprint:
        return FingerprintComparison.EQUIVALENT_REPLAY
    return FingerprintComparison.FINGERPRINT_CONFLICT
