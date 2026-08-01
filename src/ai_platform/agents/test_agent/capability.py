"""The deterministic text.word-count capability (Section 14).

word_count is the number of maximal nonempty text segments separated by
Unicode whitespace. No trimming, Unicode normalization, or text mutation
is performed beyond what str.split() already does: Python's default
str.split() (no separator argument) splits on runs of Unicode whitespace
and discards empty segments, which is exactly this semantic.
"""

CAPABILITY_NAME = "text.word-count"
CAPABILITY_VERSION = "1.0"


def compute_word_count(text: str) -> int:
    """Return the deterministic word count for `text`."""
    return len(text.split())
