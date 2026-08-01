"""Unit tests for ADR-0012 correlation normalization."""

from __future__ import annotations

from ai_platform.api.correlation import normalize_correlation_id

VALID_UUIDV7 = "019fbdd6-ab3d-77aa-8e61-4c3903e582ad"


def test_missing_header_generates_a_value() -> None:
    result = normalize_correlation_id(None)
    assert result.was_generated is True
    assert result.effective_correlation_id is not None


def test_valid_header_is_preserved() -> None:
    result = normalize_correlation_id(VALID_UUIDV7)
    assert result.was_generated is False
    assert str(result.effective_correlation_id) == VALID_UUIDV7


def test_malformed_header_is_discarded_and_generated() -> None:
    result = normalize_correlation_id("not-a-uuid")
    assert result.was_generated is True
    assert str(result.effective_correlation_id) != "not-a-uuid"


def test_oversized_header_is_discarded_and_generated() -> None:
    oversized = "a" * 500
    result = normalize_correlation_id(oversized)
    assert result.was_generated is True
    assert str(result.effective_correlation_id) != oversized


def test_control_character_header_is_discarded_and_generated() -> None:
    injected = VALID_UUIDV7[:-1] + "\n"
    result = normalize_correlation_id(injected)
    assert result.was_generated is True
    assert "\n" not in str(result.effective_correlation_id)


def test_uppercase_uuid_is_not_canonical_and_is_discarded() -> None:
    # ADR-0004 requires lowercase canonical form; uppercase is a different
    # (noncanonical) representation and must not be silently accepted.
    result = normalize_correlation_id(VALID_UUIDV7.upper())
    assert result.was_generated is True


def test_generated_values_are_unique() -> None:
    first = normalize_correlation_id(None)
    second = normalize_correlation_id(None)
    assert first.effective_correlation_id != second.effective_correlation_id
