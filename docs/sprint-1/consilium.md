# Sprint 1 — Team Consilium

> Reviewing the proposed Sprint 1 scope (Vertical Slice 01, Phase 1 only:
> root tooling metadata + canonical contracts, no domain behavior) before
> committing to `docs/sprint-1/plan.md`.

## Remy (Producer)

Phase 1 is the right first cut. It has no dependency on PostgreSQL or
Redpanda being stood up, so it can complete without any infrastructure
decisions blocking it. My only concern is scope creep: it would be tempting
to "just sketch" the Orchestrator or Test Agent while we're in here. We
don't. Phase 1 output is tooling + contracts + an empty package skeleton.
Nothing importable as domain logic. If a task tempts someone into writing
domain logic, it moves to the Sprint 2 backlog instead.

## Dash (Tooling Engineer)

Agreed on scope. ADR-0003 is unusually prescriptive, which is good — CPython
3.14, uv, Hatchling, Ruff, BasedPyright, pytest are non-negotiable. The one
open question flagged in Section 23 of the vertical-slice doc is "exact
supported patch releases and locked dependency versions." I'll pin the
newest available CPython 3.14 patch at implementation time and record it in
`pyproject.toml`'s `requires-python`, then let `uv.lock` pin everything else.
I also want a `scripts/` or `Makefile`-equivalent set of uv-managed commands
(`uv run ruff format`, `uv run ruff check`, `uv run basedpyright`, `uv run
pytest`) documented in the same PR, since ADR-0003 requires the same commands
to work locally and in CI even though no CI is configured yet.

## Sage (Contracts Engineer)

Phase 1 explicitly says "Include the Accepted ADR-0012 correlation contract"
and "implement no domain behavior." That means: schemas and examples for the
`workflow.submit`/`workflow.read`/health operations and the
`ExecuteTask`/`TaskCompleted`/`TaskFailed` events, described in Sections 5,
10, and the correlation table in Section 19 — but as contract artifacts
only, not as running code that enforces them. The open question from Section
23 that's actually in scope here is "canonical schema file organization and
generation tooling." I'll propose a `contracts/` tree (JSON Schema, OpenAPI,
AsyncAPI, `examples/`) and keep it separate from `src/ai_platform/contracts/`
until Phase 2 decides how runtime models are generated or hand-written from
it. I'll flag that decision explicitly rather than silently picking one, per
AGENTS.md.

## Ivy (QA Engineer)

Testable acceptance for Phase 1 is narrower than Section 19 of the vertical
slice doc — most of Section 19 depends on Postgres/Redpanda, which don't
exist yet. My Phase 1 test surface is: (1) JSON Schema documents are valid
Draft 2020-12 schemas, (2) the OpenAPI 3.1.1 document and AsyncAPI 3.0.0
document are structurally valid, (3) every example validates against its
declared schema, (4) `uv run ruff check`, `uv run basedpyright`, and `uv run
pytest` all succeed against an empty/near-empty package. I will not write
tests that assert domain behavior that doesn't exist yet — that would be
testing nothing and would mislead a future reader about what's implemented.

## Disagreements

1. **Dash vs. Sage — where should generation tooling live, if any.** Dash
   wants a small script now to lint the contracts directory in CI-friendly
   fashion; Sage argues no generation/codegen tooling should be chosen yet
   since Phase 2 (runtime models/ports) may drive that decision, and
   introducing it now risks a premature, undocumented architectural choice.
   **Resolution:** Sprint 1 adds validation-only tooling (schema/OpenAPI/
   AsyncAPI linting), not code generation. Codegen tooling choice, if any, is
   explicitly deferred to Phase 2 and noted as an open question, not decided
   silently.

2. **Remy vs. Ivy — should Ivy's contract tests live under `tests/` now or
   wait until Phase 2 introduces runtime code to test against.** Remy wants
   to defer any `tests/` scaffolding to avoid an empty/placeholder test tree.
   Ivy argues validating the contracts *is* real, valuable Phase 1 work and
   without it nothing checks that the schemas/examples are even
   self-consistent. **Resolution:** Ivy's contract-validation tests are
   in-scope for Sprint 1, under `tests/contract/`, per the test layout named
   in ADR-0003 and the test level matrix in `docs/testing/README.md`. They
   test the contracts, not unwritten domain behavior.

## Outcome

Sprint 1 scope confirmed as Phase 1 only, with contract-validation tests
included and code generation explicitly deferred. Proceeding to
`docs/sprint-1/plan.md`.
