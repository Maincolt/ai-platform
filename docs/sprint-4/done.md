# Sprint 4 — Done

## What Was Built

**Test Agent** (`src/ai_platform/agents/test_agent/`):
- `capability.py` — `compute_word_count` (deterministic `text.word-count`).
- `execution_context.py` — `ExecuteTaskContext`.
- `ids.py` — Agent-owned `IdentifierFactory` Protocol.
- `errors.py` — `CapabilityMismatchError`, `CommandIdentityConflictError`, `CommandIntegrityError`.
- `messages.py` — `build_task_completed_payload`, `build_task_failed_payload`.
- `readiness.py` — Agent-owned `ReadinessClassification`, `AgentReadiness`, `evaluate_readiness`.
- `agent.py` — `TestAgent`: the full Section 14/ADR-0007 Section 4 lifecycle (receipt-first idempotency, capability validation, deadline check, deterministic execution, atomic receipt/outcome/event-outbox construction).

**Architectural correction** (discovered while building the above):
- Moved `identifiers.py` from `orchestrator/domain/` to `shared/` — these are envelope-level identifiers used by both the Orchestrator and Agent sides.
- Split the former `orchestrator/domain/recovery.py` into three correctly-owned locations: `orchestrator/domain/recovery.py` (Orchestrator-only: `OrchestratorOutboxRecord`, `OrchestratorInboxRecord`), `agents/domain/outcomes.py` (Agent-only: `AgentCompletedReceipt`, `AgentEventOutboxRecord`), and `shared/` (`PublicationState` in `shared/recovery.py`, `AgentOutcome` in `shared/outcomes.py` since it crosses the Agent/Orchestrator boundary by design).
- Changed `AgentReceiptRepositoryPort.create_or_resolve` to return `tuple[AgentCompletedReceipt, bool]` (an explicit `is_new` flag), fixing a real correctness gap where value-equality could not distinguish "I created it" from "a concurrent writer already created an identical one."

**Tests:**
- `tests/unit/agents/test_agent/` — 14 tests (capability edge cases including Unicode whitespace, readiness classification).
- `tests/component/agents/test_agent/test_agent_lifecycle.py` — 7 tests (first execution, duplicate resolution, identity/integrity conflicts, deadline-before-execution, capability mismatch, concurrent-duplicate race).

165 tests total (up from 144), all passing. Clean on `ruff format`, `ruff check`, and `basedpyright` (strict), with zero warnings.

## What's NOT Done

- No Event Bus consumer or real message delivery — Phase 6.
- Lifecycle interruption (shutdown/restart/rebalance cancellation) — deferred to Phase 6 (see consilium disagreement 2).
- Workflow API implementation (Phase 5) and concrete adapters (Phase 6) remain out of scope.

## Files Changed/Created

- `docs/sprint-4/{consilium.md,plan.md,progress.md,done.md}` — sprint docs.
- `src/ai_platform/agents/test_agent/*.py` — 7 new modules.
- `src/ai_platform/agents/domain/{__init__.py,outcomes.py}` — 2 new modules.
- `src/ai_platform/shared/{identifiers.py,recovery.py,outcomes.py}` — moved/new shared modules.
- `src/ai_platform/orchestrator/domain/recovery.py` — reduced to Orchestrator-owned types only.
- `src/ai_platform/ports/persistence/{agent.py,outbox.py}` — updated imports and the `create_or_resolve` signature.
- `src/ai_platform/orchestrator/application/terminal.py` — updated imports.
- `tests/unit/agents/test_agent/*.py`, `tests/component/agents/test_agent/*.py` — new test modules.
- Various Sprint 2/3 test files — updated imports for the moved types.

## Manual Setup Required

None — no new environment variables, secrets, or external services.

## Known Issues

- None filed. See `docs/qa/sprint-4-signoff.md` for the explicit "no
  blockers" QA result.
