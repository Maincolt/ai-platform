"""Unit tests for the deterministic text.word-count capability (Section 14)."""

from __future__ import annotations

import pytest

from ai_platform.agents.test_agent.capability import compute_word_count


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("the quick brown fox", 4),
        ("", 0),
        ("   ", 0),
        ("single", 1),
        ("  leading and trailing spaces  ", 4),
        ("multiple   internal    spaces", 3),
        ("tabs\tand\tnewlines\nhere", 4),
        ("\n\n\t  \n", 0),
        ("word\u00a0with\u00a0nbsp", 3),  # Python's str.isspace() treats NBSP as whitespace
        ("word\u2003with\u2003em-space", 3),  # em space is also Unicode whitespace
    ],
)
def test_compute_word_count(text: str, expected: int) -> None:
    assert compute_word_count(text) == expected


def test_compute_word_count_performs_no_trimming_or_normalization() -> None:
    # The exact original text is not mutated by this function -- only counted.
    text = "  Café naïve  "
    assert compute_word_count(text) == 2
