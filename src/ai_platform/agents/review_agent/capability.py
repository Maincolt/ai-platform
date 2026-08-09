"""The `code.review` capability identity (ADR-0018 Decision 3).

No pure compute function here, matching `summarize_agent.capability`, not
`test_agent.capability`: the "computation" is a synchronous call through
the AI Router port to a non-deterministic external provider, followed by
parsing its response into a structured findings list -- neither belongs
in a capability module imported for its determinism. Both live in
`agent.py`, alongside the durable claim and outcome-commit orchestration
they require.
"""

CAPABILITY_NAME = "code.review"
CAPABILITY_VERSION = "1.0"
