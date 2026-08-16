# ADR-0028: `scrum-master-agent` — ADR-0026 Phase 2, Real Autonomous Board Write Access

- **Status:** Accepted
- **Date:** 2026-08-16
- **Supersedes:** None
- **Superseded by:** None

## Context

[ADR-0026](ADR-0026-autonomous-team-agents.md) authorized three autonomous
roles to take real, hard-to-reverse actions with no per-action human
approval, staged by phase. Phase 1 ([ADR-0027](ADR-0027-scrum-status-capability.md),
`scrum.status`) is read-only and is genuinely live-verified against the
repository owner's real GitHub Projects v2 board. This ADR is **Phase 2**:
`scrum-master-agent` gains real write access to that board — the
lowest-blast-radius of the three future roles (no merge, no deploy).

This is the first Agent deployable that is **not driven by a Workflow
submission**. Every capability before this consumes an `ExecuteTask`
Kafka command and responds once. `scrum-master-agent` instead wakes up
on its own schedule and decides what to do — a genuinely new execution
model, confirmed via direct research to have no existing precedent to
copy in this codebase beyond its individual building blocks:

- The "wake up periodically" primitive already exists and is generic:
  `PeriodicService` (`src/ai_platform/runtime/lifecycle.py:249-280`),
  already used by the Orchestrator's `DeadlineReconciler`/availability-
  refresh loops. Reused unchanged for this agent's cycle.
- `agent.audit` already exists but is workflow-scoped (`workflow_id`
  column) — not a fit for actions with no Workflow behind them. A new,
  purpose-built table is needed.
- Every Agent deployable already shares one Postgres `agent` schema —
  new state is a new migration into that same schema, following
  `0007_agent_provider_call_claims.sql`'s shape.
- No config anywhere in this platform is re-read after process
  startup — a kill switch needs `PeriodicService`'s own operation to
  check a DB-backed flag every cycle, since nothing else re-reads.
- Agents never touch a Kafka producer directly. Since this agent needs
  no `ExecuteTask` consumption and publishes no events in this phase,
  it is the first Agent deployable that skips Kafka entirely.

## Decision

### 1. Action scope: three of the six ADR-0026 Decision 1 actions

The repository owner chose to start narrower than ADR-0026's full
target set (create/close/relabel/reassign/comment/move-card), shipping
the three that need no specific-repo target and are lowest-complexity
to get right first:

- **`set_status`** — move a card by changing its Status field value
  (`updateProjectV2ItemFieldValue` GraphQL mutation).
