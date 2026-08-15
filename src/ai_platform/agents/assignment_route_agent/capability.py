"""The `assignment.route` capability identity (ADR-0023).

No pure compute function here, matching every other AI-backed capability
module: the "computation" is a synchronous call through the AI Router
port to a non-deterministic external provider, followed by parsing its
response into a structured recommendation list -- neither belongs in a
capability module imported for its determinism. Both live in `agent.py`,
alongside the durable claim and outcome-commit orchestration they
require.
"""

CAPABILITY_NAME = "assignment.route"
CAPABILITY_VERSION = "1.0"
