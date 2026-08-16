# ADR-0026: Autonomous Team Agents — Scrum Master, Product Owner, and Principal Developer Acting Without Human Approval

- **Status:** Accepted
- **Date:** 2026-08-16
- **Supersedes:** [ADR-0014](ADR-0014-ai-router-and-first-ai-backed-agent.md)
  Section 9's exclusion of "any Agent capability that grants the model tool
  use, code execution, or an ability to trigger a further platform action
  from its output," and [ADR-0018](ADR-0018-software-team-persona-capabilities.md)
  Decision 1's "never autonomously applied" clause — narrowly, only for the
  three autonomous team-agent roles this ADR defines and only for the
  action sets each is explicitly granted (Decision 1/Decision 8). All
  other content in ADR-0014 and ADR-0018 remains in force, including
  ADR-0018 Decision 1's admission policy for every other capability. Also
  narrowly amends `SECURITY.md`'s "Human Approval for High-Impact Actions"
  section with the carve-out this ADR requires (Decision 6).
- **Superseded by:** None

## Context

Every capability built so far — `text.summarize` through `security.review`
— follows the same bounded-advisory shape ADR-0018 Decision 1 established:
one input, one AI Router call, one structured advisory output, never
autonomously applied. That shape deliberately excludes tool use
(ADR-0014 Section 9) and requires a human to act on every finding
(ADR-0018 Decision 1), "to preserve the platform's existing
human-in-the-loop posture." `SECURITY.md`'s "Human Approval for High-Impact
Actions" section independently codifies the same posture as a repo-wide
policy: no destructive, irreversible, or materially high-impact action may
be taken by an AI Agent without explicit human approval, repo-wide, not
just for capabilities built under ADR-0018.

The repository owner has now asked for something structurally different:
three roles — Scrum Master, Product Owner, and Principal Developer —
operating a real scrum board **autonomously**, including taking real,
hard-to-reverse actions (creating/closing tickets, reassigning work,
merging pull requests) with **no per-action human approval at all**. This
was confirmed explicitly, with the tradeoffs surfaced first: full autonomy
was chosen over a gated-execution alternative that would have kept
`SECURITY.md`'s approval requirement for destructive actions specifically;
a hard spend/rate cap was requested given this project's previously
documented AI-provider-cost caution (ADR-0018 Decision 5); and amending
`SECURITY.md` explicitly was chosen over leaving it unmodified and quietly
inconsistent with what these three roles actually do.

Product Owner and Scrum Master were explicitly assessed and rejected by
ADR-0018 Decision 2 as **not fitting the bounded-advisory model** at all —
"continuous facilitation/prioritization roles, not one-shot request/
response work." That assessment is not wrong under the bounded-advisory
model; it is exactly why this ADR does not try to force these roles into
that model. It defines a different execution model for them instead.

## Decision

### 1. Scope: three new autonomous roles, each its own Agent deployable

- **`scrum-master-agent`** (`scrum.autonomous`): create/close/relabel/
  reassign/comment on tracker issues, move sprint-board cards, post status
  updates. No merge or deploy rights.
- **`product-owner-agent`** (`backlog.autonomous`): reprioritize the
  backlog, create/edit/close tickets, adjust sprint scope. No merge or
  deploy rights.
- **`principal-developer-agent`** (`code.autonomous`): review pull
  requests, request changes, **merge**. No deploy rights.

No role in this ADR's initial granted-action set includes deployment or
infrastructure changes. This ADR's policy change (Decision 6) authorizes
full autonomy in principle for these roles, including destructive actions
— the initial action sets above are deliberately conservative anyway, per
the phased rollout in Decision 8: no role's action set should include its
highest-blast-radius actions until the audit trail, kill switch, and spend
cap have been proven under real autonomous load with lower-stakes actions
first. Deployment-capable autonomy is explicitly deferred to a future ADR
regardless (Decision 8, Phase 5).

### 2. Execution model: a bounded tool-calling loop, not open-ended model access

A new port, `AutonomousToolLoopPort`, wraps the existing `AIRouterPort`.
The model may request one action from a **fixed, per-role enumerated
set**; Agent code validates the request against that role's allowlist,
executes it through the relevant write port (Decision 3), and feeds the
structured result back to the model, repeating until the model signals
completion or a per-cycle step limit is reached. The model never receives
raw tool/API access — every action passes through Agent-owned dispatch
code first. This keeps the enumerable action set a hard, code-enforced
boundary rather than a prompt convention, directly implementing
`SECURITY.md`'s existing "restrict tools ... to the minimum required
scope" guidance for exactly this new, higher-stakes case.

### 3. New write ports (new credential classes)

- **`ProjectTrackerPort`** (write): issue/card create, close, relabel,
  reassign, comment, move.
- **`SourceControlPort`** (write): PR review, approve, merge. No push or
  force-push.
- A `DeploymentPort` is deliberately not introduced by this ADR (Decision
  1, Decision 8 Phase 5).

