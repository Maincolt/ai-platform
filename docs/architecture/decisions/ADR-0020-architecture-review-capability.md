# ADR-0020: `architecture.review` — a Solution-Architect Review Capability

- **Status:** Accepted
- **Date:** 2026-08-14
- **Supersedes:** None
- **Superseded by:** None

## Context

ADR-0018 Decision 2 already assessed the twelve software-team personas for
fit against this platform's bounded-advisory execution model and found six
that fit now, including **Solution Architect**: "read this input, return
structured analysis" — the same shape as `text.summarize`, differing only
in prompt and output structure. `code.review` (ADR-0018) and `ui.review`
(ADR-0019) are the first two capabilities built from that admission
policy; `architecture.review` is the third.

Unlike `ui.review`, this capability introduces **no new external side
effect and no new architecture**: the input is caller-supplied text (a
proposed architectural change, design doc, or ADR draft — the same
"caller already has the content" shape `code.review`'s diff input has),
and the only external call is the existing single AI Router `complete()`
call. There is nothing here for ADR-0018 Decision 1's admission policy to
stretch around, unlike `ui.review`'s Playwright fetch — this is the
simplest possible case of the pattern, structurally identical to
`code.review` end to end.

## Decision

### 1. Execution model: identical to `code.review`

One AI Router call, same durable pre-call claim (ADR-0016), same
idempotent-replay/deadline handling, same outcome-commit/event-publish
path. No new idempotency mechanism, no new claim model.

### 2. Capability contract shape

`capability_name = "architecture.review"`, `capability_version = "1.0"`,
following [ADR-0015](ADR-0015-generic-capability-result-model.md)'s
generic result model:

- **Input**: the existing generic `payload.input` string field, holding
  the proposed architectural change, design doc excerpt, or ADR draft
  text to review.
- **Result**: `result_data = {"findings": [...]}`, where each finding is
  `{section: string (1–200 chars), summary: string (1–2000 chars),
  severity: "low"|"medium"|"high"}` — `section` identifies which part of
  the reviewed document the finding refers to (e.g. "Decision 2",
  "Consequences", "Security"), the same free-text-locator role
  `ui.review`'s `area` plays. Advisory-only, never applied
  automatically — unchanged from `code.review`/`ui.review`.

### 3. Model reuse: no new model-approval question

Reuses [ADR-0017](ADR-0017-ai-router-follow-up-decisions.md) Decision 3's
approved allowlist unchanged (`claude-haiku-4-5` / `gpt-5-mini`), the same
precedent ADR-0018 Decision 5 and ADR-0019 Decision 3 already established.
Real Anthropic/OpenAI credentials are already configured in this
environment (see ADR-0018/ADR-0019's Implementation Status updates) —
`architecture-review-agent` uses the same real credentials, no new
provider-cost decision required.

### 4. New deployable: `architecture-review-agent`

Its own Agent deployable — own container (the shared `ai-platform:sprint6`
image; no new runtime dependency, unlike `ui-review-agent`'s dedicated
Chromium image), own Kafka principal/ACLs and capability-scoped topic
pair, own Capability Registry binding — following the exact isolation
pattern ADR-0018 Decision 4 established.

## Security

Structurally identical to `code.review`'s security posture (ADR-0014
Section 4, inherited unchanged): the reviewed text is untrusted input to
the provider, the completion is untrusted output to the platform (stored
as opaque structured findings, never parsed as commands); no human-
approval gate is required (advisory output only, no state mutation
beyond the platform's own outcome bookkeeping); no new credential class.
No SSRF or external-fetch consideration applies here — unlike
`ui.review`, this capability makes no outbound call beyond the AI Router
itself.

## Alternatives Considered

### A broader "review any document type" capability

Rejected as unnecessarily generic for a first version — `code.review` and
`ui.review` both scoped to one concrete document/content type first
(a diff, a captured page) rather than a general-purpose reviewer; a
generalized review capability, if ever wanted, is a future ADR's decision
once there's a real second and third use case to generalize from, per
ADR-0018 Decision 4's own reasoning for not prematurely consolidating
Agent deployables.

## Consequences

### Positive

- Reuses effectively all of `code.review`'s machinery — the only new
  engineering surface is one new capability contract, one new domain
  module (structurally a near-verbatim copy), and one new deployable.
- No new side-effect category, no new security surface, no new
  architecture — the simplest of the three ADR-0018-derived capabilities
  to build and reason about.

### Negative

- A fifth Agent deployable to operate (own container, principals, topic
  pair, Registry binding) — more deployables, traded for isolation per
  ADR-0018 Decision 4's established reasoning.
- Five of the twelve personas assessed as fitting the model in ADR-0018
  Decision 2 are now built (Principal Developer/QA-flavored via
  `code.review`, UI/UX Designer-flavored via `ui.review`, Solution
  Architect via this ADR); Technical Architect and Data Analyst remain
  unbuilt, same "future ADR, not an easy default" posture as the six
  personas ADR-0018 rejected outright.

## Implementation Status

**Landed in the accepting PR**: the `architecture.review` contract
additions (`execute_task.schema.json`, `task_completed.schema.json`,
`task_failed.schema.json` capability enums; `task_completed.schema.json`'s
findings-list discriminated branch, `{section, summary, severity}`) and
the `architecture_review_agent` domain module
(`src/ai_platform/agents/architecture_review_agent/`: capability identity,
the `ArchitectureReviewAgent` execution lifecycle, findings parsing/
validation — including markdown-fence tolerance from day one, learned
live from `code.review`/`ui.review`'s PR #40 — domain errors), with unit,
component, and contract-level test coverage mirroring `review_agent`'s.
Also landed here, following `ui.review`'s precedent rather than
`code.review`'s original one-PR-behind approach: `runtime/loading.py`'s
`_SUPPORTED_CAPABILITY_NAMES` and `runtime/composition.py`'s executor
selection, reusing ADR-0017 Decision 3's exact approved model list
unchanged.

Deployment wiring (Compose service, Kafka principals/topics/ACLs,
Registry binding) and live verification against the real Mac Docker host
follow as a separate commit/PR, per this repository's established
pattern.

**Update (2026-08-15) — deployment wiring landed and live-verified**: PR #42
added the `architecture-review-agent` Compose service (shared
`ai-platform:sprint6` image), its own Kafka producer/consumer
principals/topic pair/ACLs (`architecture-review-agent-producer`/
`-consumer`, `task-commands.architecture-review.v1` + quarantine
companion), and a Capability Registry binding; `test_kafka_acl_matrix.py`
gained matching isolation cases. Deployed to the Mac Docker host following
`ui.review`'s exact playbook: image rebuilt, new SCRAM credentials seeded
against the already-provisioned broker via `kafka-configs.sh --alter`
(the `kafka-storage.sh format --add-scram` gap documented in
`docs/operations/README.md` Section 4), `platform`/`test-agent`/`dashboard`
recreated to pick up the new netns after `platform` itself was recreated
by the Compose diff. `GET /api/v1/agents` reported `architecture.review` as
`READY`/`fresh: true` immediately. A real submission (a deliberately
flawed "cache every AI Router completion indefinitely" mini-ADR) reached
`COMPLETED` with seven genuine, contextually specific findings from the
real Anthropic provider (indefinite-cache staleness, no invalidation
strategy, PII-in-cache exposure, hash-collision risk, and more) — not a
placeholder/fixture response. The full 89-case ACL matrix, including the
new principals' isolation cases, passed live against the broker.

## Related Decisions

- [ADR-0007: Agent Execution Model and Lifecycle](ADR-0007-agent-execution-model-and-lifecycle.md) — request/response shape this ADR applies
- [ADR-0008: Capability Registry and Agent Discovery](ADR-0008-capability-registry-and-agent-discovery.md) — `architecture-review-agent`'s Registry binding follows this shape
- [ADR-0014: AI Router and the First AI-Backed Agent](ADR-0014-ai-router-and-first-ai-backed-agent.md) — the single-shot `AIRouterPort` contract this capability reuses unchanged
- [ADR-0015: Generic Capability Result Model](ADR-0015-generic-capability-result-model.md) — `architecture.review`'s findings-list `result_data` shape
- [ADR-0016: Provider Call Claim Reconciliation](ADR-0016-provider-call-claim-reconciliation.md) — durable pre-call claim reused unchanged
- [ADR-0017: AI Router Follow-Up Decisions and Multi-Agent Readiness Routing](ADR-0017-ai-router-follow-up-decisions.md) — model allowlist reused unchanged
- [ADR-0018: Software-Team-Persona Capabilities — Scope and First Candidate](ADR-0018-software-team-persona-capabilities.md) — Decision 1's admission policy and Decision 2's Solution Architect fit assessment this ADR activates; Decision 4's isolation pattern this ADR follows
- [ADR-0019: `ui.review` — a Playwright-Backed UI Review Capability](ADR-0019-ui-review-capability.md) — the second capability built from the same admission policy, whose findings-shape/deployment pattern this ADR mirrors

## References

- `.claude/agents/sofia-alvarez.md` — the Solution Architect persona this capability's prompt tone draws from, copied at build time per ADR-0018 Decision 4's precedent (no runtime coupling to Claude Code's subagent mechanism)
- `src/ai_platform/agents/review_agent/` — the template this capability's domain module mirrors file-for-file
