# Sprint 2 — Done

## What Was Built

- `src/ai_platform/orchestrator/domain/` — pure Python domain model:
  - `identifiers.py` — `NewType` aliases for all workflow-related IDs.
  - `states.py` — `WorkflowState` enum and the Section 9 legal-transition table.
  - `errors.py` — `IllegalTransitionError`, `TerminalWorkflowError`.
  - `accepted_request.py` — frozen `AcceptedRequestKey`, `AcceptanceEvidence`,
    `FingerprintComparison` enum, `compare_fingerprint`.
  - `selection.py` — frozen `SelectionIntent`.
  - `task.py` — `Task`, `TaskAttempt` (enforces `attempt_number == 1`).
  - `history.py` — frozen `TransitionRecord`.
  - `results.py` — `WorkflowResult`, `WorkflowFailure`.
  - `audit.py` — frozen `AuditRecord`.
  - `recovery.py` — outbox/inbox/receipt/outcome records, `PublicationState`.
  - `workflow.py` — the `Workflow` aggregate enforcing the full Section 9
    state machine (legal transitions only, incrementing revision, append-only
    history, terminal immutability).
- `src/ai_platform/ports/persistence/` — 7 capability-oriented `Protocol`
  interfaces per ADR-0006 Section 4: `workflow.py`, `accepted_request.py`,
  `task.py`, `outbox.py` (Orchestrator + Agent event outbox), `agent.py`
  (receipt + outcome), `orchestrator_inbox.py`, `audit.py`.
- `tests/unit/orchestrator/` — 21 unit tests: full happy-path and
  fail-path state transitions, every illegal-edge case, terminal
  immutability, duplicate/late-event rejection, accepted-request identity
  immutability, fingerprint comparison outcomes, and value-object
  invariants (`attempt_number`, `word_count >= 0`, exactly-one
  success/failure on `AgentOutcome`).
- `tests/component/orchestrator/test_persistence_ports.py` — 11 component
  tests with in-memory fakes proving all 7 ports are implementable and
  behaviorally correct, including a genuine compare-and-set/stale-revision
  race for the workflow repository and claim/publish/acknowledge cycles
  with fencing-token rejection for both outbox ports.

## What's NOT Done

- No Orchestrator process, Capability Registry, Test Agent, Workflow API,
  or concrete persistence/Event Bus adapters — all deferred to Phases 3-6
  by design (see `docs/sprint-2/plan.md`, "What's NOT in This Sprint").
- The deadline-reconciler *process* is not implemented; the aggregate only
  enforces that a workflow accepts at most one terminal transition, which
  is sufficient for a future reconciler to rely on.
- Mapping fingerprint-comparison/replay outcomes to HTTP status codes is
  explicitly deferred to the Workflow API (Phase 5).

## Files Changed/Created

- `docs/sprint-2/{consilium.md,plan.md,progress.md,done.md}` — sprint docs.
- `src/ai_platform/orchestrator/domain/*.py` — 11 new modules.
- `src/ai_platform/ports/persistence/*.py` — 7 new port modules (the
  package `__init__.py` docstring was also updated to describe the ports).
- `tests/unit/orchestrator/*.py` — 3 new test modules (24 tests).
- `tests/component/orchestrator/test_persistence_ports.py` — 1 new test
  module (11 tests) with 7 in-memory fakes.

## Manual Setup Required

None — no new environment variables, secrets, or external services. Same
`uv sync` / `uv run pytest` workflow as Sprint 1.

## Known Issues

- None filed. See `docs/qa/sprint-2-signoff.md` for the explicit "no
  blockers" QA result.
