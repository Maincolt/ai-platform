"""Unit tests for accepted-request identity, evidence, and fingerprint comparison."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from ai_platform.orchestrator.domain.accepted_request import (
    AcceptanceEvidence,
    AcceptedRequestKey,
    FingerprintComparison,
    compare_fingerprint,
)
from ai_platform.shared.identifiers import (
    ActorId,
    IdempotencyScopeId,
    OwnerSubjectId,
    RequestId,
)

NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)


def _key() -> AcceptedRequestKey:
    return AcceptedRequestKey(
        environment="local-development",
        operation="workflow.submit",
        idempotency_scope_id=IdempotencyScopeId("scope-1"),
        request_id=RequestId("019fbdd6-ab3d-77aa-8e61-4c3903e582ad"),
    )


def _evidence(fingerprint: str = "aaa") -> AcceptanceEvidence:
    return AcceptanceEvidence(
        acceptance_actor_id=ActorId("actor-1"),
        accepted_owner_subject_id=OwnerSubjectId("owner-1"),
        fingerprint=fingerprint,
        fingerprint_policy_version="1.0",
        accepted_at=NOW,
    )


def test_accepted_request_key_is_frozen() -> None:
    key = _key()
    with pytest.raises(dataclasses.FrozenInstanceError):
        key.request_id = RequestId("changed")  # type: ignore[misc]


def test_acceptance_evidence_is_frozen() -> None:
    evidence = _evidence()
    with pytest.raises(dataclasses.FrozenInstanceError):
        evidence.fingerprint = "changed"  # type: ignore[misc]


def test_compare_fingerprint_new_when_no_existing_mapping() -> None:
    assert compare_fingerprint(None, "aaa") == FingerprintComparison.NEW


def test_compare_fingerprint_equivalent_replay_when_same() -> None:
    assert compare_fingerprint("aaa", "aaa") == FingerprintComparison.EQUIVALENT_REPLAY


def test_compare_fingerprint_conflict_when_different() -> None:
    assert compare_fingerprint("aaa", "bbb") == FingerprintComparison.FINGERPRINT_CONFLICT


def test_same_request_id_in_different_scopes_is_a_different_key() -> None:
    scope_a = dataclasses.replace(_key(), idempotency_scope_id=IdempotencyScopeId("scope-a"))
    scope_b = dataclasses.replace(_key(), idempotency_scope_id=IdempotencyScopeId("scope-b"))

    assert scope_a != scope_b
    assert scope_a.request_id == scope_b.request_id
