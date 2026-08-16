# ADR-0031: `principal-developer-agent` — ADR-0026 Phase 4

- **Status:** Accepted
- **Date:** 2026-08-16
- **Supersedes:** None
- **Superseded by:** None

## Context

[ADR-0026](ADR-0026-autonomous-team-agents.md) authorized three autonomous
roles staged by phase. Phase 2 (`scrum-master-agent`) and Phase 3
(`product-owner-agent`) are both live on the Mac Docker host and have run
real cycles against the repository owner's board without incident. This
ADR is **Phase 4**, the last phase ADR-0026 itself authorizes:
`principal-developer-agent` gains real pull-request review and **merge**
rights — the highest-blast-radius action of the three roles, and the
first genuinely irreversible one (a bad status change or a wrongly
closed ticket can be undone by hand; a merged commit is part of history).
ADR-0026 Decision 8 explicitly required the audit trail, kill switch, and
spend cap to be "exercised under real autonomous load from Phases 2–3"
before this phase — that condition is now met.

**Repository owner's explicit choice on merge eligibility** (via
`AskUserQuestion` before this ADR was written): **any PR whose GitHub-
computed `mergeable_state == "clean"`** (all required status checks
green, no merge conflicts) **is eligible — no additional human-applied
label gate.** This is the closer-to-ADR-0026's-original-framing option:
full autonomy, no human pre-filter on which PRs the agent even considers.
Reusing GitHub's own `mergeable_state` computation (rather than re-
deriving eligibility from raw check-run data) means this role trusts the
same signal the GitHub UI's own "Merge" button availability already
relies on.

**No new migration, again**: `agent.autonomous_kill_switch` (platform-
wide) and the per-`role`-keyed `agent.autonomous_role_budget`/
`agent.autonomous_actions` tables already cover a third role
unchanged — new state is just `role='principal-developer'` rows.

**Runtime wiring reuses the Phase 3 refactor**: `PrincipalDeveloperRuntimeConfig`
extends the same `_AutonomousRoleRuntimeConfigBase` (`configuration.py`)
`ScrumMasterRuntimeConfig`/`ProductOwnerRuntimeConfig` already do, adding
only this role's own credential fields (`github_token`/
`github_repo_owner`/`github_repo_name` — no project number, since this
role operates on a repository's pull requests directly, never the
Projects v2 board). `_autonomous_shared.py`'s two pure helpers
(`estimate_spend_cents`, `strip_markdown_json_fence`) are reused
unchanged a third time.

## Decision

### 1. Action scope: `request_changes` and `merge` — ADR-0026 Decision 1's full grant for this role

ADR-0026 Decision 1 named this role's target actions directly: "review
pull requests, request changes, merge." Unlike Scrum Master's six-action
target (of which only three shipped in Phase 2) or Product Owner's six-
action target, Principal Developer's grant is already this small —
there is no narrower MVP to carve out of it.

- **`request_changes`** — leave a "changes requested" review on a PR:
  REST `POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews` body
  `{"event": "REQUEST_CHANGES", "body": ...}`. No merge-eligibility gate
  — any open PR is a valid target.
- **`merge`** — merge a PR: REST
  `PUT /repos/{owner}/{repo}/pulls/{pull_number}/merge`. Gated on
  `mergeable_state == "clean"`, checked twice: once when the board
  snapshot is built for the AI Router prompt, and **again immediately
  before the actual merge call**, inside the same dispatch that makes
  it — closing the TOCTOU gap between "the PR looked mergeable when the
  cycle started" and "is it still mergeable right now." A PR that
  stopped being clean between those two checks (a new commit landed, a
  required check started failing, a conflict appeared) is refused with
  `TrackerActionFailedError`, not merged anyway.

### 2. No push, no force-push, no direct write to `main`

Same structural boundary every prior role's tracker/source-control client
enforces: `source_control.py` never calls a push or force-push endpoint,
and never writes directly to a branch — its only path to changing `main`
is the same `merge` REST call a human clicking GitHub's own "Merge pull
request" button would trigger, subject to the exact same branch-
protection rules (required checks, required reviews if configured) that
already apply to any human merging by hand. The `repo` classic OAuth
scope this role's PAT needs is technically all-or-nothing and includes
push capability; the boundary is what the code implements, never what
the token could theoretically do (ADR-0028 Decision 4's precedent,
applied identically here).

### 3. Same execution model, cadence, and cap shape as Phases 2–3

Single-shot propose-then-dispatch (ADR-0028 Decision 3, still not the
full multi-turn tool-calling loop ADR-0026 Decision 2 originally
described — three phases in and this simpler shape has not shown a need
for the more complex one yet). Hourly `PeriodicService` cycle. Same hard
daily cap shape as both other roles: 10 actions AND $1.00 estimated
spend per UTC day, tracked independently as `role='principal-developer'`
rows — not shared with either other role's budget.

