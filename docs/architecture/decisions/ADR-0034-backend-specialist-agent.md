# ADR-0034: `backend-specialist-agent` — A Third Domain Review Role

- **Status:** Accepted
- **Date:** 2026-08-18
- **Supersedes:** [ADR-0026](ADR-0026-autonomous-team-agents.md) Decision 1, narrowly — adds one more role to the authorized set, same as ADR-0033 already did for two.
- **Superseded by:** None

## Context

With `frontend-specialist-agent` and `postgres-specialist-agent`
(ADR-0033) live and running against real pull requests, the repository
owner asked for one more: a backend specialist. This is the gap ADR-0033
itself already flagged as the clearest remaining one — Python/FastAPI
backend code (`src/ai_platform/`) had no domain-scoped autonomous
reviewer, only the general-purpose `principal-developer-agent` (whose
job is "is this safe to merge," not a backend-focused review) and the
on-demand, Workflow-invoked `code.review`/`technical.review`
capabilities.

Same governance requirement as every prior role addition: `SECURITY.md`'s
carve-out text excludes "any new role" from the existing exemptions by
design, so this ADR re-amends it a third time, naming
`backend-specialist-agent` explicitly.

**Zero new code beyond configuration and wiring.** `DomainReviewAgent`
and `_pull_request_review_shared.py` (ADR-0033) were already built
generic over role/domain label/path prefixes — this role is a third
`build_*_process()` composition function passing different literals to
the same shared implementation, not a new domain package. Zero new
migration, same as every role since ADR-0028.

## Decision

### 1. Domain: `src/ai_platform/`, deliberately broad and deliberately overlapping `postgres-specialist-agent`

Unlike `frontend-specialist-agent`/`postgres-specialist-agent`'s
narrowly-scoped path prefixes, `backend-specialist-agent`'s single
prefix (`src/ai_platform/`) covers the whole Python backend tree,
including the `adapters/persistence/`/`ports/persistence/` paths
`postgres-specialist-agent` already reviews. This overlap is
intentional, not an oversight: `PullRequestReviewPort.request_changes`
is additive (multiple independent review comments from different
roles), never conflicting or exclusive, so two domain specialists
commenting on the same persistence-touching PR is a feature (layered
review depth), not a bug. The prompt's `domain_label` ("Python backend
service and API layer") gives this role a different review lens than
`postgres-specialist-agent`'s narrower "Postgres schema and persistence
layer" framing, even where their file-path domains overlap.

### 2. Same action, cadence, caps, and credential pattern as every prior review-only role

`request_changes` only — no merge (`PullRequestReviewPort` still has no
merge method at all; this role is exactly as structurally incapable of
writing anything as `frontend-specialist-agent`/`postgres-specialist-agent`).
Hourly cadence, 10 actions/$1 per day, tracked as independent
`role='backend-specialist'` rows. One more separate `repo`-scoped PAT,
starting as an obviously-fake placeholder until the repository owner
supplies a real one.

## Security

Identical threat model and blast radius to `frontend-specialist-agent`/
`postgres-specialist-agent` (ADR-0033's Security section applies
unchanged) — structurally incapable of merging or writing anything, so
a successful prompt injection here can at most cause an unwanted review
comment.

## Alternatives Considered

### Narrower backend sub-domains (e.g. `src/ai_platform/api/` only, excluding persistence)

Rejected: the path-prefix filter has no exclusion mechanism, only
prefix matching, and there is no real harm in the overlap with
`postgres-specialist-agent` (see Decision 1) — enumerating exclusions
the mechanism doesn't support would add complexity for no real safety
benefit.

## Consequences

### Positive

- Closes the gap ADR-0033 itself identified as the clearest remaining
  one, using code that already existed — the smallest marginal addition
  of any role built so far (no new domain package, no new port).

### Negative

- A sixth autonomous role deployment to operate, with its own
  credential and failure modes.
- Deliberate domain overlap with `postgres-specialist-agent` means a
  single persistence-touching PR can receive two independent review
  comments in the same review cycle — expected, but worth knowing if it
  looks like duplication rather than two distinct lenses.

## Related Decisions

- [ADR-0033: `frontend-specialist-agent` and `postgres-specialist-agent`](ADR-0033-frontend-and-postgres-specialist-agents.md) — the shared `DomainReviewAgent`/`_pull_request_review_shared.py` implementation this role reuses unchanged, and the role this ADR's Context names as the gap it fills

## References

- `src/ai_platform/agents/domain_review_agent/agent.py` — `DomainReviewAgent`, reused unchanged
- `src/ai_platform/agents/_pull_request_review_shared.py` — `PullRequestReviewPort`/`GitHubPullRequestReviewClient`, reused unchanged

## Implementation Status

Accepted; implementation follows in the accepting PR. Deploys with a
placeholder credential only — a real PAT is a separate, later step the
repository owner supplies explicitly, same as every prior role.

**Update (2026-08-18):** merged (PR #66). The repository owner supplied
a real, `repo`-scoped PAT before first deployment, so this role skipped
the placeholder-then-real two-step every prior role followed — deployed
directly with the real credential. A live cycle showed a genuine
`200 OK` pull-request fetch against `Maincolt/ai-platform`, correctly
reporting no open pull requests touch `src/ai_platform/` right now. The
service reaches `ready: true`. Confirmed visually via a Playwright
screenshot: the dashboard's "Autonomous Agents" tab now shows all six
roles, Backend Specialist included, all at zero usage today.
`backend-specialist-agent` is now live with real review capability.
