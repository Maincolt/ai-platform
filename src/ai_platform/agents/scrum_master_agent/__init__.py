"""Scrum Master Agent module (ADR-0026, ADR-0028).

ADR-0026 Phase 2: the platform's first Agent that is not driven by a
Workflow submission. Instead of consuming `ExecuteTask` commands, it
wakes up on its own schedule (`PeriodicService`,
`src/ai_platform/runtime/lifecycle.py`), fetches the same live GitHub
Projects v2 board `scrum_status_agent` (ADR-0027) reads, and -- bounded
by a fixed three-action allowlist, a daily action/spend cap, a
platform-wide kill switch, and a durable audit trail -- takes real,
autonomous write actions with no per-action human approval, per the
narrow `SECURITY.md` exception ADR-0026 established.
"""
