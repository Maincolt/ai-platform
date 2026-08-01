# Sprint 3 — Progress Tracker

> If context overflows, start a new chat/session:
> "Read PROJECT_BRIEF.md and docs/sprint-3/progress.md.
>  Continue Sprint 3 (Vertical Slice 01, Phase 3 only) from where it left off."

## Task Status

| # | Task | Owner | Status | Notes |
|---|------|-------|--------|-------|
| 1 | Capability Registry module | Dash (background sub-agent) | ✅ Done | `declarations.py`, `snapshot.py`, `availability.py`, `selection.py` — matched the interface spec exactly; built fully in parallel with tasks 3-6 |
| 2 | Registry unit tests | Dash (background sub-agent) | ✅ Done | `tests/unit/orchestrator/registry/`: 41 tests (declarations, snapshot validation, availability freshness, selection eligibility/ambiguity) |
| 3 | Nonterminal-workflow recovery port | Sage | ✅ Done | `ports/persistence/recovery.py`: `NonterminalWorkflowQueryPort` |
| 4 | Submission orchestration service | Sage | ✅ Done | `application/submission.py`: `SubmissionOrchestrator`, `SubmissionRequest`, `SubmissionDisposition`, `SubmissionResult`; `application/messages.py` for the ExecuteTask payload; `application/candidate_selection.py` for the Registry seam; `application/ids.py` for identifier generation |
| 5 | Terminal event processing service | Sage | ✅ Done | `application/terminal.py`: `TerminalEventProcessor` |
| 6 | Deadline reconciliation service | Sage | ✅ Done | `application/deadline.py`: `DeadlineReconciler` |
| 7 | Application-service component tests | Ivy | ✅ Done | `tests/component/orchestrator/test_application_services.py`: 11 tests, all against a fake `CandidateSelectorPort` (Registry stand-in until task 8) |
| 8 | Integration of Registry + application services | Sage | ✅ Done | `application/registry_candidate_selector.py` (`RegistryCandidateSelector` adapter); `tests/component/orchestrator/test_registry_integration.py`: 4 end-to-end tests using the real Registry, including a test proving the deadline reconciler safely no-ops against an already-completed workflow |
| 9 | Sprint coordination | Remy | ✅ Done | Scope held to Phase 3 only; parallel work streams integrated cleanly on first attempt (interface spec held exactly) |

## Bugs Found

| # | Description | Severity | Status | Fix |
|---|-------------|----------|--------|-----|
| _none yet_ | | | | |

## Notes

- Sprint scope confirmed via [team consilium](consilium.md): all of Phase 3,
  split into a parallel background sub-agent (Registry) and main-thread
  work (application services), integrated in Phase B.
- Full outbox/inbox recovery-query capabilities (not-attempted, unknown,
  claimed-expired) are explicitly deferred to Phase 6 (adapter-dependent);
  only the narrow deadline-reconciliation query is in scope.
- `now` is always an explicit parameter in Registry/application-service
  code, never read from a wall clock.
- **Parallel execution worked cleanly on the first attempt.** The
  background sub-agent (model: claude-opus-4.8) built the Registry module
  against the fixed interface spec in `docs/sprint-3/plan.md` while the
  main thread built the application services against the same spec, using
  a local `CandidateSelectorPort` fake as a stand-in. No signature
  mismatches were found at integration time (task 8) — the interface spec
  written up front was sufficient.
- **Validation performed (2026-08-01):** `uv run ruff format --check .`,
  `uv run ruff check .`, `uv run basedpyright` (strict mode),
  `uv run pytest -v` — all passed (143/143 tests: 52 contract + 24 domain
  unit + 41 registry unit + 11 persistence-port component + 11
  application-service component + 4 registry-integration component, 0
  lint findings, 0 type errors).
