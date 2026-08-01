"""Unit tests for RFC 8785 request fingerprinting."""

from __future__ import annotations

from ai_platform.api.fingerprint import compute_fingerprint


def test_fingerprint_is_deterministic_for_identical_input() -> None:
    a = compute_fingerprint(
        text="hello world", capability_name="text.word-count", capability_version="1.0"
    )
    b = compute_fingerprint(
        text="hello world", capability_name="text.word-count", capability_version="1.0"
    )
    assert a == b


def test_fingerprint_changes_when_text_changes() -> None:
    a = compute_fingerprint(
        text="hello world", capability_name="text.word-count", capability_version="1.0"
    )
    b = compute_fingerprint(
        text="goodbye world", capability_name="text.word-count", capability_version="1.0"
    )
    assert a != b


def test_fingerprint_changes_when_capability_version_changes() -> None:
    a = compute_fingerprint(
        text="hello world", capability_name="text.word-count", capability_version="1.0"
    )
    b = compute_fingerprint(
        text="hello world", capability_name="text.word-count", capability_version="2.0"
    )
    assert a != b


def test_fingerprint_is_a_lowercase_hex_sha256_digest() -> None:
    digest = compute_fingerprint(
        text="hello", capability_name="text.word-count", capability_version="1.0"
    )
    assert len(digest) == 64
    assert digest == digest.lower()
    int(digest, 16)  # raises ValueError if not valid hex
