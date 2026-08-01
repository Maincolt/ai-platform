# Sprint 1 — Done

## What Was Built

- Root tooling metadata: `pyproject.toml` (Hatchling build backend,
  `requires-python = ">=3.14,<3.15"`, Ruff config, BasedPyright strict
  config, pytest config) and a committed `uv.lock`.
- `src/ai_platform/` package skeleton matching the ADR-0003 tree
  (`api/`, `orchestrator/capability_registry/`, `agents/test_agent/`,
  `contracts/`, `ports/{event_bus,persistence}/`,
  `adapters/{event_bus,persistence}/`, `shared/{configuration,logging}/`) —
  every module is docstring-only; no domain logic.
- Canonical contracts under `contracts/`:
  - JSON Schema (Draft 2020-12): Problem Details, `workflow.submit` request,
    `workflow.submit`/`workflow.read` responses, `ExecuteTask`,
    `TaskCompleted`, `TaskFailed`.
  - OpenAPI 3.1.1 description of the Workflow API
    (`workflow.submit`, `workflow.read`, `health.live`, `health.ready`).
  - AsyncAPI 3.0.0 description of `task-commands`/`task-outcomes`.
  - 12 examples, one or more per schema/operation/message.
  - The ADR-0012 `Correlation-Id` normalization contract, expressed as a
    required response header (OpenAPI) plus the lowercase-UUIDv7 pattern on
    every correlation/identifier field.
- `tests/contract/` — 52 tests validating JSON Schema validity, OpenAPI 3.1
  structural validity, AsyncAPI structural validity, and example↔schema
  conformance.
- `contracts/README.md` documenting layout, naming, and known Phase 1
  simplifications.

## What's NOT Done

- No Orchestrator, Capability Registry, Test Agent, Workflow API, adapters,
  or persistence/Event Bus code — all deferred to Phases 2–6 by design (see
  `docs/sprint-1/plan.md`, "What's NOT in This Sprint").
- No contract code-generation tooling — explicitly deferred to Phase 2 per
  the Sprint 1 consilium.
- Full AsyncAPI meta-schema conformance validation — Sprint 1 validates
  structure only; see `contracts/README.md`.

## Files Changed/Created

- `PROJECT_BRIEF.md` — sprint coordination hub.
- `docs/sprint-1/{consilium.md,plan.md,progress.md,done.md}` — sprint docs.
- `pyproject.toml`, `uv.lock` — tooling metadata.
- `src/ai_platform/**/__init__.py` — package skeleton (16 files, no logic).
- `contracts/README.md` and `contracts/{json-schema,openapi,asyncapi,examples}/v1/*`
  — canonical contracts and examples (23 files).
- `tests/contract/*.py` — 4 contract validation test modules (52 tests).

## Manual Setup Required

- Run `uv sync` once to create the local `.venv/` (already verified working
  with CPython 3.14.4 via `uv python install`/uv-managed toolchain).
- No environment variables, secrets, or external services are required for
  Sprint 1 — there is nothing running yet.

## Known Issues

- None filed. See `docs/qa/sprint-1-signoff.md` for the explicit "no
  blockers" QA result.
