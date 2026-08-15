# ADR-0024: Submission History — `GET /api/v1/workflows`

- **Status:** Accepted
- **Date:** 2026-08-15
- **Supersedes:** None
- **Superseded by:** None

## Context

The dashboard's new "Submit assignment" tab (ADR-0023) lets a human
operator submit an assignment and watch it route and fan out live, but
that view is ephemeral — reloading the page or opening the dashboard from
a different machine loses it. The user asked for a durable history of
requested assignments, visible on the dashboard, not just in the
submitting browser's own memory.

Two things this platform's persistence does **not** already support,
confirmed by direct inspection before this ADR:

- **No cross-workflow query exists anywhere.** Every read path
  (`WorkflowQueryPort.get`, `AuthorizedWorkflowQueryPort.get_authorized`,
  `select_workflow`) fetches exactly one workflow by ID. There is no
  `list`/`search`/`query` method on any persistence port in this
  codebase — this ADR's endpoint is the first.
- **`orchestrator.workflows` carries neither the submitted capability nor
  the submitted text.** `capability_name` exists only on
  `orchestrator.task_attempts` (per-attempt, not queryable by workflow
  without a join that still wouldn't recover the original text); the
  submitted text is never persisted anywhere — the Orchestrator only ever
  forwards it into the `ExecuteTask` command payload, not into its own
  tables.

The `Workflow` domain aggregate (`orchestrator/domain/workflow.py`) is
constructed directly by name in roughly a dozen files across
`src/`/`tests/` (submission orchestration, both persistence adapters, and
every integration/component test exercising the submission path). Adding
required `capability_name`/`input_text` fields to that aggregate would
touch all of them for a feature that is, at its core, informational —
not a change to workflow execution semantics. That cost buys nothing the
alternative below doesn't already get.

## Decision

### 1. An additive history table, not a Workflow aggregate change

A new table, `orchestrator.submission_history` (migration `0008`), keyed
by `workflow_id` (references `orchestrator.workflows`), stores exactly
what does not exist elsewhere: `capability_name`, `capability_version`,
`input_text`, `submitted_at`. It carries no state of its own — state and
result always come from joining back to `orchestrator.workflows` at read
time, so history entries can never go stale relative to the workflow's
real terminal outcome.

One row is inserted per genuinely new submission, inside the *same*
atomic transaction `SubmissionOrchestrator.submit`'s `NEW` path already
uses to write the workflow/task/attempt/outbox/audit rows
(`PsycopgOrchestratorPersistence.commit_submission`) — not a separate,
non-atomic write. An `EQUIVALENT_REPLAY` never re-enters that transaction
(per the existing idempotency design), so replays never produce duplicate
history rows for free, with no new logic required to prevent it.

`SubmissionCommitIntent` gains three new fields (`capability_name`,
`capability_version`, `input_text`), all defaulted so the dozen existing
call sites that construct it directly (mostly integration tests
exercising unrelated concerns) do not need to change.

### 2. `GET /api/v1/workflows` — the collection resource

`POST /api/v1/workflows` already submits; `GET /api/v1/workflows/{id}`
already reads one. `GET /api/v1/workflows` (no ID) is the natural
collection-read counterpart, not a new resource family. Query
parameters: `capability` (optional, one of the platform's declared
capability names), `limit` (optional, default 20, max 100), `before`
(optional RFC 3339 timestamp cursor — entries submitted strictly before
this instant). Response is newest-first, cursor-paginated (not
offset-paginated — this is an append-mostly activity feed, where offset
pagination silently skips or repeats rows as new submissions arrive
between pages; a `submitted_at` cursor does not).

This is the first paginated list endpoint in this API. No other
endpoint's shape needed to change to accommodate it — `GET
/api/v1/agents` remains deliberately unpaginated (the Capability Registry
is small and bounded by design, not an activity feed).

### 3. Security: same posture as the existing read endpoint, same caveat

Routes through the same `security_policy.resolve(semantic_operation=
"workflow.read")` trusted-context resolution the single-workflow read
endpoint already uses. Per-row ownership filtering is not applied to the
list query, for the same reason `GET /api/v1/agents` applies none today:
`LocalDevelopmentAuthorizationPolicy` resolves every caller to one
synthetic principal in this environment (see `PROJECT_BRIEF.md` Section
9 / `docs/operations/README.md` Section 8's existing security
limitations) — there is only one owner to filter by. This is a known,
already-documented limitation of the local-development deployment, not a
new gap this ADR introduces.

## Consequences

### Positive

- A real, shared, durable history — the same for every visitor, survives
  restarts — answering the actual gap ("how do I see what's been
  submitted") without touching workflow execution semantics at all.
- Zero blast radius on the ~12 existing call sites that construct
  `Workflow`/`SubmissionCommitIntent` directly, since the aggregate is
  untouched and the intent's new fields are defaulted.
- Cursor pagination is the correct shape for this data from day one,
  rather than adding offset pagination now and needing to migrate later.

### Negative

- A second table to keep in sync with `orchestrator.workflows` (by
  `workflow_id` reference) — mitigated by carrying no mutable state of
  its own, so "in sync" only ever means "the referenced workflow still
  exists," never "the cached state is stale."
- `input_text` is stored and returned verbatim (bounded to the existing
  10,000-character submission limit) — the same untrusted-content
  handling posture the rest of the platform already has for submitted
  text (never executed, never parsed as anything but opaque content), so
  no new data-handling class is introduced, but it does mean a longer
  submission now persists twice (once in the `ExecuteTask` command
  payload, once here) rather than once.

## Alternatives Considered

### Add `capability_name`/`input_text` directly to `orchestrator.workflows`

Rejected: would still need the same `SubmissionCommitIntent` threading,
plus changes to `insert_workflow`/`update_workflow`/`workflow_from_rows`
and every test asserting on that row shape, for no benefit over a
separate table joined at read time — the data has a different lifecycle
(write-once at submission vs. read-and-updated through the workflow's
whole lifetime) and belongs in its own table for that reason alone.

### Browser-local history (localStorage)

Considered first and explicitly rejected by the user: only visible on
the browser that made the submission, lost on clearing site data, not
shared across visitors opening the dashboard from a different machine.
Doesn't meet "keep a history... show them on the dashboard page" for
more than one person.

### Reconstruct assignment.route "sessions" (routing + its fanned-out results, grouped)

Considered and deferred, not rejected outright: today's fan-out
(ADR-0023 Decision 5) creates independent, unlinked workflow submissions
— there is no `parent_workflow_id` connecting an `assignment.route`
submission to the capabilities it recommended. Grouping them in history
would need a new field on `WorkflowSubmitRequest`/`ExecuteTask` to carry
that link, a contract change touching the write path this ADR
deliberately avoids. `GET /api/v1/workflows?capability=...` gives a flat,
chronological, per-capability history instead; grouping is left to a
future ADR if it turns out to matter once there's real history to look
at.

## Implementation Status

**Landed across three PRs**: #51 (migration `0008`, `SubmissionCommitIntent`/
`SubmissionHistoryQueryPort`, both persistence adapters, `GET
/api/v1/workflows`, JSON Schema/OpenAPI contracts, unit/component/
integration tests — 730 tests passing locally), #52 (the dashboard's
History tab), and a live deployment pass on the Mac Docker host.

**Update (2026-08-15) — live-verified end to end**: the migration applied
cleanly against the already-provisioned broker/database (`orchestrator`
schema version 3 → 4, migrations 0001–0007 correctly skipped as
already-applied); `platform` and `dashboard` rebuilt and recreated
(`test-agent` recreated for the existing netns gotcha — `registry.json`
was unchanged this round, so no other Agent needed restarting, unlike
every capability-adding deployment before this one). All eight
capabilities remained `READY` throughout. A real submission through the
live `GET /api/v1/workflows` returned the exact capability, input text,
and state recorded — confirmed against a completely fresh `curl`
round-trip, not just the test suite. The `capability` query filter
correctly returned an empty list for an unrelated capability. The four
`external_service`-marked tests in
`tests/integration/test_workflow_state_machine_persistence.py`
(including the new submission-history round-trip test) all passed
directly against the real Mac Postgres.

## Related Decisions

- [ADR-0006: Persistence, State, and Recovery](ADR-0006-persistence-state-and-recovery.md) — the atomic-commit-per-transaction discipline this ADR's insert follows
- [ADR-0010: Security, Identity, Authorization, and Trust Boundaries](ADR-0010-security-identity-authorization-and-trust-boundaries.md) — `LocalDevelopmentAuthorizationPolicy`'s single-synthetic-principal limitation this ADR inherits unchanged
- [ADR-0015: Generic Capability Result Model](ADR-0015-generic-capability-result-model.md) — `result_data` is read via the existing workflow row, not duplicated into this history table
- [ADR-0023: `assignment.route` — Team-Based Assignment Routing](ADR-0023-assignment-route-capability.md) — the feature whose dashboard UI motivated this history endpoint

## References

- `src/ai_platform/orchestrator/application/submission.py` — `SubmissionOrchestrator.submit`'s `NEW` path, where the history insert is added
- `src/ai_platform/adapters/persistence/orchestrator.py` — `commit_submission`'s existing atomic transaction, extended with one more insert
- `contracts/openapi/v1/workflow-api.openapi.json` — gains a `GET` method on the existing `/api/v1/workflows` path entry