Each port's credential is scoped to only the role(s) that need it — the
same least-privilege isolation this platform already applies to Kafka
principals per capability (ADR-0014 Section 6): `scrum-master-agent` and
`product-owner-agent` never hold a `SourceControlPort` credential;
`principal-developer-agent` never holds deploy rights (none exist yet) or
directly performs tracker board management outside its own PR-review
scope.

### 4. Persistent team/board state

A new durable aggregate, `orchestrator.team_board` — current sprint,
backlog snapshot cache, WIP limits, per-role last-run timestamp. This is
**not** a Workflow: a Workflow is one bounded request/response
(ADR-0007); `team_board` is continuously-updated state a scheduled or
event-triggered process reads and writes across many runs.

### 5. Trigger model: scheduled and event-driven, not synchronous submission

A new invocation path alongside the Workflow API's synchronous submit-
and-poll model: each autonomous role runs on a cadence (e.g. every N
minutes) or reacts to an event published onto the existing Kafka Event
Bus (`IssueOpened`, `PRReadyForReview`, `SprintBoundaryReached`). The
scheduler itself is an internal loop inside each Agent process, matching
this platform's existing preference (ADR-0007) for owning its own
execution model rather than depending on an external workflow engine.

### 6. `SECURITY.md` carve-out (explicit and narrow)

`SECURITY.md`'s "Human Approval for High-Impact Actions" section is
amended with a narrow, named exception: an autonomous team-agent role
operating under this ADR's bounded, enumerated, audited, least-privilege
action set is exempt from the per-action approval requirement **only for
the actions this ADR explicitly grants that role** (Decision 1). The
exemption is conditioned, without exception, on every mechanism in
Decision 7 being in place: a fixed and enumerable action set the model
cannot expand, a durable audit record of every action, a platform-wide
kill switch checked before every action, and a hard spend/rate cap. Any
action outside a role's granted set, any future role, and every other AI
Agent or automation in this platform remain fully subject to the
unmodified policy.

### 7. Guardrails that remain without a per-action approval gate

- **Per-role least privilege** (Decision 3) — bounds what a bad decision
  from any one role can reach, structurally, not by convention.
- **Durable, complete audit trail** of every dispatched action — extends
  the existing `AuditRecord`/`orchestrator.audit_records` pattern
  (ADR-0006, ADR-0009) to record actor role, action, target, inputs,
  result, and timestamp for every tool-loop dispatch. This is after-the-
  fact, not preventive: it makes every action reconstructable, not
  stoppable in advance.
- **A platform-wide kill switch** — one flag, checked before every
  dispatched action in every role's tool loop (not just at role start),
  that halts all autonomous action-taking immediately.
