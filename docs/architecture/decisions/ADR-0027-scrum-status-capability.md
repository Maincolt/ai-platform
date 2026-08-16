# ADR-0027: `scrum.status` — a Read-Only, Live Scrum-Board Status Capability

- **Status:** Accepted
- **Date:** 2026-08-16
- **Supersedes:** None
- **Superseded by:** None

## Context

[ADR-0026](ADR-0026-autonomous-team-agents.md) authorized an eventual
autonomous multi-agent team but deliberately staged the rollout, and its
Phase 1 is explicitly a read-only advisory capability that fetches real
project-board state and returns one AI Router call's worth of advisory
findings — needing no `SECURITY.md` carve-out, no write credentials, no
tool-calling loop. This ADR is that Phase 1.

Live-verified before designing this: the `Maincolt/ai-platform` repository
currently has **no populated tracker** — zero GitHub Issues, no accessible
classic Projects, and no reachable Projects v2 board. The repository owner
chose **GitHub Projects (v2)** as the target system over plain Issues
(richer status/sprint fields) or classic Projects (deprecated by GitHub),
and confirmed no board exists yet — one will be created after this
capability is built, with its owner/number supplied once it exists.

Structurally, this introduces **no new external side effect and no new
architecture** beyond what `ui.review` ([ADR-0019](ADR-0019-ui-review-capability.md))
already established: the Agent's own deterministic code performs one
read-only fetch, then makes the existing single-shot `AIRouterPort.complete()`
call. The only genuine difference is the fetch target: an authenticated
GitHub GraphQL API call instead of an unauthenticated Playwright page
load, which is why this ADR reaches a different call than ADR-0019
Decision 4 on one specific point (Decision 3 below).

## Decision

### 1. Execution model: fetch-then-single-AI-call, identical shape to `ui.review`

One deterministic, read-only fetch via a new port, then one
`AIRouterPort.complete()` call, same durable pre-call claim (ADR-0016),
same idempotent-replay/deadline handling, same outcome-commit/event-
publish path. No tool-calling, no write access, no new claim model.

### 2. Capability contract shape

`capability_name = "scrum.status"`, `capability_version = "1.0"`,
following [ADR-0015](ADR-0015-generic-capability-result-model.md)'s
generic result model:

