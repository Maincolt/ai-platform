# Sprint 2 — Progress Tracker

> If context overflows, start a new chat/session:
> "Read PROJECT_BRIEF.md and docs/sprint-2/progress.md.
>  Continue Sprint 2 (Vertical Slice 01, Phase 2 only) from where it left off."

## Task Status

| # | Task | Owner | Status | Notes |
|---|------|-------|--------|-------|
| 1 | Workflow state and identifiers | Sage | ✅ Done | `states.py` (5-state enum + legal-transition table), `identifiers.py` (NewType aliases) |
| 2 | Accepted-request identity and evidence | Sage | ✅ Done | `accepted_request.py`: frozen `AcceptedRequestKey`/`AcceptanceEvidence`, `FingerprintComparison` enum + `compare_fingerprint` |
| 3 | Selection intent | Sage | ✅ Done | `selection.py`: frozen `SelectionIntent` |
| 4 | Task and task attempt | Sage | ✅ Done | `task.py`: `Task`, `TaskAttempt` (enforces `attempt_number == 1`) |
| 5 | Transition history | Sage | ✅ Done | `history.py`: frozen `TransitionRecord` |
| 6 | Workflow aggregate | Sage | ✅ Done | `workflow.py`: `Workflow` enforcing the Section 9 state table via `_transition`; `errors.py` for stable domain exceptions |
| 7 | Result and failure | Sage | ✅ Done | `results.py`: `WorkflowResult`, `WorkflowFailure` |
| 8 | Audit record | Sage | ✅ Done | `audit.py`: frozen `AuditRecord` |
| 9 | Inbox/outbox/receipt records | Sage | ✅ Done | `recovery.py`: outbox/inbox/receipt/outcome records, `PublicationState` enum |
| 10 | Persistence ports | Sage | ✅ Done | 7 `Protocol` modules under `src/ai_platform/ports/persistence/`: workflow, accepted_request, task, outbox, orchestrator_inbox, agent, audit |
| 11 | Domain unit tests | Ivy | ✅ Done | `tests/unit/orchestrator/`: 24 tests (workflow state machine, accepted-request, value objects) |
| 12 | Port contract tests with in-memory fakes | Ivy | ✅ Done | `tests/component/orchestrator/test_persistence_ports.py`: 11 tests with in-memory fakes covering all 7 ports (workflow, accepted-request, task, task-attempt, orchestrator outbox, agent event outbox, agent receipt/outcome, orchestrator inbox) |
| 13 | Sprint coordination | Remy | ✅ Done | Scope held to Phase 2 only; ports remain `Protocol`s; no adapters, no Phase 3+ behavior |

## Bugs Found

| # | Description | Severity | Status | Fix |
|---|-------------|----------|--------|-----|
| 1 | Initial `InMemoryWorkflowRepository` fake stored the live `Workflow` object by reference, so mutating the caller's object silently changed what appeared "durably stored," defeating the compare-and-set revision-conflict test | minor (test-fake only, no domain-code bug) | fixed | Fake now stores a `copy.deepcopy` snapshot per save and tracks `_stored_revisions` separately from any live object the caller continues to mutate |

## Notes

- Sprint scope confirmed via [team consilium](consilium.md): all of Phase 2,
  as pure domain code and `Protocol` ports, no adapters/no I/O.
- Deadline reconciler *process* and HTTP-status mapping for
  replay/conflict outcomes are explicitly out of scope (Phase 3/5).
- **Validation performed (2026-08-01):** `uv run ruff format --check .`,
  `uv run ruff check .`, `uv run basedpyright` (strict mode),
  `uv run pytest -v` — all passed (87/87 tests, 0 lint findings, 0 type
  errors).
- Component tests (task 12) now cover all 7 persistence ports with
  in-memory fakes, including a genuine compare-and-set/stale-revision
  scenario for the workflow repository (two independent copies of the same
  workflow racing to commit a transition).