- **A hard spend/rate cap** (repository owner's explicit requirement) — a
  durable counter checked before every provider call and before every
  dispatched action; on breach, the affected role automatically drops to
  a read-only "report only" mode (the same shape as a bounded-advisory
  capability) rather than the whole system failing.

### 8. Phasing

This ADR authorizes the full end-state architecture and policy; rollout
is staged so the safety machinery (Decision 7) is proven before the
highest-stakes credentials exist at all.

- **Phase 1** (no policy change needed — fits the existing bounded-
  advisory model unchanged): read-only advisory capabilities, e.g.
  `scrum.status`/`backlog.triage`, that fetch real tracker/board state and
  return one AI Router call's worth of advisory findings — the same
  deterministic-fetch-then-single-call shape `ui.review` (ADR-0019)
  already established.
- **Phase 2**: `scrum-master-agent` gains `ProjectTrackerPort` write
  access only — the lowest blast radius of the three roles.
- **Phase 3**: `product-owner-agent` gains backlog/sprint-scope write
  access.
- **Phase 4**: `principal-developer-agent` gains `SourceControlPort`
  merge rights — only after the audit trail, kill switch, and spend cap
  have been exercised under real autonomous load from Phases 2–3.
- **Phase 5** (future, its own ADR): a deployment-capable role, if ever
  needed. Deliberately excluded from this ADR's initial granted-action
  scope even though Decision 6 permits it in principle — deployment is
  categorically higher blast radius than anything tracker- or git-side
  and warrants its own dedicated safety review once the rest of this
  ADR's machinery is proven in production.

## Security

The reviewed/fetched tracker and PR content these roles act on is
untrusted input, the same threat class `ui.review`'s Playwright capture
already established (ADR-0019) — but the blast radius of a successful
prompt injection is categorically different here: instead of a wrong
advisory finding, a successful injection could trigger a real action (an
unwanted merge, an incorrectly closed ticket). The primary mitigation is
Decision 2's enumerable, code-dispatched action set — an injected
instruction can at most cause the model to *request* an allowed action, not
expand what's allowed. The audit trail (Decision 7) provides detection
after the fact; the kill switch (Decision 7) provides containment once
detected. Neither prevents a single successful injection from taking one
unwanted-but-in-scope action before detection — this is the real, accepted
risk this ADR's policy change carries, and is not eliminated by any
mechanism here. `SourceControlPort` deliberately excludes push/force-push
to limit what a compromised merge action could do; `principal-developer-
agent` can merge a bad PR but cannot rewrite history or push directly.

No new data-classification concern beyond `SECURITY.md`'s existing
"External AI Providers" section: tracker/PR content is treated as the
same class of input every prior capability's caller-supplied text
already is.

## Alternatives Considered

### Keep the human-approval gate for destructive actions ("gated execution")

The alternative actually presented to and rejected by the repository
owner: full autonomy for planning/board management, but `SourceControlPort`
merges (and any future deploy action) still require one human approval
click. Rejected for this ADR per the repository owner's explicit choice;
recorded here as the fallback design to revisit if Phase 4 reveals real
problems with unattended merging.

### Direct/raw tool access for the model instead of an enumerable action set

Rejected as unnecessarily larger attack surface for no real capability
gain — an enumerated allowlist can express everything a scrum-board
interaction and PR merge actually need, and keeps `SECURITY.md`'s "restrict
tools ... to the minimum required scope" guidance enforceable in code
rather than only in the prompt.

### A third-party workflow/scheduling engine for the trigger model

Rejected for now, matching this platform's existing preference (ADR-0007)
for owning its own execution model rather than taking on an external
orchestration dependency. Revisit if the internal scheduler proves
insufficient at real scale.

## Consequences

### Positive

- Delivers the autonomous multi-agent team the repository owner asked
  for, including real actions, not a thinner advisory-only version of the
  same idea.
- The `SECURITY.md` carve-out is explicit and narrow — the general
  human-approval policy stays fully intact for every other Agent and
  every action these three roles aren't specifically granted.
- Audit trail, kill switch, and spend cap give real — if after-the-fact
  rather than preventive — safety even with zero per-action approval.
- Phased rollout means the highest-blast-radius credentials (merge; any
  future deploy) don't exist until the safety machinery has already been
  proven under real autonomous load.

### Negative

- Reverses this platform's human-in-the-loop posture for the first time
  — a real, deliberately accepted increase in blast radius per action
  these three roles take, not a hypothetical one.
- New credential classes (`ProjectTrackerPort` write, `SourceControlPort`
  merge) are a new class of platform risk beyond anything built under
  ADR-0018.
- A successful prompt injection against fetched tracker/PR content can
  now cause one real, unwanted-but-in-scope action before the audit trail
  and kill switch catch it — mitigated, not eliminated (see Security).
- Meaningful new engineering surface: new persistent state
  (`team_board`), a new trigger model, new write ports, new tool-loop
  execution machinery, new safety infrastructure (audit extension, kill
  switch, spend cap) — the largest single ADR's scope since ADR-0007/
  ADR-0014.
- Three more Agent deployables to operate, each with its own credentials
  and failure modes, on top of the nine capabilities already running.

## Related Decisions

- [ADR-0006: Persistence, State, and Recovery](ADR-0006-persistence-state-and-recovery.md) — the `AuditRecord` pattern this ADR extends for autonomous-action audit trails
- [ADR-0007: Agent Execution Model and Lifecycle](ADR-0007-agent-execution-model-and-lifecycle.md) — the request/response execution model `team_board`'s scheduled/event-driven trigger deliberately departs from, and the "own our execution model" preference the scheduler decision follows
- [ADR-0009: Observability, Telemetry, and Audit Correlation](ADR-0009-observability-telemetry-and-audit-correlation.md) — audit correlation this ADR's action-level audit trail extends
- [ADR-0014: AI Router and the First AI-Backed Agent](ADR-0014-ai-router-and-first-ai-backed-agent.md) — Section 9's tool-use exclusion this ADR narrowly supersedes
- [ADR-0018: Software-Team-Persona Capabilities — Scope and First Candidate](ADR-0018-software-team-persona-capabilities.md) — Decision 1's admission policy and "never autonomously applied" clause this ADR narrowly supersedes for these three roles; Decision 2's Product Owner/Scrum Master "does not fit" assessment this ADR agrees with under the bounded-advisory model and addresses with a different execution model instead
- [ADR-0019: `ui.review` — a Playwright-Backed UI Review Capability](ADR-0019-ui-review-capability.md) — the deterministic-fetch-then-single-AI-call shape Phase 1's read-only advisory capabilities reuse unchanged

## References

- `SECURITY.md` — "Human Approval for High-Impact Actions" (narrowly amended by this ADR, Decision 6) and "Prompt Injection and Untrusted Input" (the guidance Decision 2's enumerable action set implements for this case)

## Implementation Status

Accepted — no code yet. The `SECURITY.md` carve-out (Decision 6) is now in
force. Phase 1 (read-only advisory capabilities) requires no policy change
and can proceed under the existing bounded-advisory model at any time.
Phases 2 onward (autonomous write access) are authorized by this ADR and
follow as separate, future implementation PRs per this repository's
established pattern of landing domain/contract work and deployment wiring
in their own reviewable commits.
