# QA Sprint 2 Sign-Off

Date: 2026-08-01
Tester: Ivy (QA)

## Scope

Vertical Slice 01, Phase 2: the five-state workflow aggregate, accepted-request
arbitration identity/evidence, task/attempt, transition history, audit,
inbox/outbox/receipt records, and capability-oriented persistence ports.
Pure Python domain code and `Protocol` interfaces only — no database, no
Event Bus, no adapters (Phase 6).

## Test Results

- Tests run: 87 (52 contract from Sprint 1 + 24 unit + 11 component)
- Tests passed: 87
- Tests failed: 0

Command: `uv run pytest -v`

## Tooling Verification

- `uv run ruff format --check .` — no reformatting needed.
- `uv run ruff check .` — all checks passed.
- `uv run basedpyright` (strict mode) — 0 errors, 0 warnings, 0 notes.

## Domain Behavior Coverage

- Every legal Section 9 transition (`none->RECEIVED`, `RECEIVED->PENDING`,
  `PENDING->DISPATCHED`, `DISPATCHED->COMPLETED`, `DISPATCHED->FAILED`)
  verified with correct resulting state, revision, and history.
- Every illegal edge tested (skipping states, transitioning from a
  nonexistent workflow, mutating from `RECEIVED`/`PENDING` directly to a
  terminal state).
- Terminal immutability verified: duplicate completion and late failure
  after a terminal state both raise and leave the original outcome/history
  unchanged.
- Deadline-expiry cause path verified as still subject to the same
  terminal-exclusivity rule.
- Accepted-request key and evidence immutability verified (frozen
  dataclasses raise on mutation attempts).
- Fingerprint comparison verified for `NEW`, `EQUIVALENT_REPLAY`, and
  `FINGERPRINT_CONFLICT`, plus same-`request_id`-different-scope
  independence.
- All 7 persistence ports proven implementable via in-memory fakes,
  including a genuine compare-and-set/stale-revision race and
  claim/fencing-token rejection for both outbox ports.

## Blockers

NONE

## Issues Filed

None. One test-fake bug (workflow repository storing a live object
reference instead of a snapshot, which would have silently defeated the
revision-conflict test) was caught and fixed during development, before
this sign-off; it affected only the test fake, not any `src/` domain code.

## Result

✅ PASS — No blockers. Sprint 2 (Phase 2) is ready to merge.
