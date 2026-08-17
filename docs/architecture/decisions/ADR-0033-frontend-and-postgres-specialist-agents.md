# ADR-0033: `frontend-specialist-agent` and `postgres-specialist-agent` — Extending ADR-0026's Autonomous Roles

- **Status:** Accepted
- **Date:** 2026-08-17
- **Supersedes:** [ADR-0026](ADR-0026-autonomous-team-agents.md) Decision 1, narrowly — adds two roles to the authorized set; every other part of ADR-0026 (execution model, safety machinery, phasing rationale) is reused unchanged, not re-litigated.
- **Superseded by:** None

## Context

ADR-0026 authorized exactly three autonomous roles (Scrum Master,
Product Owner, Principal Developer), all now live on the Mac Docker
host. Decision 8 described that ADR as authorizing "the full end-state
architecture" for those three specifically — not an open-ended
authorization for arbitrary future roles. `SECURITY.md`'s own carve-out
text is explicit about this boundary: *"Any action outside a role's
explicitly granted set, **any new role**, and every other AI Agent or
automation in this platform remain fully subject to this section's
approval requirement unmodified."* Adding a new autonomous role
therefore requires its own ADR-level decision and its own explicit
`SECURITY.md` amendment — this ADR is that decision for two more roles
the repository owner requested.

The repository owner initially asked for four new roles: a Vue.js
frontend specialist, a Node.js backend specialist, a Postgres
specialist, and an Oracle Database specialist. Two of those don't
correspond to anything in this codebase — the backend is Python
(FastAPI), and the only database anywhere in this repository is
Postgres — so only the Vue.js frontend and Postgres roles are defined
here. Confirmed via direct question: both new roles get the **same
narrow, board/PR-level action shape** every existing role already
uses, not autonomous code writing (a categorically different, far
larger capability class this platform has never built and this ADR
does not introduce), and **review-only, no merge rights** — merge
authority stays concentrated in `principal-developer-agent` alone
rather than multiplying identities that can push to `main`.

**Zero new migration**: `agent.autonomous_kill_switch` is platform-
wide (ADR-0026 Decision 7); `agent.autonomous_role_budget`/
`agent.autonomous_actions` are already keyed on an arbitrary `role`
string (migration 0009). New state is just `role='frontend-specialist'`/
`role='postgres-specialist'` rows in the same tables every prior role
already writes to.

**First genuine 1:1 code reuse across two roles.** Every prior pair of
roles shared only the two pure helpers in `_autonomous_shared.py`
(`estimate_spend_cents`, `strip_markdown_json_fence`) — their actual
dispatch/prompt/parsing logic stayed deliberately separate, since each
role's real action set differed. These two roles are structurally
identical: same one action (`request_changes`), same dispatch logic,
differing only in role name, prompt wording, and which file-path
prefixes define "their" pull requests. That is a strong enough signal
to share the actual domain logic this time, not just pure helpers (see
Decision 2).

## Decision

### 1. Action scope: `request_changes` only, filtered to each role's domain

- **`frontend-specialist-agent`** — pull requests touching `frontend/`.
- **`postgres-specialist-agent`** — pull requests touching
  `infrastructure/migrations/`, `src/ai_platform/adapters/persistence/`,
  or `src/ai_platform/ports/persistence/`.

Filtering happens in Agent code, **before** the AI Router prompt is
built — a PR outside a role's domain is never shown to the model at
all, a tighter scope than relying on the model to self-filter and
lower token cost besides. No merge, no ticket creation: `close`/`merge`
capability is deliberately absent from the underlying port
(`PullRequestReviewPort` has no `merge` method at all), so "no merge"
is a structural fact about what the code can do, not a policy the
model or the Agent's dispatch logic chooses to honor — the same "the
boundary is what the code implements, not what the credential could
theoretically do" pattern every prior role's client already
established. Ticket creation is deferred as a possible fast-follow
(matching the ADR-0028→ADR-0029 precedent of shipping a narrower MVP
first), not part of this ADR's grant.

### 2. Shared implementation: one domain package, two thin deployments

- `src/ai_platform/agents/_pull_request_review_shared.py` — `PullRequestSnapshot`
  (number, title, `changed_file_paths`, the first port field of this
  kind — fetched via `GET /repos/{owner}/{repo}/pulls/{number}/files`,
  the same N+1-per-PR pattern `principal_developer_agent.source_control`
  already uses for `mergeable_state`), `PullRequestReviewPort` Protocol,
  `GitHubPullRequestReviewClient` (REST-only, same shape as
  `principal_developer_agent.source_control.GitHubSourceControlClient`
  minus everything merge-related).
- `src/ai_platform/agents/domain_review_agent/` — one shared package
  (singular, not one per role) whose `DomainReviewAgent` class is
  parametrized at construction by `role`, `domain_label` (prompt
  wording), and `path_prefixes`. Same kill-switch → budget → fetch →
  one AI call → strict parse → dispatch shape every prior `run_cycle()`
  already has; the two roles differ only in the three constructor
  arguments their own `build_*_process()` composition function passes.

