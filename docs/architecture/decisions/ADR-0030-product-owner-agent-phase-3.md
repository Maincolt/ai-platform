# ADR-0030: `product-owner-agent` — ADR-0026 Phase 3

- **Status:** Accepted
- **Date:** 2026-08-16
- **Supersedes:** None
- **Superseded by:** None

## Context

[ADR-0026](ADR-0026-autonomous-team-agents.md) authorized three autonomous
roles staged by phase. Phase 2 (`scrum-master-agent`, [ADR-0028](ADR-0028-scrum-master-agent-phase-2.md),
rounded out by [ADR-0029](ADR-0029-scrum-master-agent-action-set-expansion.md))
shipped, is live on the Mac Docker host, and has run real cycles
successfully against the repository owner's board. This ADR is **Phase
3**: `product-owner-agent` gains real backlog/sprint-scope write access.
The repository owner chose the **full ADR-0026 Decision 1 target set from
day one** for this role ("reprioritize the backlog, create/edit/close
tickets, adjust sprint scope") rather than the narrower-MVP-first path
Phase 2 took — Phase 2 already proved the safety machinery (kill switch,
budget cap, audit trail) under real autonomous load, so there is less
reason for a second, separate narrowing step here.

**Confirmed by re-reading migration 0009 before designing this**: no new
migration is needed. `agent.autonomous_kill_switch` is a genuine
platform-wide singleton (ADR-0026 Decision 7); `agent.autonomous_role_budget`
and `agent.autonomous_actions` already key on a `role` column. This ADR's
new state is just new rows with `role='product-owner'`.

**Refactor landing alongside this ADR**: with a second near-identical
runtime config about to exist, `configuration.py` gains a shared
`_AutonomousRoleRuntimeConfigBase` (environment, DB pool, agent identity,
readiness, the six `ai_router_*` fields, cadence, caps — the ~20 fields
`ScrumMasterRuntimeConfig` and `ProductOwnerRuntimeConfig` both need
unchanged) that both configs subclass, adding only their own credential
fields. `_autonomous_shared.py` (new) holds the two genuinely role-
agnostic pure helpers (`estimate_spend_cents`, `strip_markdown_json_fence`)
`scrum_master_agent/agent.py` already had, now shared instead of
duplicated a second time. Each role's actual dispatch/prompt/parsing
logic stays deliberately separate — different action verbs and
validation per role, so forcing that into a shared base would be a leaky
abstraction, not a useful one.

## Decision

### 1. Full action set, mapped onto the board's actual current schema

- **`create_ticket`** — add a draft issue to the board:
  `addProjectV2DraftIssue` (the same mutation `scrum-master-agent`'s
  `create_draft_item` already uses, separate credential/process).
- **`edit_ticket`** — edit an existing real issue's title/body: REST
  `PATCH /repos/{owner}/{repo}/issues/{number}`. Restricted to real
  issues only — same "never a draft item" boundary `scrum-master-agent`'s
  `add_comment`/`close_issue`/`relabel`/`reassign` already enforce.
  Editing a draft item's title/body via GraphQL's
  `updateProjectV2DraftIssue` mutation needs the draft issue's own node
  ID (distinct from the `ProjectV2Item` id every other action already
  uses), which the board fetch does not currently expose; recreating a
  draft via `close_ticket` + `create_ticket` covers the same need
  without adding a second ID concept for this pass.
- **`close_ticket`** — close an existing real issue/PR via REST. Same
  "never a draft item" restriction as `edit_ticket`.
- **`archive_draft_ticket`** — the draft-item counterpart to
  `close_ticket`, split into its own action type rather than one
  polymorphic action, so every action keeps the same "all required
  fields are always non-empty strings" invariant the strict
  discriminated-union parser already relies on (a `close_ticket` that
  sometimes needs `issue_url` and sometimes needs `item_id` instead
  would break that invariant). Uses `archiveProjectV2Item(itemId: ...)`
  — confirmed this mutation takes the same `ProjectV2Item` id every
  other action already uses, not a draft-specific id, so no new ID
  surface is needed. Reversible (GitHub items can be unarchived), same
  "cheap to notice and undo by hand" category as everything else this
  role and `scrum-master-agent` do.
- **`reprioritize`** — reorder an item's position on the board:
  `updateProjectV2ItemPosition` (GitHub's native backlog-ordering
  primitive; `afterId: null` moves to top). No new board field needed.
- **`adjust_sprint_scope`** — move an item's Status value between a
  designated "Backlog" option and the active-sprint options, via the
  same `updateProjectV2ItemFieldValue` mutation mechanism `scrum-master-
  agent`'s `set_status` already uses (separate code path and credential,
  same GraphQL call shape). The live board has no dedicated Iteration
  field configured, and GitHub's API does not support creating one
  programmatically — this is a pragmatic mapping onto the board's actual
  current schema, not the "real" iteration-based mechanism GitHub
  Projects v2 natively supports. Revisit if a real Iteration field is
  ever added to the board.

