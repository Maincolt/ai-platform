"""Scrum Status Agent module (ADR-0027).

The platform's tenth capability, `scrum.status`: ADR-0026's Phase 1 --
a bounded, read-only fetch of live GitHub Projects v2 board state in, a
bounded list of advisory status findings out (never applied
automatically), via the same technology-neutral AI Router port
`summarize_agent`/`review_agent` use. Structurally identical to
`ai_platform.agents.ui_review_agent` -- the only difference is the fetch
target (an authenticated GitHub GraphQL API call instead of an
unauthenticated Playwright page load) and the findings' locator key
(`location` instead of `area`). No tool-calling, no write access, no new
architecture.
"""
