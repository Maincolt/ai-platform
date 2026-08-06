# ADR-0015: Generic Capability Result Model

- **Status:** Accepted
- **Date:** 2026-08-06
- **Supersedes:** None (extends, does not contradict, the accepted parts
  of Vertical Slice 01's contract/domain/persistence design)
- **Superseded by:** None

## Context

Implementing ADR-0014's `text.summarize` capability surfaced a coupling
that was not visible at the architecture-decision level and that ADR-0014
did not itself resolve: `text.word-count`'s specific result shape —
`word_count: integer` — is hardcoded through four separate layers, not
just inside the Test Agent implementation:

1. **Wire contracts.** `contracts/json-schema/v1/execute_task.schema.json`
   constrains `payload.capability` to `const: "text.word-count"`.
   `task_completed.schema.json` does the same and requires a
   `payload.word_count: integer` field with no generic alternative.
2. **Agent domain/persistence.** `AgentOutcome`
   (`src/ai_platform/agents/domain/outcomes.py`) has a typed `word_count`
   field, and the `agent.outcomes` table
   (`infrastructure/migrations/0002_agent_schema.sql`) has a `word_count
   INTEGER` column with a CHECK constraint pairing it against
   `failure_code`.
3. **Orchestrator domain/persistence.** The `Workflow` aggregate's
   terminal `COMPLETED` state and the `orchestrator.workflows` table
   (`infrastructure/migrations/0001_orchestrator_schema.sql`) carry
   `result_word_count INTEGER`, the same pattern one layer up.
4. **Public API contract.**
   `contracts/json-schema/v1/workflow_submit_response.schema.json`'s
   `result` object requires `word_count` specifically.

A second capability with a structurally different result (`summary:
string` instead of `word_count: integer`) cannot be added without
changing all four layers. This is real, cross-cutting, difficult-to-reverse
refactoring — not new capability code — so it gets its own ADR rather than
being absorbed silently into Sprint 9's implementation, per this
repository's own rule that architecture is not to be introduced implicitly
through implementation.

The repository owner has directed that this be generalized properly now,
rather than worked around per-capability, so that a third and fourth
capability do not repeat this discovery.

## Decision Drivers

- ADR-0004's contract standards (JSON Schema Draft 2020-12, versioned,
  exact-identity validation) — generalization must not weaken contract
  validation, only stop conflating "the one capability that happens to
  exist" with "the platform's result model."
- ADR-0006's atomic persistence units — the migration must preserve
  existing atomicity/CHECK-constraint guarantees, just against a generic
  shape.
- ADR-0008's Registry model, which already treats capability identity as
  configuration data (`CapabilityBinding.capability_name`), not a code
  constant — the result model should follow the same principle.
- Backward safety: Sprints 1–8 already proved the `text.word-count` path
  end-to-end, including real crash-recovery and real-broker validation.
  This change must not silently regress that evidence; the existing
  behavior for `text.word-count` must be provably unchanged after this
  migration, not just "probably fine."

## Decision

### 1. Wire contracts: capability stays a real field, result becomes discriminated

`payload.capability` in `ExecuteTask` changes from `const: "text.word-count"`
to `enum: ["text.word-count", "text.summarize"]` (extended again for each
future capability — an explicit, reviewable list, not an open string, so
an unrecognized capability value fails contract validation immediately
rather than being silently accepted).

`TaskCompleted.payload` drops the required `word_count` field and adds a
required `result: object` field whose internal shape is validated by a
JSON Schema `allOf`/`if`/`then` discriminated on `capability` — each
capability's result shape is still exactly and strictly validated, just
selected by the same `capability` field already present in the envelope,
not hardcoded as the only possible shape:

```json
{
  "allOf": [
    {
      "if": { "properties": { "capability": { "const": "text.word-count" } } },
      "then": {
        "properties": {
          "result": {
            "required": ["word_count"],
            "properties": { "word_count": { "type": "integer", "minimum": 0 } }
          }
        }
      }
    },
    {
      "if": { "properties": { "capability": { "const": "text.summarize" } } },
      "then": {
        "properties": {
          "result": {
            "required": ["summary"],
            "properties": { "summary": { "type": "string", "minLength": 1, "maxLength": 2000 } }
          }
        }
      }
    }
  ]
}
```

`TaskFailed.payload` is unchanged — `failure_code`/`summary` are already
capability-agnostic and need no discrimination.

This keeps the logical contract names (`ExecuteTask`, `TaskCompleted`,
`TaskFailed`) and the Registry's existing `command_contract_name`/
`event_contract_names` model exactly as ADR-0008 already defined them —
capabilities share contract names and are distinguished by the existing
`capability`/`capability_version` fields, not by inventing a new contract
per capability.

### 2. Agent domain and persistence: a generic result payload

`AgentOutcome.word_count: int | None` becomes
`AgentOutcome.result_data: Mapping[str, object] | None` — an
arbitrary, capability-owned JSON-compatible payload. The existing success/
failure invariant (`(result is None) xor (failure_code is None)`) is
preserved, just against the renamed/generalized field. Each Agent
constructs its own `result_data`:
`{"word_count": n}` for `text.word-count`, `{"summary": text}` for
`text.summarize`.

`agent.outcomes.word_count INTEGER` becomes `agent.outcomes.result_data
JSONB`, in a new migration (schema version 2 for the `agent` component) —
existing migrations (`0001`, `0002`) are not edited, per this repository's
migration append-only convention; a new versioned migration file performs
the column change and re-publishes `schema_version`.