### 2. Same execution model, cadence, and caps as `scrum-master-agent`

Single-shot propose-then-dispatch (ADR-0028 Decision 3, unchanged
reasoning — still the simpler, still-bounded shape, still deferring true
multi-turn iteration). Hourly `PeriodicService` cycle. Same hard daily
cap shape: 10 actions AND $1.00 estimated spend per UTC day — the
repository owner's explicit choice to reuse Phase 2's proven defaults
rather than tune new numbers per role. This role's budget is **tracked
independently** from `scrum-master-agent`'s (`role='product-owner'` vs.
`role='scrum-master'` rows in the same table) — the two roles' caps do
not share a pool.

### 3. New credential: a separate, `product-owner`-only PAT

Per ADR-0026 Decision 3 (per-role least privilege) and ADR-0028 Decision
4's precedent, this is a **different** PAT from every other role's,
scoped identically to `scrum-master-agent`'s: `project` (classic) +
`repo`. Same "the `repo` scope's push capability is a boundary this
agent's code never exercises, not one the token itself withholds"
posture as every prior role.

### 4. Not a Capability Registry entry

Same as `scrum-master-agent`: no `ExecuteTask` consumption, no
`registry.json` binding, not on the dashboard's Agent Status grid, a
minimal `/health/ready` for Docker's own healthcheck only.

## Security

Same threat model and mitigations as ADR-0028's Security section:
fetched board content is untrusted input; the enumerable, code-dispatched
action set bounds what a successful prompt injection can cause to one
in-scope action; the audit trail and kill switch provide after-the-fact
detection and containment, not prevention. The six actions here are the
same "cheap to notice and undo by hand" category as `scrum-master-
agent`'s — a wrong ticket edit, an unwanted close, a bad reprioritization,
or an incorrect sprint-scope change are all reversible by a human in
seconds, unlike a merge or a deploy.

## Alternatives Considered

### Narrower MVP first, mirroring Phase 2's rollout shape

Considered and explicitly rejected by the repository owner for this
phase: Phase 2's narrowing was driven by this being the *first* real-
write-access role ever built, with an unproven execution model
(`PeriodicService`-driven, not Workflow-driven) and unproven safety
machinery. Both are now proven under real autonomous load, so a second
narrowing step here would mostly just delay reaching this role's actual
target scope without a comparable amount of new uncertainty to hedge
against.

### A real GitHub Projects v2 Iteration field for `adjust_sprint_scope`

Rejected for now: GitHub's API does not support creating Iteration
fields programmatically, and the repository owner has not configured one
manually on the live board. The Status-field mapping is a pragmatic
stand-in, documented as such, not a permanent design commitment.

## Consequences

### Positive

- Completes ADR-0026's second autonomous role, with its full target
  action set delivered in one pass.
- Zero new migration — `agent.autonomous_*`'s per-role design (ADR-0028)
  pays off immediately for a second role.
- The `_AutonomousRoleRuntimeConfigBase`/`_autonomous_shared.py` refactor
  keeps the marginal engineering cost of adding this role smaller than
  Phase 2's, without forcing a shared abstraction onto the genuinely
  different per-role dispatch logic.

### Negative

- A second role now holds real write access to the same board
  `scrum-master-agent` already writes to — two independent autonomous
  processes acting on the same shared state, each unaware of the other's
  in-flight decisions within an hour-long cycle window. Not a new risk
  category (both are already bounded by the same enumerable-action-set/
  audit/kill-switch machinery), but a new interaction surface worth
  watching in the audit log.
- `adjust_sprint_scope`'s Status-field mapping is a pragmatic
  approximation of "real" sprint/iteration semantics, not the mechanism
  GitHub Projects v2 actually provides for this concept.

## Related Decisions

- [ADR-0026: Autonomous Team Agents](ADR-0026-autonomous-team-agents.md) — Decision 1's Product Owner action-set grant this ADR implements in full
- [ADR-0028: `scrum-master-agent` Phase 2](ADR-0028-scrum-master-agent-phase-2.md) — the execution model, safety machinery, and credential pattern this ADR reuses unchanged
- [ADR-0029: `scrum-master-agent` action-set expansion](ADR-0029-scrum-master-agent-action-set-expansion.md) — the immediately-preceding fast-follow that proved the per-role-budget/audit design already generalizes cleanly to a new action

## References

- `src/ai_platform/agents/scrum_master_agent/tracker.py` — the GraphQL/REST call patterns `product_owner_agent/tracker.py` extends with backlog-specific mutations
- `src/ai_platform/agents/_autonomous_shared.py` — the two pure helpers now shared between both autonomous roles

## Implementation Status

Accepted; implementation follows in the accepting PR.
