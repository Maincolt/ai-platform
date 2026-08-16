"""The `scrum.status` capability identity (ADR-0027).

No pure compute function here, matching `ui_review_agent.capability`: the
"computation" is a read-only external fetch followed by a synchronous
call through the AI Router port to a non-deterministic external
provider, then parsing its response into a structured findings list --
none of that belongs in a capability module imported for its
determinism. All of it lives in `agent.py`/`board.py`, alongside the
durable claim and outcome-commit orchestration it requires.
"""

CAPABILITY_NAME = "scrum.status"
CAPABILITY_VERSION = "1.0"