- **Input**: the existing generic `payload.input` string field, holding
  a free-text focus or question about the board (e.g. "what's blocking
  the sprint"); the platform-wide `minLength: 1` on `input` means a
  caller with no specific focus submits a short placeholder such as
  `"status"` rather than a true empty string. The board itself is
  fetched from server-side configuration, not supplied by the caller.
- **Result**: `result_data = {"findings": [...]}`, where each finding is
  `{location: string (1–200 chars), summary: string (1–2000 chars),
  severity: "low"|"medium"|"high"}` — `location` names the issue/card the
  observation refers to (e.g. `"issue #42 (In Progress)"`, `"Sprint
  velocity"`), the same free-text-locator role every prior capability's
  locator field plays. Advisory-only, never applied automatically.

### 3. New port: `ProjectBoardPort`, real implementation reads GitHub Projects v2

`ProjectBoardPort` (Protocol, one `async def fetch(self) ->
ProjectBoardSnapshot` method) mirrors `ui_review_agent.capture
.PageCapturePort` exactly — a narrow, read-only seam `agent.py` and its
tests depend on, never a real HTTP client directly. `GitHubProjectsBoardReader`
is the real implementation: an `httpx.AsyncClient` POST to
`https://api.github.com/graphql` with a Bearer PAT, querying the
configured owner's `projectV2(number:)` for item titles, states, URLs,
and status field values. Bounded item count and text length, same
truncation discipline as `PlaywrightPageCapture`. Raises one domain error,
`ProjectBoardFetchFailedError(reason: str)`, on any HTTP error, timeout,
GraphQL error response, or malformed shape — never a partial result.

### 4. Project coordinates are configuration, not a hardcoded constant

`ui.review`'s hardcoded review target (ADR-0019 Decision 4) exists to
close off an SSRF-shaped risk: an unauthenticated fetch of a
caller-influenced arbitrary URL. `scrum.status` has no equivalent risk —
the fetch target is always `https://api.github.com/graphql`, and the
*board* fetched is scoped entirely by which PAT is configured and what
that PAT can see, per GitHub's own permission model. There is nothing an
attacker could redirect this fetch toward beyond what the configured
credential already permits. Accordingly, the project owner and number are
ordinary, non-secret `AgentRuntimeConfig` fields
(`AI_PLATFORM_AGENT_GITHUB_PROJECT_OWNER`/`_NUMBER`), not hardcoded
module constants — a deliberate, narrower divergence from ADR-0019
Decision 4's precedent, justified by the different risk shape, not a
general loosening of it.

### 5. New credential class: a read-only-scoped GitHub PAT

`AI_PLATFORM_AGENT_GITHUB_TOKEN_FILE`, read via the existing
`SecretFileReference` pattern (the same mechanism every AI Router
provider key already uses). The PAT must be scoped to `read:project`
only — no `repo`, no `write:project`, no organization-admin scope. Since
no board exists yet, this credential and the two project-coordinate env
vars start as clearly-fake placeholders at deployment time, upgraded to
real values once the repository owner creates the board — the same
placeholder-then-real-credential path this project's AI Router provider
keys already followed.

### 6. Model reuse: no new model-approval question

Reuses [ADR-0017](ADR-0017-ai-router-follow-up-decisions.md) Decision 3's
approved allowlist unchanged (`claude-haiku-4-5` / `gpt-5-mini`), the same
precedent every prior AI-backed capability has established.

### 7. New deployable: `scrum-status-agent`

Its own Agent deployable — own container (the shared `ai-platform:sprint6`
image), own Kafka principal/ACLs and capability-scoped topic pair, own
Capability Registry binding — following the exact isolation pattern
ADR-0018 Decision 4 established. Tenth Agent deployable.

### 8. Fits ADR-0018 Decision 1's admission policy unchanged

Bounded input/output, one AI Router call, no side effect beyond the read-
only fetch, advisory-only output. No `SECURITY.md` carve-out, no
ADR-0026 tool-calling loop, and no autonomous action-taking are part of
this ADR — Phases 2 onward of ADR-0026 remain separate, future,
deliberately gated work.

## Security

The fetched board content (issue titles, status values, comments if ever
included) is untrusted input to the provider, the same posture every
prior fetch-based capability already carries (ADR-0019's Playwright
capture is the direct precedent) — stored as opaque structured findings,
never parsed as commands. No human-approval gate is required: read-only,
advisory output only, no state mutation beyond the platform's own outcome
bookkeeping. The GitHub PAT is the one new credential class this ADR
introduces; scoping it to `read:project` only (Decision 5) means even a
fully compromised credential grants no write access to anything.

## Alternatives Considered

### GitHub Issues alone, no Projects v2

Considered and rejected by the repository owner in favor of Projects v2's
richer status/sprint-scoped fields (custom status field, sprint
iteration, points) — plain Issues has no first-class sprint/board
concept to report on.

### Classic GitHub Projects

Rejected: deprecated by GitHub in favor of Projects v2, not a reasonable
foundation for new work.

### Hardcode the project owner/number, matching `ui.review` exactly

Considered for consistency with ADR-0019 Decision 4. Rejected per
Decision 4 above: the two designs address different risk shapes (SSRF-
bounded arbitrary fetch vs. a credential-scoped API call), and forcing
identical treatment would only cost operational flexibility (a project
migration or renumbering would require a code change instead of a config
update) without closing any risk that config-driven coordinates leave
open.

## Consequences

### Positive

- Reuses effectively all of `ui.review`'s machinery — the only new
  engineering surface is one new capability contract, one new fetch port
  and its real implementation, one new credential class, and one new
  deployable.
- No new side-effect category, no new tool-calling or write-access
  surface — Phases 2+ of ADR-0026 remain untouched by this ADR.
- Config-driven project coordinates mean the board can be repointed
  (new owner, new project number) without a code change or redeploy of
  application logic.

### Negative

- A tenth Agent deployable to operate (own container, principals, topic
  pair, Registry binding) — more deployables, traded for isolation per
  ADR-0018 Decision 4's established reasoning.
- A new credential class (GitHub PAT) with its own rotation/scoping
  discipline to maintain, independent of the AI Router provider keys.
- Cannot be meaningfully live-verified end to end until the repository
  owner creates a real Projects v2 board and supplies a real PAT —
  `scrum-status-agent` will reach `READY` on deployment (readiness does
  not depend on a live board fetch), but a real submission fails closed
  with `PROJECT_BOARD_FETCH_FAILED` against placeholder credentials until
  then, by design.

## Related Decisions

- [ADR-0007: Agent Execution Model and Lifecycle](ADR-0007-agent-execution-model-and-lifecycle.md) — request/response shape this ADR applies
- [ADR-0008: Capability Registry and Agent Discovery](ADR-0008-capability-registry-and-agent-discovery.md) — `scrum-status-agent`'s Registry binding follows this shape
- [ADR-0014: AI Router and the First AI-Backed Agent](ADR-0014-ai-router-and-first-ai-backed-agent.md) — the single-shot `AIRouterPort` contract this capability reuses unchanged
- [ADR-0015: Generic Capability Result Model](ADR-0015-generic-capability-result-model.md) — `scrum.status`'s findings-list `result_data` shape
- [ADR-0016: Provider Call Claim Reconciliation](ADR-0016-provider-call-claim-reconciliation.md) — durable pre-call claim reused unchanged
- [ADR-0017: AI Router Follow-Up Decisions and Multi-Agent Readiness Routing](ADR-0017-ai-router-follow-up-decisions.md) — model allowlist reused unchanged
- [ADR-0018: Software-Team-Persona Capabilities — Scope and First Candidate](ADR-0018-software-team-persona-capabilities.md) — Decision 1's admission policy this capability still fits unchanged; Decision 4's isolation pattern this ADR follows
- [ADR-0019: `ui.review` — a Playwright-Backed UI Review Capability](ADR-0019-ui-review-capability.md) — the fetch-then-single-AI-call template this ADR mirrors, and Decision 4's hardcoded-target precedent this ADR deliberately diverges from (Decision 4 above)
- [ADR-0026: Autonomous Team Agents](ADR-0026-autonomous-team-agents.md) — this ADR is ADR-0026's Phase 1

## References

- `src/ai_platform/agents/ui_review_agent/` — the template this capability's domain module mirrors file-for-file

## Implementation Status

**Landed in the accepting PR**: the `scrum.status` contract additions
(`execute_task.schema.json`, `task_completed.schema.json`,
`task_failed.schema.json` capability enums; `task_completed.schema.json`'s
findings-list discriminated branch, `{location, summary, severity}`) and
the `scrum_status_agent` domain module
(`src/ai_platform/agents/scrum_status_agent/`: capability identity, the
`ScrumStatusAgent` execution lifecycle, `ProjectBoardPort`/
`GitHubProjectsBoardReader`, findings parsing/validation, domain errors),
with unit, component, and contract-level test coverage mirroring
`ui_review_agent`'s. Also landed here: `runtime/loading.py`'s
`_SUPPORTED_CAPABILITY_NAMES`, `runtime/configuration.py`'s new
`github_token`/`github_project_owner`/`github_project_number` fields, and
`runtime/composition.py`'s executor selection, reusing ADR-0017 Decision
3's exact approved model list unchanged.

**Update (2026-08-16) — deployment wiring landed and live-verified**: PR
#56 added the `scrum-status-agent` Compose service (shared
`ai-platform:sprint6` image), its own Kafka producer/consumer
principals/topic pair/ACLs (`scrum-status-agent-producer`/`-consumer`,
`task-commands.scrum-status.v1` + quarantine companion), and a Capability
Registry binding (revision `local-compose-11`); the new Kafka secrets
were declared in the top-level `secrets:` stanza from the start, and a
`github_token` secret entry was added holding an obviously-fake
placeholder until a real PAT exists.
`test_kafka_acl_matrix.py` gained matching isolation cases (183 cases
total across all ten capabilities). Deployed to the Mac Docker host:
image rebuilt, new SCRAM credentials seeded against the already-
provisioned broker via `kafka-configs.sh --alter`, all twelve
agent/platform/dashboard/test-agent services recreated for the
registry-revision-bump gotcha. `GET /api/v1/agents` reported all ten
capabilities `READY`/`fresh: true` on the first check, confirmed
visually via a Playwright screenshot of the live dashboard showing
"10 / 10 online" with `scrum.status` as its own card and zero frontend
changes needed. The full 183-case ACL matrix, including the new
principals' isolation cases, passed live against the broker.

