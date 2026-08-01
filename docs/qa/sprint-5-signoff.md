# QA Sprint 5 Sign-Off

Date: 2026-08-01
Tester: Ivy (QA)

## Scope

Vertical Slice 01, Phase 5: the Workflow API's submit/read/health
operations, trusted synthetic request context, ADR-0012 correlation
normalization, RFC 8785 request fingerprinting, and stable Problem
Details error responses. Composed over Sprint 3's application services
using in-memory reference port implementations; no real database/Kafka
adapters (Phase 6).

## Test Results

- Tests run: 190 (52 contract + 24 domain unit + 42 registry unit + 14
  Test Agent unit + 11 API unit + 47 component: 11 persistence-port + 11
  application-service + 4 registry-integration + 8 Test Agent lifecycle +
  13 Workflow API)
- Tests passed: 190
- Tests failed: 0

Command: `uv run pytest -v`

## Tooling Verification

- `uv run ruff format --check .` — no reformatting needed.
- `uv run ruff check .` — all checks passed.
- `uv run basedpyright` (strict mode, with one narrowly scoped exception
  for `tests/component/api` covering a confirmed upstream `httpx`/
  `TestClient` typing gap) — 0 errors, 0 warnings, 0 notes.
- Manually verified: `uv run uvicorn ai_platform.api.app:app` starts a
  real local server and responds correctly to real HTTP requests
  (`GET /health/live`, `POST /api/v1/workflows`).

## Behavior Coverage

- **Correlation (ADR-0012):** missing, valid, malformed, oversized, and
  control-character header scenarios; uppercase (noncanonical) UUIDs
  correctly rejected; generated values are unique.
- **Fingerprint:** deterministic for identical input; changes when text or
  capability version changes; produces a valid lowercase hex SHA-256
  digest.
- **Submission:** first acceptance returns `202 DISPATCHED`; equivalent
  replay returns `200` with the same workflow and unchanged durable
  correlation; fingerprint conflict returns `409 REQUEST_ID_CONFLICT`; no
  eligible Agent (empty Registry snapshot) returns
  `503 AGENT_TEMPORARILY_UNAVAILABLE`; invalid body returns
  `400 INVALID_REQUEST` with a Problem Details body.
- **Read:** existing workflow returns current state/revision/timestamps;
  missing workflow returns `404 WORKFLOW_NOT_FOUND`.
- **Health:** `/health/live` always succeeds; `/health/ready` reports the
  Registry-snapshot readiness this sprint actually constructs.
- **Disclosure:** public response bodies never expose `task_id`,
  `task_attempt_id`, or `idempotency_scope_id`.

## Blockers

NONE

## Issues Filed

None. One accepted, documented limitation: `httpx`/Starlette's
`TestClient` triggers a one-time `StarletteDeprecationWarning` on import
that could not be reliably suppressed via pytest/warnings configuration
in this environment; it is purely cosmetic and does not affect test
correctness (see `docs/sprint-5/progress.md`).

## Result

✅ PASS — No blockers. Sprint 5 (Phase 5) is ready to merge.