### 4. New credential: a separate, `principal-developer`-only PAT

Per ADR-0026 Decision 3 and the established per-role least-privilege
precedent, a **different** PAT from all three other roles', scoped to
`repo` (covers PR read, review, and merge). This is the platform's
fourth distinct GitHub credential.

### 5. Deployed built and tested, but withheld from a real credential

Unlike Phases 2–3, this PR does **not** hand this role a real PAT or
bring the service up with one. `principal-developer-agent` is deployed
to the Mac Docker host with the same obviously-fake placeholder pattern
every prior role's credential started with, confirming it fails closed
against real GitHub `401`s exactly like `product-owner-agent` did. This
role's first real PAT — and by extension its first real, autonomous
merge against this repository's actual `main` branch — requires an
explicit, separate go-ahead from the repository owner, flagged
prominently outside this ADR at the point that action is actually taken.

## Security

Same threat model as ADR-0028/ADR-0030's Security sections — fetched
PR content (title, body, diff summary if included in the prompt) is
untrusted input, and the enumerable, code-dispatched action set bounds a
successful prompt injection to one in-scope action. Unlike every prior
action across all three roles, a successful `merge` is **not** cheap to
notice and undo by hand — reverting a bad merge is possible but visible,
disruptive, and not instantaneous the way toggling a status field or
reopening a closed issue is. This is the real, accepted risk increase
this ADR carries, exactly the one ADR-0026's own Alternatives Considered
section named and the repository owner explicitly chose to accept over
the gated-execution alternative. The `mergeable_state` re-check
immediately before dispatch (Decision 1) is the one mechanism specific
to this ADR that meaningfully narrows the window a bad merge could slip
through, on top of every role's existing kill switch/audit trail.

## Alternatives Considered

### Require a human-applied label before a PR is merge-eligible

The alternative actually presented to and rejected by the repository
owner (see Context): a label like `auto-merge-ok` a human applies first,
narrowing the agent's real discretion to "when," not "whether." Rejected
for this phase in favor of ADR-0026's original full-autonomy framing;
recorded here as the design to revisit if real autonomous merging
reveals problems `mergeable_state` alone doesn't catch.

### AI-judged merge-worthiness (reviewing the actual diff) in addition to `mergeable_state`

Considered and rejected as unnecessary scope growth for this phase:
`mergeable_state` already encodes "every required check passed and there
is no conflict," which is the same bar a human merging by hand normally
applies. Adding AI diff review as a second, independent merge gate is a
reasonable future enhancement, not a Phase 4 requirement.

## Consequences

### Positive

- Completes ADR-0026's third and final authorized autonomous role —
  every phase this ADR originally staged (2 through 4) is now built.
- Zero new migration or config-architecture surface — the Phase 3
  refactor (`_AutonomousRoleRuntimeConfigBase`, `_autonomous_shared.py`)
  pays off a second time.
- The `mergeable_state` double-check closes a real TOCTOU gap that a
  naive "check once, act later" cycle would have left open.

### Negative

- The platform's first genuinely irreversible autonomous action. Every
  prior role's mistakes are cheap to notice and undo by hand; a bad
  merge is not.
- A fourth distinct GitHub credential to provision, rotate, and reason
  about the blast radius of if ever leaked.
- This role's real-world value is deliberately deferred: built and
  tested, but withheld from a real credential per Decision 5 — the
  repository owner does not get real autonomous merging out of this PR
  alone, only the built, tested, ready-to-activate capability.

## Related Decisions

- [ADR-0026: Autonomous Team Agents](ADR-0026-autonomous-team-agents.md) — Decision 1's Principal Developer action-set grant this ADR implements in full; Decision 8's Phase 4 gate (audit trail/kill switch/spend cap proven under real load from Phases 2–3) this ADR satisfies
- [ADR-0028: `scrum-master-agent` Phase 2](ADR-0028-scrum-master-agent-phase-2.md) — the execution model, safety machinery, and "boundary is in code, not the token" credential pattern this ADR reuses unchanged
- [ADR-0030: `product-owner-agent` Phase 3](ADR-0030-product-owner-agent-phase-3.md) — the `_AutonomousRoleRuntimeConfigBase`/`_autonomous_shared.py` refactor this ADR's runtime wiring builds on directly

## References

- `src/ai_platform/agents/scrum_master_agent/tracker.py` — the REST call/error-handling pattern `principal_developer_agent/source_control.py` reuses for PR review/merge calls
- `src/ai_platform/agents/_autonomous_shared.py` — the two pure helpers reused unchanged a third time

## Implementation Status

Accepted; implementation follows in the accepting PR. Per Decision 5,
this role is deployed with a placeholder credential only — no real PAT,
no real merge, until an explicit separate go-ahead.
