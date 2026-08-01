# Sprint 5 — Workflow API

> Sprint Goal: Implement Vertical Slice 01, Phase 5: the Workflow API's
> submit/read/health operations, trusted synthetic request context,
> ADR-0012 correlation normalization, RFC 8785 request fingerprinting, and
> stable Problem Details error responses — composed over Sprint 3's
> `SubmissionOrchestrator`/`TerminalEventProcessor` using in-memory port
> implementations assembled at app startup. No real database/Kafka
> adapters (Phase 6).
> Branch: `feature/sprint-5-workflow-api`
> Scope authority: [Vertical Slice 01, Section 20, Phase 5](../implementation/vertical-slice-01.md#20-implementation-phases)
> See also: [Sprint 5 team consilium](consilium.md)

## Prioritized Task List

| # | Task | Owner | Description |
|---|------|-------|-------------|
| 1 | Trusted request context | Sage | `api/context.py`: `TrustedRequestContext` frozen dataclass + `LocalDevelopmentAuthorizationPolicy` (Section 4: fixed synthetic environment/scope/actor/owner/policy identity per call) |
| 2 | Correlation normalization | Sage | `api/correlation.py`: validate a raw `Correlation-Id` header against the canonical lowercase UUIDv7 profile; generate via `uuid.uuid7()` on missing/invalid (ADR-0012) |
| 3 | Request fingerprinting | Sage | `api/fingerprint.py`: RFC 8785 canonical bytes (via `rfc8785`) + SHA-256 over `{text, capability, capability_version, api_contract_major}`, excluding property order/whitespace/headers/correlation (Section 6) |
| 4 | Problem Details builder | Sage | `api/problem_details.py`: builds bodies matching `contracts/json-schema/v1/problem_details.schema.json` for every Section 5 stable error |
| 5 | Request/response models | Sage | `api/models.py`: Pydantic models mirroring the Sprint 1 JSON Schemas for the submit request/response and read response |
| 6 | In-memory application assembly | Sage | `api/dependencies.py`: wires Sprint 2/3 in-memory port fakes + `SubmissionOrchestrator`/`TerminalEventProcessor`/`RegistryCandidateSelector` into one process-lifetime app state (explicitly documented as non-production) |
| 7 | Workflow API routes | Sage | `api/app.py`: `POST /api/v1/workflows`, `GET /api/v1/workflows/{workflow_id}`, `GET /health/live`, `GET /health/ready`, mapping `SubmissionDisposition` to the Section 5 status-code table |
| 8 | Correlation contract tests | Ivy | `tests/unit/api/test_correlation.py`: all five ADR-0012 scenarios |
| 9 | Fingerprint tests | Ivy | `tests/unit/api/test_fingerprint.py`: determinism regardless of JSON key order/whitespace |
| 10 | Workflow API component tests | Ivy | `tests/component/api/test_workflow_api.py`: full Section 5 error table via `TestClient` — invalid body (400), first acceptance (202), replay (200), conflict (409), no eligible Agent (503), missing/unauthorized workflow (404), health endpoints |

## Work Schedule

### Phase A: Context, Correlation, Fingerprint, Problem Details (tasks 1-5)
- All request-processing building blocks, independently testable.
- Checkpoint commit: `sprint-5: add workflow api request-processing building blocks`.

### Phase B: Routes and Assembly (tasks 6-7)
- Full FastAPI app wired against in-memory ports.
- Checkpoint commit: `sprint-5: add workflow api routes`.

### Phase C: Tests and Sign-off (tasks 8-10)
- Unit and component (`TestClient`) tests.
- QA sign-off (`docs/qa/sprint-5-signoff.md`).
- Final commit and PR.

## Success Criteria

- [ ] `uv run ruff format --check .` and `uv run ruff check .` succeed with no findings.
- [ ] `uv run basedpyright` succeeds in strict mode with no errors.
- [ ] `uv run pytest` succeeds, including new API unit and component tests.
- [ ] Every response includes a `Correlation-Id` header reflecting the effective value (preserved, or generated on missing/invalid).
- [ ] A raw invalid/oversized/malformed `Correlation-Id` is never echoed, logged, or persisted.
- [ ] `POST /api/v1/workflows` returns `202` on first acceptance, `200` on equivalent replay, `409` on fingerprint conflict, `503` on no eligible Agent, `400` on invalid input, all matching `contracts/json-schema/v1/problem_details.schema.json` for error bodies.
- [ ] `GET /api/v1/workflows/{workflow_id}` returns the durable state/result for an existing workflow and a safe `404` otherwise.
- [ ] `/health/live` never depends on anything; `/health/ready` reflects only what Sprint 5 actually constructs (see consilium disagreement 1).
- [ ] The response body for a submit/read never exposes `task_id`, `task_attempt_id`, `idempotency_scope_id`, or internal evidence, per Section 5.
- [ ] `docs/sprint-5/done.md` and PROJECT_BRIEF.md Sections 6-8 are updated before merge.

## What's NOT in This Sprint

| Feature | Reason |
|---------|--------|
| Concrete PostgreSQL/Redpanda adapters | Phase 6; this sprint assembles in-memory port implementations at app startup |
| Multi-principal authorization / owner-mismatch disclosure paths | Structurally unreachable under `LocalDevelopmentAuthorizationPolicy` (single synthetic principal); see consilium disagreement, Sage's note |
| Real API-contract-version evolution machinery | Fixed `api_contract_major = "1"` constant this slice (consilium disagreement 2) |
| Full Section 8 `/health/ready` semantics (DB/broker readiness) | No real adapters exist to be ready or not; scoped explicitly (consilium disagreement 1) |
| TLS, production identity, rate limiting | Explicit Vertical Slice 01 deferrals (Section 21) |

## Agent Prompt

> Read `PROJECT_BRIEF.md`, then read `docs/sprint-5/plan.md` and
> `docs/sprint-5/consilium.md`. Execute Sprint 5, Phase 5 of
> [vertical-slice-01.md](../implementation/vertical-slice-01.md) only.
>
> First: `git pull origin main && git checkout -b feature/sprint-5-workflow-api`
>
> Update `docs/sprint-5/progress.md` after each phase (A/B/C above).
> When done, push and create a PR following `CONTRIBUTING.md` and
> Sections 12-14 of `PROJECT_BRIEF.md`. Do not implement any Phase 6
> behavior or any concrete persistence/transport adapter.