### 3. Same cadence, caps, and per-role credential pattern as every prior role

Hourly `PeriodicService` cycle; 10 actions/day and $1.00 estimated
spend/day, tracked independently per role (repository owner's
consistent choice across every role built so far — no new numbers
introduced here). Two more separate PATs
(`github_token_frontend_specialist`, `github_token_postgres_specialist`),
`repo` scope only (review-only needs no `project` scope), each starting
as an obviously-fake placeholder until the repository owner supplies a
real one — the same "deployed but inert" posture every role's first
deployment has followed, and doubly appropriate here since this ADR is
genuinely new policy scope, not a continuation of an already-authorized
phase.

### 4. `SECURITY.md` re-amended, naming this ADR and both roles explicitly

Per `SECURITY.md`'s own "any new role... remain[s] fully subject to
this section's approval requirement" text, the existing "Narrow
exception (ADR-0026)" paragraph does not, on its own, cover these two
roles. A second paragraph is added, naming `ADR-0033` and both roles by
name and their one granted action, under the identical unconditional
requirements (enumerable action set, audit trail, kill switch, spend
cap) the original exception already demands.

## Security

Same threat model as every prior autonomous role: fetched PR content
(title, changed file paths) is untrusted input, and the enumerable,
code-dispatched action set bounds a successful prompt injection to one
in-scope action. These two roles have the **lowest blast radius of any
autonomous role built so far** — `request_changes` is not just
low-consequence like every prior role's actions, it is structurally
incapable of writing anything at all (no merge method exists in
`PullRequestReviewPort`, and there is no tracker/board write path
either), so a successful injection here can at most cause an unwanted
review comment, not a state change.

## Alternatives Considered

### Give these roles ticket-creation too, matching Product Owner's scope

Rejected for this pass, matching the narrower-MVP-first precedent
ADR-0028's rollout already established: ship the one clearly-scoped
action, revisit once it has run safely in production.

### A single parametrized "code review specialist" role instead of two separate deployments

Considered: since `DomainReviewAgent` is already generic over role/
domain/paths, one deployment could in principle serve multiple domains
by holding a list of `(domain_label, path_prefixes)` pairs and
reviewing across all of them. Rejected: it would blur the per-role
least-privilege/audit-trail boundary ADR-0026 Decision 7 relies on —
"which specialist proposed this action" stays unambiguous only if each
domain is its own Agent deployment with its own role name, credential,
and budget row.

## Consequences

### Positive

- Extends the autonomous-role line to two more real-world-useful
  domains without introducing any new capability class (no code
  writing, no merge) or new engineering primitive (zero new migration,
  reuses every existing safety mechanism unchanged).
- The first genuine shared-domain-logic reuse across roles keeps the
  marginal cost of adding a second review-only role smaller than the
  first.
- `SECURITY.md`'s anti-scope-creep design (explicitly excluding "any
  new role" from the prior exemption) worked as intended — it forced
  this ADR to exist and be explicit, rather than letting two more
  autonomous roles slip in under an old carve-out that never named
  them.

### Negative

- Two more autonomous role deployments to operate, each with its own
  credential and failure modes, on top of the three already running.
- The requested Node.js backend and Oracle Database roles are
  explicitly out of scope — if either technology is ever introduced to
  this codebase, those roles would need their own ADR at that time, not
  a retroactive claim on this one.

## Related Decisions

- [ADR-0026: Autonomous Team Agents](ADR-0026-autonomous-team-agents.md) — Decision 1's role list this ADR extends; every other Decision reused unchanged
- [ADR-0028: `scrum-master-agent` Phase 2](ADR-0028-scrum-master-agent-phase-2.md) — the narrower-MVP-first precedent Decision 1 follows
- [ADR-0031: `principal-developer-agent` Phase 4](ADR-0031-principal-developer-agent-phase-4.md) — the `SourceControlPort`/`mergeable_state`-fetch pattern `_pull_request_review_shared.py` reuses minus the merge path

## References

- `SECURITY.md` — "Human Approval for High-Impact Actions", re-amended by this ADR (Decision 4)
- `src/ai_platform/agents/principal_developer_agent/source_control.py` — the REST/error-handling pattern `_pull_request_review_shared.py` extends with a changed-files fetch

## Implementation Status

Accepted; implementation follows in the accepting PR. Both roles deploy
with placeholder credentials only — real PATs are a separate, later
step the repository owner supplies explicitly, same as every prior
role.

**Update (2026-08-17):** merged (PR #65) and deployed to the Mac Docker
host with obviously-fake placeholder credentials. Both services reach
`ready: true`; a live cycle on each correctly failed closed with a real
GitHub `401 Bad credentials` on the pull-request fetch — no AI Router
call was reached, no action was possible. Confirmed visually via a
Playwright screenshot: the dashboard's "Autonomous Agents" tab now
shows all five roles (`AutonomousAgentsPanel.vue`'s `KNOWN_ROLES`
extended), Frontend Specialist and Postgres Specialist both at zero
usage today. Real PATs for both roles still await the repository
owner's explicit supply.
