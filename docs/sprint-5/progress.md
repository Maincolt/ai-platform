# Sprint 5 — Progress Tracker

> If context overflows, start a new chat/session:
> "Read PROJECT_BRIEF.md and docs/sprint-5/progress.md.
>  Continue Sprint 5 (Vertical Slice 01, Phase 5 only) from where it left off."

## Task Status

| # | Task | Owner | Status | Notes |
|---|------|-------|--------|-------|
| 1 | Trusted request context | Sage | ✅ Done | `api/context.py`: `TrustedRequestContext`, `LocalDevelopmentAuthorizationPolicy` |
| 2 | Correlation normalization | Sage | ✅ Done | `api/correlation.py`: canonical UUIDv7 validation, `uuid.uuid7()` generation |
| 3 | Request fingerprinting | Sage | ✅ Done | `api/fingerprint.py`: RFC 8785 (`rfc8785` package) + SHA-256 |
| 4 | Problem Details builder | Sage | ✅ Done | `api/problem_details.py`: all Section 5 stable errors |
| 5 | Request/response models | Sage | ✅ Done | `api/models.py`: Pydantic models mirroring Sprint 1 schemas |
| 6 | In-memory application assembly | Sage | ✅ Done | `api/inmemory_ports.py`, `api/dependencies.py`, `api/ids.py`: explicitly non-production wiring |
| 7 | Workflow API routes | Sage | ✅ Done | `api/app.py`: full FastAPI app, verified both via `TestClient` and a real `uvicorn` process |
| 8 | Correlation contract tests | Ivy | ✅ Done | `tests/unit/api/test_correlation.py`: 7 tests |
| 9 | Fingerprint tests | Ivy | ✅ Done | `tests/unit/api/test_fingerprint.py`: 4 tests |
| 10 | Workflow API component tests | Ivy | ✅ Done | `tests/component/api/test_workflow_api.py`: 13 tests, full Section 5 error table |

## Bugs Found

| # | Description | Severity | Status | Fix |
|---|-------------|----------|--------|-----|
| 1 | `httpx`/Starlette's `TestClient` overloads report several members as partially "Unknown" under BasedPyright strict mode, a confirmed upstream typing gap (sentinel default values), not our code | minor (third-party typing gap) | accepted | Scoped `basedpyright` execution-environment override for `tests/component/api` only (`reportUnknownMemberType`/`reportUnknownVariableType`/`reportUnknownArgumentType` disabled there); rest of the tree remains fully strict |

## Notes

- Sprint scope confirmed via [team consilium](consilium.md): full Workflow
  API contract, composed over Sprint 3's application services using
  in-memory port implementations assembled at app startup — explicitly
  documented as non-production, not a Phase 6 adapter.
- Multi-principal authorization/owner-mismatch disclosure paths are
  structurally unreachable under the single-principal
  `LocalDevelopmentAuthorizationPolicy` and are not implemented.
- `/health/ready` reports only Registry-snapshot readiness (what this
  sprint actually constructs), not full Section 8 DB/broker semantics —
  documented explicitly in the endpoint's docstring, per consilium
  disagreement 1.
- One harmless, non-suppressible third-party `StarletteDeprecationWarning`
  appears once per test run (`httpx` vs. `httpx2` with `TestClient`); it
  originates entirely inside Starlette's own module and could not be
  reliably filtered via pytest/warnings configuration in this environment
  (module-based filters did not take effect against it). Documented here
  rather than silently left unexplained.
- **Validation performed (2026-08-01):** `uv run ruff format --check .`,
  `uv run ruff check .`, `uv run basedpyright` (strict, with the one
  scoped exception above), `uv run pytest -v` — all passed (190/190
  tests, 0 lint findings, 0 type errors). Also manually verified the app
  runs as a real local process via `uv run uvicorn ai_platform.api.app:app`
  and responds correctly to real HTTP requests (not just `TestClient`).
