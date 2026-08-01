# Sprint 4 — Test Agent

> Sprint Goal: Implement Vertical Slice 01, Phase 4: the built-in
> `text.word-count` capability, bounded lifecycle, capability/input
> validation, completed-receipt deduplication, outcome/event/outbox
> persistence, and a development readiness boundary — as pure Python
> domain/application code composed over the Phase 2 Agent-side ports. No
> Event Bus consumer, no concrete adapters (Phase 6).
> Branch: `feature/sprint-4-test-agent`
> Scope authority: [Vertical Slice 01, Section 20, Phase 4](../implementation/vertical-slice-01.md#20-implementation-phases)
> See also: [Sprint 4 team consilium](consilium.md)

## Prioritized Task List

| # | Task | Owner | Description |
|---|------|-------|-------------|
| 1 | Deterministic capability | Sage | `agents/test_agent/capability.py`: `compute_word_count(text) -> int` (`len(text.split())`, matching "maximal nonempty text segments separated by Unicode whitespace") |
| 2 | Execution context | Sage | `agents/test_agent/execution_context.py`: `ExecuteTaskContext` frozen dataclass carrying everything one bounded execution needs |
| 3 | Agent-owned identifier factory | Sage | `agents/test_agent/ids.py`: local `IdentifierFactory` Protocol (deliberately not shared with `orchestrator/application/ids.py` — separate deployables) |
| 4 | Agent-owned errors | Sage | `agents/test_agent/errors.py`: `CapabilityMismatchError`, `CommandIdentityConflictError`, `CommandIntegrityError` |
| 5 | Terminal event payload builders | Sage | `agents/test_agent/messages.py`: `build_task_completed_payload`, `build_task_failed_payload`, matching the Sprint 1 contracts |
| 6 | Readiness boundary | Sage | `agents/test_agent/readiness.py`: Agent-owned `ReadinessClassification`, `AgentReadiness`, `evaluate_readiness` (declaration-digest match + draining check; ADR-0008 Section 7) |
| 7 | Test Agent lifecycle | Sage | `agents/test_agent/agent.py`: `TestAgent` class implementing the Section 14/ADR-0007 Section 4 ordering: receipt-first idempotency, capability validation, deadline check, deterministic execution, atomic receipt/outcome/event-outbox construction |
| 8 | Capability unit tests | Ivy | `tests/unit/agents/test_agent/test_capability.py`: Unicode whitespace edge cases, empty string, leading/trailing/multiple separators |
| 9 | Readiness unit tests | Ivy | `tests/unit/agents/test_agent/test_readiness.py`: match/mismatch/draining classifications |
| 10 | Lifecycle component tests | Ivy | `tests/component/agents/test_agent/test_agent_lifecycle.py`: first execution, duplicate resolution, identity conflict, integrity conflict, deadline-before-execution, concurrent-duplicate arbitration, capability mismatch rejection |

## Work Schedule

### Phase A: Value Objects and Capability (tasks 1-6)
- Deterministic capability, execution context, local ID factory, errors, message builders, readiness.
- Checkpoint commit: `sprint-4: add test agent value objects and capability`.

### Phase B: Lifecycle and Tests (tasks 7-10)
- `TestAgent` lifecycle class and full test coverage.
- Checkpoint commit: `sprint-4: add test agent lifecycle`.

### Phase C: Sign-off
- QA sign-off (`docs/qa/sprint-4-signoff.md`).
- Final commit and PR.

## Success Criteria

- [ ] `uv run ruff format --check .` and `uv run ruff check .` succeed with no findings.
- [ ] `uv run basedpyright` succeeds in strict mode with no errors.
- [ ] `uv run pytest` succeeds, including new Test Agent unit and component tests.
- [ ] `compute_word_count` matches Section 14's exact semantics (no trimming/normalization beyond `split()`).
- [ ] A redelivered command with identical `task_attempt_id`/`message_id`/digest returns the stored outcome without re-executing or enqueueing a second event.
- [ ] A different `message_id` for the same `task_attempt_id` raises `CommandIdentityConflictError`; a matching `message_id` with a different digest raises `CommandIntegrityError`.
- [ ] A command whose deadline has already elapsed before execution produces a `TASK_RESULT_DEADLINE_EXCEEDED` failure without invoking `compute_word_count`.
- [ ] A capability/version mismatch is rejected before execution.
- [ ] No module under `agents/test_agent/` imports `orchestrator/*` or `adapters/*`.
- [ ] `docs/sprint-4/done.md` and PROJECT_BRIEF.md Sections 6-8 are updated before merge.

## What's NOT in This Sprint

| Feature | Reason |
|---------|--------|
| Event Bus consumer / real message delivery | Requires a concrete adapter (Phase 6); this sprint models only the domain-level `handle()` call |
| Lifecycle interruption (shutdown/restart/rebalance cancellation) | A process/transport concern with no in-flight execution to interrupt at the domain level (see consilium disagreement 2) |
| Workflow API implementation (Phase 5) | Maps Orchestrator outcomes to HTTP; unrelated to the Agent |
| PostgreSQL/Redpanda adapters (Phase 6) | Ports remain interfaces only |

## Agent Prompt

> Read `PROJECT_BRIEF.md`, then read `docs/sprint-4/plan.md` and
> `docs/sprint-4/consilium.md`. Execute Sprint 4, Phase 4 of
> [vertical-slice-01.md](../implementation/vertical-slice-01.md) only.
>
> First: `git pull origin main && git checkout -b feature/sprint-4-test-agent`
>
> Update `docs/sprint-4/progress.md` after each phase (A/B/C above).
> When done, push and create a PR following `CONTRIBUTING.md` and
> Sections 12-14 of `PROJECT_BRIEF.md`. Do not implement any Phase 5+
> behavior or any concrete persistence/transport adapter.
