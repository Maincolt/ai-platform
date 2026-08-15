"""The `technical.review` capability identity (ADR-0022).

No pure compute function here, matching `data_analysis_agent.capability`:
the "computation" is a synchronous call through the AI Router port to a
non-deterministic external provider, followed by parsing its response
into a structured findings list -- neither belongs in a capability module
imported for its determinism. Both live in `agent.py`, alongside the
durable claim and outcome-commit orchestration they require.
"""

CAPABILITY_NAME = "technical.review"
CAPABILITY_VERSION = "1.0"
