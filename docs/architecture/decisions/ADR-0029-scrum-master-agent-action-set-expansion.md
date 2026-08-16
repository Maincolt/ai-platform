# ADR-0029: `scrum-master-agent` — Rounding Out the Action Set (close/relabel/reassign)

- **Status:** Accepted
- **Date:** 2026-08-16
- **Supersedes:** None
- **Superseded by:** None

## Context

[ADR-0028](ADR-0028-scrum-master-agent-phase-2.md) Decision 1 deliberately
shipped `scrum-master-agent` with three of ADR-0026's six target tracker
actions — `set_status`, `add_comment`, `create_draft_item` — the three
that needed no specific-repo target and were lowest-complexity to get
right first, with `close`/`relabel`/`reassign` explicitly deferred "to a
fast-follow-up once these three are proven safe in production." That MVP
has since been deployed to the Mac Docker host, live-verified (real board
fetch, real Anthropic completion), and had its one real bug (an
already-elapsed AI Router deadline) found and fixed under real conditions.
This ADR is that fast-follow-up: it rounds out `scrum-master-agent`'s
action set to the full six ADR-0026 Decision 1 named for this role
("create/close/relabel/reassign/comment on tracker issues, move
sprint-board cards").

No new safety machinery, credential, or migration is needed. The existing
`project`+`repo`-scoped PAT already covers the three new REST calls below;
`agent.autonomous_kill_switch`/`agent.autonomous_role_budget`/
`agent.autonomous_actions` (migration 0009) already apply unchanged to
every action this role takes, new or old.

## Decision

### 1. Three new actions, same dispatch discipline as the existing three

- **`close_issue`** — close an existing issue or pull request:
  `PATCH /repos/{owner}/{repo}/issues/{number}` body `{"state": "closed"}`.
- **`relabel`** — replace an issue's label set:
  `PUT /repos/{owner}/{repo}/issues/{number}/labels` body
  `{"labels": [...]}`. A full replace, not an add/remove delta — keeps the
  board's actual label state exactly what the model most recently decided,
  with no drift from an unobserved prior label set.
- **`reassign`** — replace an issue's assignee set:
  `PATCH /repos/{owner}/{repo}/issues/{number}` body
  `{"assignees": [...]}`. Same full-replace reasoning as `relabel`.

All three raise `TrackerActionFailedError` on any failure and reject
draft-item URLs (empty string) the same way `add_comment` already does —
there is no issue to close/relabel/reassign until a draft item becomes a
real issue.

### 2. New bounded string-list field type in the proposal parser

`relabel`/`reassign` are the first actions whose payload includes a list
field (labels, assignees) rather than only scalar strings. The strict
discriminated-union parser (`_parse_proposed_actions`) is extended with a
bounded string-list validator — fixed maximum item count and per-item
length, reject-the-whole-batch on any violation — same "no partial
acceptance" discipline every other field already uses.

### 3. `close`/`relabel`/`reassign` remain scoped exactly like the original three

No change to Decision 2/3/4/5/6 of ADR-0028: still no push/force-push
capability anywhere in `tracker.py`, still single-shot propose-then-
dispatch (not multi-turn), still the same kill switch/budget/audit trail,
still the same credential.

## Security

No new risk class introduced. A wrongly closed issue, a wrong label set,
or a wrong assignee are all in the same "cheap to notice and undo by hand"
category ADR-0028's Security section already established for this role's
action set — closing an issue is reversible (GitHub issues can be
reopened), unlike a merge or a deploy.

## Alternatives Considered

### Add/remove semantics for `relabel`/`reassign` instead of full replace

Rejected: add/remove requires the model to reason about the board's
current label/assignee state correctly to compute a correct delta: a
full replace is simpler to reason about, simpler to validate, and
cannot drift from a stale view of "what labels are already there."

## Consequences

### Positive

- Completes ADR-0026 Decision 1's full action-set grant for this role —
  no further scope decisions needed for `scrum-master-agent` itself.
- Zero new engineering surface beyond the three dispatch methods and the
  parser's new field type — no new credential, no new migration, no new
  safety mechanism.

### Negative

- A slightly larger blast radius per role even though each individual
  action remains low-consequence — more distinct ways a single successful
  prompt injection could manifest (ADR-0028's Security section's accepted
  risk, now with three more concrete shapes).

## Related Decisions

- [ADR-0026: Autonomous Team Agents](ADR-0026-autonomous-team-agents.md) — Decision 1's full six-action grant for this role, now complete
- [ADR-0028: `scrum-master-agent` Phase 2](ADR-0028-scrum-master-agent-phase-2.md) — the MVP this ADR completes; Decision 1's explicit deferral of these three actions

## References

- `src/ai_platform/agents/scrum_master_agent/tracker.py` — `add_comment`'s existing REST-call/error-handling/draft-rejection pattern, reused unchanged for the three new methods

## Implementation Status

Accepted; implementation follows in the accepting PR.
