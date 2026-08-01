# Sprint 1 — Progress Tracker

> If context overflows, start a new chat/session:
> "Read PROJECT_BRIEF.md and docs/sprint-1/progress.md.
>  Continue Sprint 1 (Vertical Slice 01, Phase 1 only) from where it left off."

## Task Status

| # | Task | Owner | Status | Notes |
|---|------|-------|--------|-------|
| 1 | Root tooling metadata | Dash | ✅ Done | `pyproject.toml` (Hatchling, `requires-python=">=3.14,<3.15"`), Ruff/BasedPyright-strict config, `uv.lock` committed |
| 2 | Package skeleton | Dash | ✅ Done | `src/ai_platform/` tree created per ADR-0003; every module is docstring-only, no domain logic |
| 3 | uv-managed command set | Dash | ✅ Done | Verified `uv sync`, `uv run ruff format`, `uv run ruff check`, `uv run basedpyright`, `uv run pytest` all succeed locally |
| 4 | Canonical contracts tree | Sage | ✅ Done | `contracts/{json-schema,openapi,asyncapi,examples}/v1/` created with `contracts/README.md` |
| 5 | Workflow API JSON Schemas | Sage | ✅ Done | `problem_details`, `workflow_submit_request`, `workflow_submit_response`, `workflow_read_response` schemas |
| 6 | OpenAPI 3.1.1 description | Sage | ✅ Done | `workflow-api.openapi.json` covers `workflow.submit`, `workflow.read`, `health.live`, `health.ready` |
| 7 | Event contracts (AsyncAPI 3.0.0) | Sage | ✅ Done | `workflow-events.asyncapi.json` covers `ExecuteTask`, `TaskCompleted`, `TaskFailed` |
| 8 | Correlation contract (ADR-0012) | Sage | ✅ Done | `Correlation-Id` response header + lowercase UUIDv7 pattern encoded in OpenAPI header + all identifier schemas |
| 9 | Examples for every contract | Sage | ✅ Done | 12 examples under `contracts/examples/v1/`; every schema has ≥ 1 example (enforced by test 10) |
| 10 | Contract validation tests | Ivy | ✅ Done | `tests/contract/` — 52 tests: JSON Schema validity, OpenAPI 3.1 validity, AsyncAPI structural validity, example↔schema conformance |
| 11 | Tooling verification tests | Ivy | ✅ Done | `uv run ruff check`, `uv run basedpyright` (strict), `uv run pytest` all pass with zero findings |
| 12 | Sprint coordination | Remy | ✅ Done | Scope held to Phase 1 only; no domain/persistence/transport code introduced |

## Bugs Found

| # | Description | Severity | Status | Fix |
|---|-------------|----------|--------|-----|
| _none yet_ | | | | |

## Notes

- Sprint scope confirmed via [team consilium](consilium.md): Phase 1 only
  (tooling + canonical contracts), no domain/persistence/transport code.
- Codegen tooling for turning contracts into runtime models is an open
  question explicitly deferred to Phase 2 (Sprint 2+); do not decide it
  silently in this sprint.
- Contract-validation tests (`tests/contract/`) are in-scope for this sprint
  per the consilium resolution, even though no domain code exists yet — they
  validate the contracts themselves.
- **Validation performed (2026-08-01):** `uv sync` (fresh `.venv`, 30 packages
  locked), `uv run ruff format --check .`, `uv run ruff check .`,
  `uv run basedpyright` (strict mode), `uv run pytest -v` — all passed
  (52/52 tests, 0 lint findings, 0 type errors) after four line-length fixes
  and a few BasedPyright-strict type annotations in the new test modules.
- AsyncAPI validation is intentionally structural only (not full meta-schema
  conformance) — documented as a known Phase 1 simplification in
  `contracts/README.md`.