- **`add_comment`** — comment on an existing issue/PR
  (`POST /repos/{owner}/{repo}/issues/{number}/comments`, owner/repo/
  number parsed from the item's own URL).
- **`create_draft_item`** — add a draft issue to the board
  (`addProjectV2DraftIssue` mutation, project-scoped, no repo needed).

`close`/`relabel`/`reassign` are deferred to a fast-follow-up once these
three are proven safe in production.

### 2. Cadence and hard safety caps

- **Hourly** wake-up.
- **Hard daily cap: 10 actions AND $1.00 estimated AI spend, whichever
  hits first** (repository owner's explicit choice). Once hit, the
  agent skips write behavior for the rest of the UTC day; it still
  checks in on schedule and does nothing, and resets at UTC midnight.
  Spend is estimated from a small hardcoded per-model $/1K-token table
  covering only the ADR-0017 Decision 3-approved models
  (`claude-haiku-4-5`/`gpt-5-mini`), applied to real
  `ProviderCallUsageRecord` token counts — an estimate, not exact
  provider billing, documented as such in code.

### 3. Execution model: single-shot propose, then dispatch

ADR-0026 Decision 2 describes an iterative tool-calling loop (model
proposes one action, sees the result, proposes the next). This first
real-write-access build uses a simpler, still-bounded shape instead:
one AI Router call returns a bounded JSON array of proposed actions
(type + params + rationale); Agent code validates each against the
3-action allowlist and per-field bounds, then dispatches each
sequentially and independently — one action's failure does not block or
roll back the others (there is nothing to roll back; a posted comment
cannot be unposted). Same "one bounded AI call, strict JSON-shape
parse, reject the whole batch on any mismatch" discipline every prior
capability already uses. True multi-turn iteration (react to one
action's result before proposing the next) is deferred as a later
enhancement, not required for Phase 2.

### 4. New credential: a separate, `scrum-master`-only PAT

Per ADR-0026 Decision 3 (per-role least privilege), this is a
**different** PAT from `scrum-status-agent`'s, scoped to:
- `project` (classic scope) — write access to Projects v2.
- `repo` — needed for posting issue comments.

GitHub's `repo` scope is all-or-nothing and technically includes push
access; the "no push" boundary this agent promises is enforced in code
(`tracker.py` never calls a push/force-push endpoint), not by the token
itself. Starts as an obviously-fake placeholder at deployment time,
same placeholder-then-real path `scrum-status-agent`'s credential
followed.

### 5. Safety mechanisms — all new, all DB-backed, checked every cycle

- **Kill switch**: `agent.autonomous_kill_switch`, one row, checked
  first, before any GitHub call. Toggled by direct SQL — no redeploy
  needed to engage it.
- **Daily budget**: `agent.autonomous_role_budget` (per role, per UTC
  day, actions-used + estimated-spend-used counters), checked second,
  before the board fetch.
- **Audit trail**: `agent.autonomous_actions` — one row per attempted
  action (role, action type, target, inputs, result, timestamp),
  written immediately after each dispatch attempt. After-the-fact, not
  preventive, per ADR-0026 Decision 7 — this makes every action
  reconstructable, not stoppable in advance.
- **Least privilege**: this agent's PAT never has merge or deploy
  scope; `scrum-status-agent`'s PAT is untouched and stays read-only.

### 6. Not a Capability Registry entry

This agent does not consume `ExecuteTask` commands, so it is not
something a Workflow can be submitted to. It gets no `registry.json`
binding and will not appear on the dashboard's Agent Status grid — that
view is specifically "capabilities a Workflow can target," which this
is not. It keeps a minimal `/health/ready` endpoint for Docker's own
healthcheck only.

## Security

Fetched board/issue content remains untrusted input to the provider,
same posture as every prior fetch-based capability. The new risk this
ADR actually introduces — a successful prompt injection causing one
real, unwanted-but-in-scope action — is exactly the risk ADR-0026's own
Security section already named and accepted for this whole autonomous-
agent line; nothing here changes that analysis. The three chosen
actions are deliberately the lowest-consequence available: a wrong
status change, an unwanted comment, or a spurious draft item are all
cheap to notice and undo by hand, unlike a merge or a deploy. The
`repo`-scope-includes-push caveat (Decision 4) is the one place this
ADR's actual credential is more powerful than what the code will ever
use it for — worth remembering if this PAT is ever reused elsewhere.

## Alternatives Considered

### True multi-turn tool-calling loop from day one

Rejected for Phase 2 specifically to keep the first real-write-access
build's blast radius and complexity bounded together — see Decision 3.
Revisit once the single-shot shape has run safely in production.

### Reusing `agent.audit` instead of a new table

Rejected: `agent.audit`'s schema requires a `workflow_id`, and these
actions have no Workflow behind them — forcing them into that shape
would be semantically wrong, not just inconvenient.

### Wiring this agent through the existing `build_agent_process`/Kafka path

Rejected: that path is built entirely around consuming `ExecuteTask`
commands and publishing `TaskCompleted`/`TaskFailed` events, none of
which apply here. A parallel, leaner process-composition function with
zero Kafka wiring is simpler and more honest about what this agent
actually is.

## Consequences

### Positive

- Delivers real autonomous write access for the first time, narrowly
  scoped to the lowest-consequence action set and a conservative daily
  cap, exactly as the repository owner chose.
- The first Agent deployable that needs no Kafka principal, topic, or
  ACL at all — genuinely simpler deployment footprint than every
  capability before it.
- Kill switch, budget cap, and audit trail are all real, DB-backed
  mechanisms, not documentation-only promises.

### Negative

- A new, genuinely different execution model (`PeriodicService`-driven,
  not Workflow-driven) to operate and reason about alongside the
  Workflow/Kafka model every other Agent uses.
- A new Postgres migration and a new persistence port
  (`AutonomousStatePort`) — new engineering surface beyond a capability
  contract.
- The estimated-spend cap is an approximation (hardcoded per-model
  rates against token counts), not exact provider billing — could
  under- or over-count real spend.
- `close`/`relabel`/`reassign` are explicitly not built yet; this ADR
  does not close out ADR-0026 Decision 1's full target action set.

## Related Decisions

- [ADR-0006: Persistence, State, and Recovery](ADR-0006-persistence-state-and-recovery.md) — the `agent` schema this ADR's new migration extends
- [ADR-0007: Agent Execution Model and Lifecycle](ADR-0007-agent-execution-model-and-lifecycle.md) — the request/response model this agent deliberately departs from
- [ADR-0017: AI Router Follow-Up Decisions and Multi-Agent Readiness Routing](ADR-0017-ai-router-follow-up-decisions.md) — the approved model list the spend-estimate table covers
- [ADR-0026: Autonomous Team Agents](ADR-0026-autonomous-team-agents.md) — this ADR is ADR-0026's Phase 2
- [ADR-0027: `scrum.status`](ADR-0027-scrum-status-capability.md) — Phase 1; the board-fetch shape and GitHub-credential pattern this ADR extends with write access

## References

- `src/ai_platform/agents/scrum_status_agent/board.py` — the read-side template this ADR's `tracker.py` extends with write mutations
- `src/ai_platform/runtime/lifecycle.py` — `PeriodicService`, reused unchanged

## Implementation Status

Accepted; implementation follows in the accepting PR (domain module,
migration, runtime wiring, deployment wiring, and live verification
against the repository owner's real board, with an explicit warning
before any real write action is taken for the first time).
