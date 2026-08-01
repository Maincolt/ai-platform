# Sprint 1 — Tooling and Canonical Contracts

> Sprint Goal: Establish the ADR-0003 tooling foundation and the canonical
> JSON Schema/OpenAPI/AsyncAPI contracts (including the ADR-0012 correlation
> contract) for Vertical Slice 01, with no domain, persistence, or transport
> behavior implemented.
> Branch: `feature/sprint-1-tooling-and-contracts`
> Scope authority: [Vertical Slice 01, Section 20, Phase 1](../implementation/vertical-slice-01.md#20-implementation-phases)
> See also: [Sprint 1 team consilium](consilium.md)

## Prioritized Task List

| # | Task | Owner | Description |
|---|------|-------|-------------|
| 1 | Root tooling metadata | Dash | `pyproject.toml` (Hatchling build backend, `requires-python = ">=3.14,<3.15"`, project metadata), `uv.lock` committed, Ruff config, BasedPyright strict config |
| 2 | Package skeleton | Dash | Create `src/ai_platform/` with the package tree from [ADR-0003](../architecture/decisions/ADR-0003-runtime-and-development-tooling.md) (`api/`, `orchestrator/capability_registry/`, `agents/test_agent/`, `contracts/`, `ports/{event_bus,persistence}/`, `adapters/{event_bus,persistence}/`, `shared/{configuration,logging}/`) — empty modules only, no domain logic |
| 3 | uv-managed command set | Dash | Document and verify `uv sync`, `uv run ruff format`, `uv run ruff check`, `uv run basedpyright`, `uv run pytest` as the same commands usable locally and in CI (no CI workflow file yet — commands must simply work) |
| 4 | Canonical contracts tree | Sage | Create `contracts/` with `json-schema/`, `openapi/`, `asyncapi/`, `examples/` subdirectories; document the directory layout in `contracts/README.md` |
| 5 | Workflow API JSON Schemas | Sage | Draft 2020-12 schemas for `workflow.submit` request/response, `workflow.read` response, RFC 9457 Problem Details, per [vertical-slice-01.md Section 5](../implementation/vertical-slice-01.md#5-workflow-api-contract) |
| 6 | OpenAPI 3.1.1 description | Sage | Describe `POST /api/v1/workflows`, `GET /api/v1/workflows/{workflow_id}`, `GET /health/live`, `GET /health/ready`, referencing the JSON Schemas from task 5 |
| 7 | Event contracts (AsyncAPI 3.0.0) | Sage | `ExecuteTask`, `TaskCompleted`, `TaskFailed` message contracts per [vertical-slice-01.md Section 10](../implementation/vertical-slice-01.md#10-commands-events-and-producer-identity) |
| 8 | Correlation contract (ADR-0012) | Sage | Encode the `Correlation-Id` valid/missing/invalid normalization rules from [ADR-0012](../architecture/decisions/ADR-0012-correlation-id-normalization.md) and the correlation scenario table in [vertical-slice-01.md Section 19](../implementation/vertical-slice-01.md#19-testable-acceptance-criteria) into schema constraints and examples |
| 9 | Examples for every contract | Sage | At least one valid example per schema/operation/message, plus the stable-error examples from the Section 5 error table |
| 10 | Contract validation tests | Ivy | `tests/contract/` — verify every JSON Schema is valid Draft 2020-12, the OpenAPI document is structurally valid 3.1.1, the AsyncAPI document is structurally valid 3.0.0, and every example validates against its declared schema |
| 11 | Tooling verification tests | Ivy | Confirm `uv run ruff check`, `uv run basedpyright`, `uv run pytest` succeed against the empty package skeleton from task 2 |
| 12 | Sprint coordination | Remy | Keep scope to Phase 1 only; review tasks 1–11 for domain-logic creep; triage any follow-up as Sprint 2 backlog items in `docs/ideas-backlog.md` |

## Work Schedule

### Phase A: Tooling Foundation (tasks 1-3)
- `pyproject.toml`, `uv.lock`, Ruff/BasedPyright config, empty `src/ai_platform/` package tree.
- Checkpoint commit: `sprint-1: add tooling metadata and package skeleton`.

### Phase B: Canonical Contracts (tasks 4-9)
- `contracts/` tree with JSON Schema, OpenAPI, AsyncAPI, and examples, including the ADR-0012 correlation contract.
- Checkpoint commit: `sprint-1: add canonical workflow API and event contracts`.

### Phase C: Validation and Sign-off (tasks 10-12)
- Contract and tooling validation tests.
- QA sign-off (`docs/qa/sprint-1-signoff.md`).
- Final commit and PR.

## Success Criteria

- [ ] `uv sync` installs a locked environment from a committed `uv.lock`.
- [ ] `uv run ruff format` and `uv run ruff check` succeed with no findings.
- [ ] `uv run basedpyright` succeeds in strict mode with no errors.
- [ ] `uv run pytest` succeeds (including the new `tests/contract/` suite).
- [ ] Every canonical JSON Schema is valid Draft 2020-12.
- [ ] The OpenAPI document is valid OpenAPI 3.1.1 and covers `workflow.submit`, `workflow.read`, `health.live`, `health.ready`.
- [ ] The AsyncAPI document is valid AsyncAPI 3.0.0 and covers `ExecuteTask`, `TaskCompleted`, `TaskFailed`.
- [ ] The `Correlation-Id` valid/missing/invalid normalization rules from ADR-0012 are represented in the contracts and covered by at least one example each.
- [ ] Every example validates against its declared schema.
- [ ] No domain, persistence, or Event Bus/transport code exists outside the empty package skeleton.
- [ ] `docs/sprint-1/done.md` and PROJECT_BRIEF.md Sections 7–8 are updated before merge.

## What's NOT in This Sprint

| Feature | Reason |
|---------|--------|
| Workflow domain model / persistence ports (Phase 2) | Depends on contracts being finalized first; explicitly deferred |
| Orchestrator, Capability Registry (Phase 3) | No domain behavior in Phase 1 |
| Test Agent implementation (Phase 4) | No domain behavior in Phase 1 |
| Workflow API implementation (Phase 5) | Contracts precede implementation |
| PostgreSQL/Redpanda adapters and Docker deployment (Phase 6) | No infrastructure needed to validate contracts/tooling |
| Integration/recovery/security/E2E test suites (Phase 7) | Require the components built in Phases 2–6 |
| Operational documentation (Phase 8) | Nothing operational exists yet |
| Contract code generation tooling | Explicitly deferred per the Sprint 1 consilium — Phase 2 will decide whether/how runtime models are generated |

## Agent Prompt

> Read `PROJECT_BRIEF.md`, then read `docs/sprint-1/plan.md` and
> `docs/sprint-1/consilium.md`. Execute Sprint 1, Phase 1 of
> [vertical-slice-01.md](../implementation/vertical-slice-01.md) only.
>
> First: `git pull origin main && git checkout -b feature/sprint-1-tooling-and-contracts`
>
> Close GitHub Issues in commits: `fix: description (Fixes #NN)`.
> Update `docs/sprint-1/progress.md` after each phase (A/B/C above).
> When done, push and create a PR following `CONTRIBUTING.md` and
> Sections 12–14 of `PROJECT_BRIEF.md`. Do not implement any Phase 2+ behavior.
