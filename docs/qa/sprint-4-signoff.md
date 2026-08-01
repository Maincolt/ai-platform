# QA Sprint 4 Sign-Off

Date: 2026-08-01
Tester: Ivy (QA)

## Scope

Vertical Slice 01, Phase 4: the Test Agent's deterministic `text.word-count`
capability, receipt-first idempotency lifecycle, capability/input
validation, and outcome/event/outbox persistence. Pure Python
domain/application code composed over the Phase 2 Agent-side ports; no
Event Bus consumer, no concrete adapters (Phase 6).

## Test Results

- Tests run: 165 (52 contract + 24 domain unit + 41 registry unit + 14
  Test Agent unit + 33 component: 11 persistence-port + 11
  application-service + 4 registry-integration + 7 Test Agent lifecycle)
- Tests passed: 165
- Tests failed: 0

Command: `uv run pytest -v`

## Tooling Verification

- `uv run ruff format --check .` — no reformatting needed.
- `uv run ruff check .` — all checks passed.
- `uv run basedpyright` (strict mode) — 0 errors, 0 warnings, 0 notes.
- No pytest warnings (fixed a `PytestCollectionWarning` for the
  `TestAgent`/`TestAgentDisposition`/`TestAgentResult` names).

## Behavior Coverage

- Deterministic `word_count`: Unicode whitespace edge cases (tabs,
  newlines, NBSP, em-space), empty/whitespace-only input, no
  trimming/normalization beyond `split()`.
- Readiness: matching declaration is ready; mismatch is
  `DECLARATION_MISMATCH`; draining takes precedence over a matching
  declaration.
- Lifecycle: first execution completes and enqueues exactly one event;
  a redelivered identical command returns the stored outcome without
  re-executing or re-enqueueing; a different `message_id` for the same
  attempt raises a permanent identity conflict; a matching `message_id`
  with a different digest raises an integrity error; a command whose
  deadline has already elapsed produces a safe failure without invoking
  the capability; a capability/version mismatch is rejected before any
  persistence; a genuine concurrent-duplicate race (two "first-time"
  executions for the same attempt) resolves to exactly one durable
  outcome via the receipt repository's `is_new` flag.

## Architectural Findings

Two real design issues were found and fixed during this sprint, not
merely style preferences:

1. Agent-owned and shared types were physically located under
   `orchestrator/domain/`, which would have required the Test Agent to
   import from Orchestrator-internal modules — a genuine boundary
   violation given the Agent and Orchestrator are separate deployables.
2. `AgentReceiptRepositoryPort.create_or_resolve` could not reliably
   distinguish "created new" from "resolved an existing, content-identical"
   receipt using value equality, which would have silently mis-classified
   a genuine concurrent-duplicate race. This was caught by a real failing
   test, not discovered through inspection alone.

Both are documented in `docs/sprint-4/progress.md` under "Bugs Found."

## Blockers

NONE

## Issues Filed

None — both architectural issues above were caught and fixed within this
sprint before sign-off.

## Result

✅ PASS — No blockers. Sprint 4 (Phase 4) is ready to merge.
