"""Assignment Route Agent module (ADR-0023).

The platform's eighth capability, `assignment.route`: a bounded free-text
assignment description in, a bounded list of capability recommendations
out (`{capability, rationale}`, never dispatched automatically), via the
same technology-neutral AI Router port every other AI-backed capability
uses. Not one of ADR-0018 Decision 2's twelve personas -- a new triage
capability that names which of the team's specialists should look at an
assignment, rather than reviewing content itself. The actual fan-out
across recommended capabilities happens outside the platform runtime
(`infrastructure/compose/scripts/submit-assignment.py`), not here -- this
Agent only makes the recommendation, exactly like every other
bounded-advisory capability makes findings, never applying anything
automatically.
"""
