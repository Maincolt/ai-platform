# Sprint 3 — Done

## What Was Built

**Capability Registry** (`src/ai_platform/orchestrator/registry/`, built by
a background sub-agent against a fixed interface spec, in parallel with the
application services below):
- `declarations.py` — `CapabilityBinding` frozen dataclass.
- `snapshot.py` — `RegistryValidationError`, `RegistrySnapshot`,
  `load_registry_snapshot` (fail-closed duplicate/conflict rejection,
  tolerating disabled duplicates).
- `availability.py` — `AvailabilityClassification`, `AvailabilityObservation`,
  `AvailabilityPort` Protocol, `is_fresh` (READY-only, within TTL).
- `selection.py` — `NoEligibleAgentError`, `AmbiguousCandidateError`,
  `select_candidate` (exact ADR-0008 Section 5 compatibility matching,
  zero/one/many eligibility handling).

**Orchestrator application services** (`src/ai_platform/orchestrator/application/`,
built on the main thread in parallel with the Registry):
- `ids.py` — `IdentifierFactory` Protocol.
- `candidate_selection.py` — `CandidateSelectorPort`, `NoEligibleCandidateError`,
  `CandidateSelectionConfigurationError` (the Registry integration seam).
- `messages.py` — `build_execute_task_payload` (matches the Sprint 1
  `execute_task.schema.json` contract).
- `submission.py` — `SubmissionOrchestrator`: accepted-request arbitration
  first, Registry selection only for genuinely new requests, atomic
  workflow/task/attempt/history/outbox/audit construction.
- `terminal.py` — `TerminalEventProcessor`: inbox-disposition-first
  idempotency, then `complete`/`fail` via the Workflow aggregate.
- `deadline.py` — `DeadlineReconciler`: finds expired `DISPATCHED` attempts
  and applies `workflow.fail(..., cause="deadline_expired")`, relying on
  the Sprint 2 aggregate's terminal-exclusivity guarantee as the race-
  safety net.
- `registry_candidate_selector.py` — `RegistryCandidateSelector`: the
  integration adapter binding the real Registry to `CandidateSelectorPort`
  (task 8).

**New persistence port:** `ports/persistence/recovery.py` —
`NonterminalWorkflowQueryPort` (narrowly scoped to the deadline
reconciler's needs; broader recovery-query capabilities deferred to
Phase 6).

**Tests:**
- `tests/unit/orchestrator/registry/` — 41 tests (Registry module).
- `tests/component/orchestrator/test_application_services.py` — 11 tests
  (application services against a fake `CandidateSelectorPort`).
- `tests/component/orchestrator/test_registry_integration.py` — 4 tests
  (end-to-end: real Registry + real application services, including a
  test proving the deadline reconciler safely no-ops against an
  already-completed workflow).

143 tests total, all passing. Clean on `ruff format`, `ruff check`, and
`basedpyright` (strict).

## Parallel Execution Summary

This sprint used a background sub-agent (model: claude-opus-4.8) to build
the Capability Registry independently while the main thread built the
Orchestrator application services concurrently, both against a fixed
interface spec written up front in `docs/sprint-3/plan.md`. Integration
(task 8) required zero interface changes — the spec held exactly. This
validates the approach for future sprints with genuinely independent,
well-specified work streams.

## What's NOT Done

- No Test Agent, Workflow API, or concrete persistence/Event Bus adapters
  — Phases 4-6 remain out of scope (see `docs/sprint-3/plan.md`, "What's
  NOT in This Sprint").
- Broader outbox/inbox recovery-query capabilities (not-attempted,
  unknown, claimed-expired) are deferred to Phase 6 (adapter-dependent).
- Dynamic Agent registration/heartbeat remains out of scope for the whole
  vertical slice (ADR-0008).

## Files Changed/Created

- `docs/sprint-3/{consilium.md,plan.md,progress.md,done.md}` — sprint docs.
- `src/ai_platform/orchestrator/registry/*.py` — 4 new modules (background sub-agent).
- `src/ai_platform/orchestrator/application/*.py` — 7 new modules (main thread).
- `src/ai_platform/ports/persistence/recovery.py` — 1 new port module.
- `tests/unit/orchestrator/registry/*.py` — 4 new test modules (41 tests).
- `tests/component/orchestrator/test_application_services.py` — 1 new test module (11 tests).
- `tests/component/orchestrator/test_registry_integration.py` — 1 new test module (4 tests).

## Manual Setup Required

None — no new environment variables, secrets, or external services. Same
`uv sync` / `uv run pytest` workflow as prior sprints.

## Known Issues

- None filed. See `docs/qa/sprint-3-signoff.md` for the explicit "no
  blockers" QA result.
