# ADR-0032: Autonomous Agent Status — Dashboard Visibility

- **Status:** Accepted
- **Date:** 2026-08-16
- **Supersedes:** None
- **Superseded by:** None

## Context

The dashboard's Agent Status grid (`GET /api/v1/agents`, added alongside
the dashboard itself) renders whatever bindings exist in `registry.json`
— by design, "capabilities a Workflow can be submitted to"
(`docs/architecture/decisions/README.md`'s own framing of that endpoint).
`scrum-master-agent`, `product-owner-agent`, and `principal-developer-agent`
(ADR-0028/ADR-0030/ADR-0031) were deliberately excluded from that view:
they consume no `ExecuteTask` commands, so there is nothing for a
Workflow to target, and ADR-0028 Decision 6 explicitly chose no
`registry.json` binding for exactly that reason. That decision remains
correct — but it left these three roles' state visible only via direct
`psql` queries (`docs/operations/README.md` Section 11), which the
repository owner asked to change with a small dashboard panel.

The repository owner also asked, separately, to migrate the dashboard's
styling to Element Plus — the platform's first adopted UI component
library; every dashboard component until now has been hand-rolled scoped
CSS against custom-property design tokens (`frontend/dashboard/src/style.css`).
Bundled with this ADR because both changes land in the same PR and touch
the same files.

## Decision

### 1. `platform` reads the `agent` Postgres schema for the first time

Every process in this platform has, until now, stayed within its own
schema (`orchestrator` for `platform`, `agent` for every Agent
deployable). This ADR crosses that boundary for the first time: the
Workflow API process opens a **second** connection pool, authenticated
as the same `ai_platform_agent_app` Postgres role the three autonomous
roles already use (the `dsn_agent` secret, now also mounted into
`platform`), and reads `agent.autonomous_kill_switch`/
`agent.autonomous_role_budget`/`agent.autonomous_actions` through two
new, `SELECT`-only `AutonomousStatePort` methods
(`list_role_budgets`, `list_recent_actions`). No new Postgres role, no
new migration, no write path — `platform` never calls
`record_action`/`record_budget_usage`, only the two new read methods.
This is safe specifically because it is read-only and the role already
has the grants; a write capability from `platform` into `agent` state
would be a materially different, larger decision this ADR does not make.

### 2. New endpoint: `GET /api/v1/autonomous-agents`

Mirrors `GET /api/v1/agents`'s shape exactly (same `AppState`-dependency
pattern, same correlation-header handling). Response:
`kill_switch_engaged` (bool), `role_budgets` (one entry per role with a
budget row today), `recent_actions` (most recent rows across all three
roles, newest first, bounded count). Not part of the Capability
Registry's `registry.json` contract — a separate, simpler read model
specific to this one dashboard panel.

### 3. Graceful degradation, not a hard startup requirement

The new `agent_database_dsn` config field is **optional**
(`PlatformRuntimeConfig`). If unset, `platform` starts normally and the
new endpoint returns an empty/inert response
(`kill_switch_engaged=false`, empty lists) rather than failing to start
or 500ing — the same posture `GET /api/v1/agents` already has toward a
missing/unloadable `registry.json`. This keeps the change strictly
additive: any existing deployment of `platform` without the new secret
mounted keeps working unchanged.

### 4. Element Plus adopted for the whole dashboard

The repository owner's explicit choice, covering every existing
component (`App.vue`, `AgentCard.vue`, `AssignmentForm.vue`,
`HistoryList.vue`) and the new `AutonomousAgentsPanel.vue` — not scoped
to the new panel alone, so the page stays visually consistent rather
than mixing a styled-library panel into an otherwise hand-rolled page.
The existing custom-property design tokens in `style.css` are retired in
favor of Element Plus's own component-level theming (including its
built-in dark-mode mechanism, toggled from the same
`prefers-color-scheme` signal the retired tokens used).

## Security

No new data-classification concern: kill-switch state, budget counters,
and action metadata (role, action type, target, result status) are
operational telemetry already durably stored and already readable via
direct `psql` access by anyone with Docker host access — this ADR only
adds a second, browser-facing read path to state that was never secret,
gated behind whatever access control already protects the dashboard
itself (none beyond network placement, unchanged by this ADR). `inputs`
(the model's own stated `rationale` and raw proposed-action fields) is
deliberately **not** exposed by the new endpoint or panel — only
`result_status`, not the full audit row — since that field can contain
arbitrary text sourced from fetched board/PR content (untrusted input,
per every prior autonomous-role ADR's Security section) and rendering it
unescaped in a browser is unnecessary surface this ADR doesn't need to
take on.

## Alternatives Considered

### Add these three roles to `registry.json` instead

Rejected again, for the same reason ADR-0028 Decision 6 already gave:
they consume no `ExecuteTask` commands, so a Registry binding would
misrepresent them as Workflow-targetable capabilities they are not.

### A write-capable path from `platform` into `agent` state (e.g. toggling the kill switch from the dashboard)

Considered and deferred: meaningfully larger scope (authorization,
audit-of-the-audit-toggle, a write credential for a process that has
never held one) for a feature not requested. The kill switch stays
`psql`-only for now; this ADR only adds visibility.

## Consequences

### Positive

- The three autonomous roles' state is finally visible somewhere other
  than direct SQL, closing the gap ADR-0028 Decision 6 knowingly left
  open.
- Read-only, degrade-gracefully design keeps the change low-risk despite
  being the first cross-schema read in the platform.
- Element Plus gives the dashboard a real component library instead of
  hand-rolled CSS per component, going forward.

### Negative

- `platform` now depends on a second Postgres role/secret it didn't
  need before — one more thing to keep provisioned correctly across
  environments.
- The dashboard's whole visual language changes in one PR (every
  existing component re-styled), a larger review surface than the panel
  alone would have been.
- The `10`/`100` daily-cap display maxima in the new panel are hardcoded
  to the currently-deployed values, not read from config — they will
  silently go stale if the deployed caps ever change without updating
  the frontend too.

## Related Decisions

- [ADR-0028: `scrum-master-agent` Phase 2](ADR-0028-scrum-master-agent-phase-2.md) — Decision 6's "no Registry binding" choice this ADR's panel exists to compensate for
- [ADR-0026: Autonomous Team Agents](ADR-0026-autonomous-team-agents.md) — Decision 7's audit trail/kill switch/spend cap, now visible in the dashboard

## References

- `src/ai_platform/api/app.py` — `list_agents`'s shape, mirrored by the new endpoint
- `src/ai_platform/adapters/persistence/autonomous.py` — the four existing `PsycopgAutonomousStatePort` methods the two new ones extend

## Implementation Status

Accepted; implementation follows in the accepting PR.