A real submission against the placeholder credentials correctly failed
closed as designed: `PROJECT_BOARD_FETCH_FAILED` carrying GitHub's own
real `401 Bad credentials` response, proving the whole fetch-then-AI-call
pipeline is wired correctly end to end short of the credential itself.

**Update (2026-08-16) — genuine board-derived live verification
complete**: the repository owner created a real GitHub Projects v2 board
(`Maincolt`, project number 1) and supplied a real `read:project`-scoped
PAT. `AI_PLATFORM_AGENT_GITHUB_PROJECT_OWNER` was updated from its
placeholder and the real PAT was written to `github_token.txt` on the
Mac Docker host; `scrum-status-agent` was recreated (no registry change
needed for a credential/config-only update) and reached `READY`. Two
real submissions (a general status summary and an explicit "list every
item" query) both reached `COMPLETED` with `{"findings": []}` — the real
GitHub GraphQL fetch succeeded (no more `PROJECT_BOARD_FETCH_FAILED`),
and the empty findings list is consistent with a genuinely empty,
newly-created board rather than any error. The credential itself was
shared directly in the working session rather than through a separate
secrets channel; it was written straight to the deployment host's secret
file without being echoed back anywhere, but the repository owner may
want to rotate it later as routine hygiene given how it was transmitted.
