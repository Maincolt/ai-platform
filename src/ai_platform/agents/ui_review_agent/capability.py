"""The `ui.review` capability identity (ADR-0019).

No pure compute function here, matching `review_agent.capability`: the
"computation" is a deterministic Playwright capture followed by a
synchronous call through the AI Router port to a non-deterministic
external provider. Both live in `agent.py`/`capture.py`, alongside the
durable claim and outcome-commit orchestration they require.
"""

CAPABILITY_NAME = "ui.review"
CAPABILITY_VERSION = "1.0"
