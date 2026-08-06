"""The `text.summarize` capability identity (ADR-0014 Section 5).

No pure compute function here, unlike `text.word-count`'s
`compute_word_count`: the "computation" is a synchronous call through the
AI Router port to a non-deterministic external provider, which is not a
pure function and does not belong in a capability module imported for its
determinism. That call lives in `agent.py`, alongside the durable claim
and outcome-commit orchestration it requires.
"""

CAPABILITY_NAME = "text.summarize"
CAPABILITY_VERSION = "1.0"
