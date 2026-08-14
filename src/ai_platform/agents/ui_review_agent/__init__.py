"""UI Review Agent module (ADR-0019).

The platform's third capability and third AI-backed one, `ui.review`: a
fixed, hardcoded web page (the platform's own dashboard) reviewed for
UI/UX/accessibility/console-error problems. Structured identically to
`ai_platform.agents.review_agent` at the platform-boundary level (same
Registry binding shape, same command/event contract family, same durable
provider-call claim model, ADR-0014 Section 5/ADR-0016) with one addition:
before the single AI Router call, this Agent performs a deterministic,
read-only Playwright capture step (`capture.py`) to produce the page
signals the model reviews -- see `agent.py` for the full lifecycle, and
ADR-0019 Decision 4 for why the review target is hardcoded rather than
caller-supplied.
"""
