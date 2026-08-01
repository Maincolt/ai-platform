# Sprint 5 — Done

## What Was Built

**Workflow API** (`src/ai_platform/api/`):
- `context.py` — `TrustedRequestContext`, `LocalDevelopmentAuthorizationPolicy`.
- `correlation.py` — ADR-0012 correlation normalization (canonical lowercase UUIDv7 validation, `uuid.uuid7()` generation).
- `fingerprint.py` — RFC 8785 canonical bytes (via the `rfc8785` package) + SHA-256 request fingerprinting.
- `problem_details.py` — Problem Details builders for every Section 5 stable error.
- `models.py` — Pydantic request/response models mirroring the Sprint 1 JSON Schemas.
- `inmemory_ports.py` — explicitly non-production in-memory implementations of the Phase 2/3 ports.
- `dependencies.py` — process-lifetime `AppState` assembly wiring in-memory ports + Sprint 3's `SubmissionOrchestrator`/`TerminalEventProcessor`/`RegistryCandidateSelector`.
- `ids.py` — `Uuid7IdentifierFactory` (stdlib `uuid.uuid7()`).
- `app.py` — the FastAPI app: `POST /api/v1/workflows`, `GET /api/v1/workflows/{workflow_id}`, `GET /health/live`, `GET /health/ready`, mapping `SubmissionDisposition` to the Section 5 status-code table, with Problem Details exception handlers for validation and unexpected errors.

Verified both via FastAPI's in-process `TestClient` (no Docker/running server needed) and as a real local `uvicorn` process handling real HTTP requests.

**Tests:**
- `tests/unit/api/` — 11 tests (correlation normalization's 5 ADR-0012 scenarios plus uniqueness/canonical-form checks; fingerprint determinism).
- `tests/component/api/test_workflow_api.py` — 13 tests covering the full Section 5 error table (400/202/200/409/503/404), correlation header behavior, and public-response field exclusion.

190 tests total (up from 166), all passing. Clean on `ruff format`, `ruff check`, and `basedpyright` (strict, with one narrowly scoped, documented exception for a third-party `httpx`/`TestClient` typing gap).

## What's NOT Done

- No concrete PostgreSQL/Redpanda adapters (Phase 6) — the API is wired against in-memory reference ports assembled at startup, explicitly documented as non-production.
- No Event Bus consumer: after submission, a workflow remains `DISPATCHED` until a future Phase 6 consumer (or a test directly driving `TerminalEventProcessor`) applies the terminal outcome.
- Multi-principal authorization / owner-mismatch disclosure paths — structurally unreachable under the single synthetic principal this slice uses.
- Full Section 8 `/health/ready` semantics (DB/broker readiness) — only Registry-snapshot readiness is reported.

## Files Changed/Created

- `docs/sprint-5/{consilium.md,plan.md,progress.md,done.md}` — sprint docs.
- `pyproject.toml` — added `fastapi`, `uvicorn`, `rfc8785` (runtime) and `httpx` (dev) dependencies; added a scoped `basedpyright` execution-environment override.
- `src/ai_platform/api/*.py` — 9 new modules.
- `tests/unit/api/*.py`, `tests/component/api/*.py` — 3 new test modules.

## Manual Setup Required

None for tests. To run the API locally:

```bash
uv sync
uv run uvicorn ai_platform.api.app:app --reload
```

No environment variables or secrets are required — this slice's
`LocalDevelopmentAuthorizationPolicy` and in-memory ports need no external
configuration.

## Known Issues

- None filed. See `docs/qa/sprint-5-signoff.md` for the explicit "no
  blockers" QA result.
