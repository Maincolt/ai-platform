# Canonical Contracts

This directory contains the canonical, versioned contracts for
[Vertical Slice 01](../docs/implementation/vertical-slice-01.md), produced in
Sprint 1 (Phase 1). It defines contracts only — no runtime code enforces
them yet. See [docs/sprint-1/plan.md](../docs/sprint-1/plan.md) for scope.

## Layout

```text
contracts/
├── json-schema/v1/    # JSON Schema Draft 2020-12 documents
├── openapi/v1/         # OpenAPI 3.1.1 description of the Workflow API
├── asyncapi/v1/         # AsyncAPI 3.0.0 description of task-commands/task-outcomes
└── examples/v1/         # One or more examples per schema/operation/message
```

`v1` matches the `v` + major-integer version-directory convention in
[ADR-0004](../docs/architecture/decisions/ADR-0004-api-and-contract-standards.md#4-naming-conventions).

## Governing Documents

- [ADR-0004: API and Contract Standards](../docs/architecture/decisions/ADR-0004-api-and-contract-standards.md) — envelope, naming, Problem Details, versioning.
- [ADR-0012: Correlation ID Normalization](../docs/architecture/decisions/ADR-0012-correlation-id-normalization.md) — `Correlation-Id` valid/missing/invalid behavior.
- [vertical-slice-01.md, Sections 5, 9, 10, 19](../docs/implementation/vertical-slice-01.md) — exact operations, states, message contents, and correlation scenarios realized here.

## Naming

File and identifier naming follows ADR-0004 Section "Naming Conventions":

- JSON Schema files: lowercase `snake_case.schema.json`.
- Schema `$id`: a stable versioned URN, e.g.
  `urn:ai-platform:contract:message:task-completed:1.0` for message contracts.
  API request/response schema URNs extend the same pattern with an `api:`
  segment (e.g. `urn:ai-platform:contract:api:workflow-submit-request:1.0`);
  this extension is a Sprint 1 implementation choice, not a new ADR decision,
  and may be revisited if a future ADR defines API schema URNs explicitly.
- Semantic contract names: `PascalCase`, e.g. `ExecuteTask`, `TaskCompleted`.
- Business enum values and stable error codes: `UPPER_SNAKE_CASE`.

## Known Phase 1 Simplifications

These are explicit, documented simplifications for Sprint 1 only — they are
not architectural decisions and must be revisited before Phase 2:

- **No shared `$ref`-based common-definitions file.** Each message schema
  (`execute_task`, `task_completed`, `task_failed`) repeats the full envelope
  fields from ADR-0004 Section 5 instead of referencing a shared envelope
  schema. Cross-file `$ref` resolution and a possible common-definitions
  file are open questions (see
  [vertical-slice-01.md Section 23](../docs/implementation/vertical-slice-01.md#23-unresolved-implementation-choices),
  "canonical schema file organization and generation tooling"), intentionally
  deferred to Phase 2 per the
  [Sprint 1 team consilium](../docs/sprint-1/consilium.md).
- **No code generation.** Runtime models are not generated from these
  contracts in Sprint 1. Whether/how that happens is a Phase 2 decision.
- **AsyncAPI validation is structural, not full meta-schema conformance.**
  `tests/contract/` checks that the AsyncAPI document has the fields and
  shapes this platform's tooling relies on (via our own JSON Schemas for its
  message payloads) rather than validating full conformance to the official
  AsyncAPI 3.0.0 meta-schema, which is split across many externally hosted
  schema files. OpenAPI validation, by contrast, uses the well-established
  `openapi-spec-validator` package and does validate full 3.1 conformance.

## Contracts in This Version

| Contract | File | Kind |
| --- | --- | --- |
| Problem Details | `json-schema/v1/problem_details.schema.json` | RFC 9457 API error body |
| `workflow.submit` request | `json-schema/v1/workflow_submit_request.schema.json` | API request |
| `workflow.submit`/`workflow.read` response | `json-schema/v1/workflow_submit_response.schema.json`, `json-schema/v1/workflow_read_response.schema.json` | API response |
| `ExecuteTask` | `json-schema/v1/execute_task.schema.json` | Command message |
| `TaskCompleted` | `json-schema/v1/task_completed.schema.json` | Event message |
| `TaskFailed` | `json-schema/v1/task_failed.schema.json` | Event message |
| Workflow API | `openapi/v1/workflow-api.openapi.json` | OpenAPI 3.1.1 |
| Task commands/outcomes | `asyncapi/v1/workflow-events.asyncapi.json` | AsyncAPI 3.0.0 |