### 3. Orchestrator domain and persistence: the same generalization, one layer up

`Workflow`'s terminal-completion value object
(`WorkflowResult.word_count: int`) becomes `WorkflowResult.result_data:
Mapping[str, object]`. `orchestrator.workflows.result_word_count INTEGER`
becomes `orchestrator.workflows.result_data JSONB`, in a new migration
(schema version 2 for the `orchestrator` component), following the same
append-only convention.

The Orchestrator's terminal-event processing
(`PsycopgOrchestratorPersistence.apply_terminal_outcome`) already
extracts the completion payload generically from the durable command
evidence for its identity-matching check (`payload_data.get("input") ==
intent.result_text` — see `src/ai_platform/adapters/persistence/orchestrator.py`);
this becomes matching against the discriminated `result` object's
capability-specific field instead of assuming `result_text`/`word_count`.

### 4. Public API: a generic, capability-scoped result object

`workflow_submit_response.schema.json`'s `result` object drops
`required: ["word_count"]` and `additionalProperties: false` in favor of
`additionalProperties: true` with no fixed inner shape at the contract
level. The public API is intentionally looser here than the internal wire
contracts (Section 1): callers already know which capability they
submitted and can interpret the result accordingly, and requiring the API
schema to enumerate every capability's result shape would force a contract
version bump for every new capability, which the wire-contract
discrimination in Section 1 already avoids by design. This is a narrower
contract change than Section 1's, deliberately: the internal event
contracts stay strictly validated per capability because they are
durable, replayable evidence; the public API response is a read view and
does not need the same strictness to remain safe.

### 5. Migration safety for the existing `text.word-count` path

Both new migrations are applied and the full existing test suite
(unit, component, and the Sprint 6/7 real-service `external_service`
suite) is re-run against `text.word-count` specifically after this change,
with no change to its observed behavior, before any `text.summarize` code
is exercised. This is the concrete evidence that generalization did not
regress the already-proven path, not an assumption.

## Consequences

### Positive

- A third and fourth capability need zero further schema/persistence
  changes to introduce a new result shape — only a new `if`/`then` branch
  in the two wire-contract schemas and a new migration-free `result_data`
  payload from the Agent, matching the pattern this ADR establishes.
- The public API stays stable across capability additions (Section 4) —
  no client-facing contract version bump per new capability's result
  shape.
- Internal wire contracts remain exactly and strictly validated per
  capability (Section 1) — generalization does not trade away contract
  rigor for flexibility.

### Negative

- Two new migrations against tables that already hold real data from
  Sprints 6–8 testing (though that data is disposable local-development
  data, not anything requiring a data-preserving migration path).
- The JSON Schema `if`/`then` discrimination pattern is more complex to
  read than a flat required-field list; contract test coverage must
  exercise both branches explicitly, and a third capability makes a
  fourth `if`/`then` branch, not a cleaner generalization — this is an
  accepted, bounded complexity, not eliminated by this decision.
- Every piece of code that currently reads `word_count` (Agent, Orchestrator
  persistence, tests, fixtures) must be updated in the same change, which
  is a broad, mechanical, but real diff across an already-tested part of
  the codebase.

## Alternatives Considered

### Separate contract family and separate tables per capability (no shared generalization)

Rejected as the primary approach (though offered to and declined by the
repository owner as an alternative scoping): avoids touching
`text.word-count`'s existing contracts/tables/domain code at all, lower
regression risk this sprint, but repeats the same hardcoding problem for
every future capability instead of resolving it once.

### A single untyped JSON blob with no wire-contract discrimination

Rejected: dropping the `if`/`then` discrimination in Section 1 and just
accepting `result: object` with `additionalProperties: true` at the wire
level would be simpler, but would weaken ADR-0004's contract rigor for
durable, replayable event evidence specifically — the one place this
repository has been most insistent on exact validation. The added
complexity of discriminated validation is kept where it matters (internal
event contracts) and dropped where it does not (the public API, Section 4).

## Testing Strategy

- Existing `text.word-count` unit/component/contract tests are updated to
  use `result_data`/discriminated payload shapes and must continue passing
  unchanged in behavior.
- New contract tests validate both `if`/`then` branches of the discriminated
  `TaskCompleted` schema (a `text.word-count` result missing `word_count`
  is rejected; a `text.summarize` result missing `summary` is rejected;
  each capability's result does not accidentally validate against the
  other's branch).
- The Sprint 6/7 real-service `external_service` suite is re-run against
  `text.word-count` after migration, per Section 5, as the concrete
  no-regression evidence for this ADR specifically (not assumed from the
  unit suite alone).

## Related Decisions

- [ADR-0004: API and Contract Standards](ADR-0004-api-and-contract-standards.md)
- [ADR-0006: Persistence, State, and Recovery](ADR-0006-persistence-state-and-recovery.md)
- [ADR-0008: Capability Registry and Agent Discovery](ADR-0008-capability-registry-and-agent-discovery.md)
- [ADR-0014: AI Router and the First AI-Backed Agent](ADR-0014-ai-router-and-first-ai-backed-agent.md) — this ADR resolves the result-model gap ADR-0014's implementation surfaced

## References

- [Vertical Slice 01, Section 10 — Message Payloads](../../implementation/vertical-slice-01.md)
- `contracts/json-schema/v1/execute_task.schema.json`,
  `task_completed.schema.json`, `task_failed.schema.json`,
  `workflow_submit_response.schema.json`
- `infrastructure/migrations/0001_orchestrator_schema.sql`,
  `0002_agent_schema.sql`
