# Sprint 9 — AI Router and the First AI-Backed Agent

> Sprint goal: implement ADR-0014 and ADR-0015.
> Branch: `feature/sprint-9-ai-router-and-summarize-agent`
> Scope authority: [ADR-0014](../architecture/decisions/ADR-0014-ai-router-and-first-ai-backed-agent.md),
> [ADR-0015](../architecture/decisions/ADR-0015-generic-capability-result-model.md)

## Context

This is new work beyond Vertical Slice 01's eight-phase plan (which
completed at Sprint 8) — the first capability that isn't
`text.word-count`, and the first Agent that calls a real external
provider. Two Accepted ADRs govern it. ADR-0015 must land first and be
proven not to regress `text.word-count`, since ADR-0014's new capability
depends on the generic result model ADR-0015 defines.

## Workstreams and sequencing

1. **Generic result model (ADR-0015)** — done first, alone. Touches
   already-tested code (`Workflow` aggregate, `AgentOutcome`, both
   persistence schemas, three wire contracts), so it is implemented and
   the full existing test suite is re-run against `text.word-count`
   before any new capability code is written, per ADR-0015 Section 5.
2. **AI Router** (ADR-0014 Sections 1–3) — `AIRouterPort`, Anthropic and
   OpenAI adapters, configuration-driven routing/fallback, durable
   redacted usage tracking. Independent of workstream 3; can proceed in
   parallel with it once workstream 1 is merged.
3. **Capability-scoped Kafka routing** (ADR-0014 Section 6) — extends
   `KafkaTopicMapping` so `task-commands` is capability-scoped at the
   physical-topic level. Independent of workstream 2; can proceed in
   parallel with it.
4. **`text.summarize` Agent** (ADR-0014 Sections 4–5) — depends on
   workstreams 1–3 all being available: the generic result model, the AI
   Router, and capability-scoped topic routing.
5. **Runtime composition, Registry, secrets, and Compose topology** —
   wires everything into `platform`/a new `summarize-agent` process,
   following the same pattern `test-agent` already established.
6. **Tests and documentation.**

## Scope

**In scope:**

- Everything ADR-0014 and ADR-0015 decided.
- Unit and component test coverage for all new/changed code, using fake
  `AIRouterPort` implementations (no real provider credentials required
  for the default `uv run pytest` suite).
- Real-service validation of the generic result model against
  `text.word-count` (ADR-0015 Section 5) via the existing `external_service`
  suite and manual real-topology validation, following the pattern
  Sprints 6–7 established.

**Explicitly out of scope** (per ADR-0014 Section 9, unchanged):

- Real-provider (Anthropic/OpenAI) end-to-end validation with live API
  keys. This repository has no provider credentials available in this
  environment; real-provider calls are exercised through fake/contract
  tests only unless and until the repository owner supplies credentials
  for a follow-up validation pass. This is stated plainly rather than
  simulated or assumed to work.
- Cost-based/dynamic routing, billing integration, budget enforcement.
- Streaming completions, Orchestrator-level AI Router invocation,
  open-ended chat/Q&A, Skills as a distinct layer.
- Resolving ADR-0014's five recorded open questions (reconciliation
  window, exact retry budgets, approved-model list, etc.) beyond what is
  needed to ship a working, safe default.

## Acceptance criteria

- [ ] `uv run ruff format --check .` succeeds.
- [ ] `uv run ruff check .` succeeds.
- [ ] `uv run basedpyright` succeeds in strict mode.
- [ ] `uv run pytest -q` succeeds, including updated `text.word-count`
      coverage against the generalized result model.
- [ ] The `external_service` suite's `text.word-count` coverage
      (`test_event_bus_delivery.py`, `test_concurrency.py`,
      `test_recovery.py`, etc.) is re-run against the migrated schema and
      passes, as ADR-0015 Section 5's concrete no-regression evidence.
- [ ] `text.summarize` is demonstrated working end-to-end against a fake
      `AIRouterPort` at minimum; real-provider validation is explicitly
      marked as not performed if no credentials are available, per scope
      above.
- [ ] Sprint completion and QA documents distinguish demonstrated behavior
      from deferred/unvalidated behavior and make no production-readiness
      claim.

## Out of scope

See "Explicitly out of scope" above.
