"""Summarize Agent module (Sprint 9 / ADR-0014).

The first AI-backed capability, `text.summarize`: bounded input text in,
a bounded provider-generated summary out, via the technology-neutral AI
Router port (`ai_platform.ports.ai_router`). Structured identically to
`ai_platform.agents.test_agent` at the platform-boundary level (same
Registry binding shape, same command/event contract family, same
receipt-first idempotency lifecycle), but with a non-deterministic,
provider-backed execution step in place of the deterministic word-count
computation -- see ADR-0014 Section 5 for the durable claim/unknown-outcome
model this requires that `text.word-count` does not.
"""
