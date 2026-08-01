# Sprint 4 — Progress Tracker

> If context overflows, start a new chat/session:
> "Read PROJECT_BRIEF.md and docs/sprint-4/progress.md.
>  Continue Sprint 4 (Vertical Slice 01, Phase 4 only) from where it left off."

## Task Status

| # | Task | Owner | Status | Notes |
|---|------|-------|--------|-------|
| 1 | Deterministic capability | Sage | ✅ Done | `capability.py`: `compute_word_count` (`len(text.split())`) |
| 2 | Execution context | Sage | ✅ Done | `execution_context.py`: `ExecuteTaskContext` |
| 3 | Agent-owned identifier factory | Sage | ✅ Done | `ids.py`: local `IdentifierFactory` Protocol |
| 4 | Agent-owned errors | Sage | ✅ Done | `errors.py`: `CapabilityMismatchError`, `CommandIdentityConflictError`, `CommandIntegrityError` |
| 5 | Terminal event payload builders | Sage | ✅ Done | `messages.py`: `build_task_completed_payload`, `build_task_failed_payload` |
| 6 | Readiness boundary | Sage | ✅ Done | `readiness.py`: Agent-owned `ReadinessClassification`, `AgentReadiness`, `evaluate_readiness` |
| 7 | Test Agent lifecycle | Sage | ✅ Done | `agent.py`: `TestAgent` implementing the Section 14 ordering |
| 8 | Capability unit tests | Ivy | ✅ Done | `tests/unit/agents/test_agent/test_capability.py`: 11 tests |
| 9 | Readiness unit tests | Ivy | ✅ Done | `tests/unit/agents/test_agent/test_readiness.py`: 3 tests |
| 10 | Lifecycle component tests | Ivy | ✅ Done | `tests/component/agents/test_agent/test_agent_lifecycle.py`: 7 tests |

## Bugs Found

| # | Description | Severity | Status | Fix |
|---|-------------|----------|--------|-----|
| 1 | Architecture leak: Agent-owned types (`AgentCompletedReceipt`, `AgentOutcome`, `AgentEventOutboxRecord`) and shared identifiers were physically defined under `orchestrator/domain/`, which the Test Agent would have had to import from directly, violating Agent/Orchestrator deployable independence | major (architectural) | fixed | Moved `identifiers.py` to `shared/`; split `recovery.py` into `orchestrator/domain/recovery.py` (Orchestrator-owned), `agents/domain/outcomes.py` (Agent-owned), and `shared/recovery.py` (`PublicationState`) / `shared/outcomes.py` (`AgentOutcome`, which crosses the boundary by design) |
| 2 | `AgentReceiptRepositoryPort.create_or_resolve` could not reliably distinguish "created new" from "resolved a pre-existing but content-identical" receipt using value equality alone, since two independently constructed receipts for the same real command are equal by value even when one is a concurrent-race loser | major (port design) | fixed | Changed the port to return `tuple[AgentCompletedReceipt, bool]` (`is_new` flag), matching the pattern `AcceptedRequestRepositoryPort` already used; updated `TestAgent` and all in-memory fakes accordingly |
| 3 | `pytest` emitted `PytestCollectionWarning` for `TestAgent`/`TestAgentDisposition`/`TestAgentResult` since their names match pytest's default test-class discovery pattern | minor (noise only) | fixed | Added `__test__ = False` to each class, the documented pytest mechanism for this exact situation |

## Notes

- Sprint scope confirmed via [team consilium](consilium.md): the
  domain/application-level portion of Phase 4 only; lifecycle
  interruption (shutdown/restart/rebalance) is explicitly deferred to
  Phase 6, where a real asyncio consumer exists to interrupt.
- **Validation performed (2026-08-01):** `uv run ruff format --check .`,
  `uv run ruff check .`, `uv run basedpyright` (strict mode),
  `uv run pytest -v` — all passed (165/165 tests, 0 lint findings, 0 type
  errors, 0 warnings) after fixing the two architectural/design issues
  above, discovered by a genuine test failure rather than assumed.
