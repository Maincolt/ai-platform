"""Review Agent module (ADR-0018).

The platform's third capability and second AI-backed one, `code.review`:
a bounded diff/patch in, a bounded list of advisory review findings out
(never applied automatically), via the same technology-neutral AI Router
port `summarize_agent` uses. Structured identically to
`ai_platform.agents.summarize_agent` at the platform-boundary level (same
Registry binding shape, same command/event contract family, same durable
provider-call claim model for the same reason -- ADR-0014 Section 5, ADR
-0016) with one addition: the provider's raw text response must parse
into a structured findings list before it is a valid completion (see
`agent.py`), since `result_data` here is not a passthrough string.
"""
