# ADR-0022: `technical.review` — a Technical-Architect Review Capability

- **Status:** Accepted
- **Date:** 2026-08-15
- **Supersedes:** None
- **Superseded by:** None

## Context

ADR-0018 Decision 2 assessed six personas as fitting this platform's
bounded-advisory execution model: Solution Architect, Technical
Architect, Principal Developer, QA, UI/UX Designer, and Data Analyst.
`code.review` covers the Principal Developer/QA pairing (ADR-0018),
`ui.review` covers UI/UX Designer (ADR-0019), `architecture.review`
covers Solution Architect (ADR-0020), and `data.analysis` covers Data
Analyst (ADR-0021) — leaving **Technical Architect** as the last of the
six still unbuilt.

Like the three capabilities immediately before it, this introduces **no
new external side effect and no new architecture**: the input is
caller-supplied text (a proposed data model/schema, API/contract
definition, service-boundary design, or deployment-topology sketch — the
same "caller already has the content" shape every prior capability's
input has), and the only external call is the existing single AI Router
`complete()` call. Structurally identical to `architecture.review` end to
end, differing only in the findings' locator key and the review prompt's
persona/framing — where `architecture.review` (Solution Architect) asks
"should we build this, and does it fit the existing architecture,"
`technical.review` (Technical Architect) asks the narrower, more concrete
follow-on question: "given an approved direction, is *this* concrete
design — schema, contract shape, service boundaries, deployment
topology — sound and buildable as specified."

## Decision

### 1. Execution model: identical to `data.analysis`/`architecture.review`

One AI Router call, same durable pre-call claim (ADR-0016), same
idempotent-replay/deadline handling, same outcome-commit/event-publish
path. No new idempotency mechanism, no new claim model.

### 2. Capability contract shape

`capability_name = "technical.review"`, `capability_version = "1.0"`,
following [ADR-0015](ADR-0015-generic-capability-result-model.md)'s
generic result model:

- **Input**: the existing generic `payload.input` string field, holding
  the proposed data model/schema, API/contract definition, service-
  boundary design, or deployment-topology text to review.
- **Result**: `result_data = {"findings": [...]}`, where each finding is
  `{component: string (1–200 chars), summary: string (1–2000 chars),
  severity: "low"|"medium"|"high"}` — `component` identifies which
  module, schema, endpoint, or service boundary the finding refers to
  (e.g. "users table", "POST /api/v1/workflows", "Kafka topic
  partitioning"), the same free-text-locator role `architecture.review`'s
  `section` and `data.analysis`'s `metric` play. Advisory-only, never
  applied automatically — unchanged from every prior AI-backed
  capability.

### 3. Model reuse: no new model-approval question

Reuses [ADR-0017](ADR-0017-ai-router-follow-up-decisions.md) Decision 3's
approved allowlist unchanged (`claude-haiku-4-5` / `gpt-5-mini`), the same
precedent ADR-0018 Decision 5, ADR-0019 Decision 3, ADR-0020 Decision 3,
and ADR-0021 Decision 3 already established. Real Anthropic/OpenAI
credentials are already configured in this environment —
`technical-review-agent` uses the same real credentials, no new
provider-cost decision required.

### 4. New deployable: `technical-review-agent`

Its own Agent deployable — own container (the shared `ai-platform:sprint6`
image; no new runtime dependency), own Kafka principal/ACLs and
capability-scoped topic pair, own Capability Registry binding —
following the exact isolation pattern ADR-0018 Decision 4 established and
every capability since has followed. This is the sixth such deployable
and closes out all six personas ADR-0018 Decision 2 found fitting.

## Security

Structurally identical to `data.analysis`/`architecture.review`'s
security posture (inherited unchanged): the reviewed text is untrusted
input to the provider, the completion is untrusted output to the
platform (stored as opaque structured findings, never parsed as
commands); no human-approval gate is required (advisory output only, no
state mutation beyond the platform's own outcome bookkeeping); no new
credential class; no SSRF or external-fetch consideration (no outbound
call beyond the AI Router itself).

## Alternatives Considered

### A capability that reads the actual repository/codebase

Rejected as a materially larger architectural surface: granting an Agent
capability read access to a real filesystem or source-control system
(rather than caller-supplied text) would need its own credential class,
its own access-authorization question, and likely change the risk
posture enough to warrant the same approval-gate design deferred for the
Azure infrastructure agent proposal. This ADR deliberately stays inside
the existing "caller-supplied text in, advisory findings out" shape,
matching `data.analysis`'s equivalent alternative (a real-data-store-
connected variant); a repository-connected variant, if ever wanted, is a
future ADR's decision once there's a concrete need and a real
authorization design to go with it.

## Consequences

### Positive

- Reuses effectively all of `architecture.review`'s machinery — the only
  new engineering surface is one new capability contract, one new domain
  module (structurally a near-verbatim copy), and one new deployable.
- No new side-effect category, no new security surface, no new
  architecture.
- Closes out all six personas ADR-0018 Decision 2 found fitting the
  bounded-advisory model — `code.review`, `ui.review`,
  `architecture.review`, `data.analysis`, and now `technical.review`
  cover Principal Developer/QA, UI/UX Designer, Solution Architect, Data
  Analyst, and Technical Architect respectively.

### Negative

- A seventh Agent deployable to operate (own container, principals, topic
  pair, Registry binding) — more deployables, traded for isolation per
  ADR-0018 Decision 4's established reasoning.
- With all six ADR-0018 Decision 2 personas now built, any further
  software-team-persona capability needs a fresh fit assessment (per
  ADR-0018 Decision 2's own "does not fit" list) rather than reuse of an
  existing pre-approved slot.

## Implementation Status

**Landed in the accepting PR**: the `technical.review` contract additions
(`execute_task.schema.json`, `task_completed.schema.json`,
`task_failed.schema.json` capability enums; `task_completed.schema.json`'s
findings-list discriminated branch, `{component, summary, severity}`) and
the `technical_review_agent` domain module
(`src/ai_platform/agents/technical_review_agent/`: capability identity,
the `TechnicalReviewAgent` execution lifecycle, findings parsing/
validation — including markdown-fence tolerance from day one — domain
errors), with unit, component, and contract-level test coverage
mirroring `data_analysis_agent`'s. Also landed here: `runtime/loading.py`'s
`_SUPPORTED_CAPABILITY_NAMES` and `runtime/composition.py`'s executor
selection, reusing ADR-0017 Decision 3's exact approved model list
unchanged.

Deployment wiring (Compose service, Kafka principals/topics/ACLs,
Registry binding) and live verification against the real Mac Docker host
follow as a separate commit/PR, per this repository's established
pattern.

## Related Decisions

- [ADR-0007: Agent Execution Model and Lifecycle](ADR-0007-agent-execution-model-and-lifecycle.md) — request/response shape this ADR applies
- [ADR-0008: Capability Registry and Agent Discovery](ADR-0008-capability-registry-and-agent-discovery.md) — `technical-review-agent`'s Registry binding follows this shape
- [ADR-0014: AI Router and the First AI-Backed Agent](ADR-0014-ai-router-and-first-ai-backed-agent.md) — the single-shot `AIRouterPort` contract this capability reuses unchanged
- [ADR-0015: Generic Capability Result Model](ADR-0015-generic-capability-result-model.md) — `technical.review`'s findings-list `result_data` shape
- [ADR-0016: Provider Call Claim Reconciliation](ADR-0016-provider-call-claim-reconciliation.md) — durable pre-call claim reused unchanged
- [ADR-0017: AI Router Follow-Up Decisions and Multi-Agent Readiness Routing](ADR-0017-ai-router-follow-up-decisions.md) — model allowlist reused unchanged
- [ADR-0018: Software-Team-Persona Capabilities — Scope and First Candidate](ADR-0018-software-team-persona-capabilities.md) — Decision 1's admission policy and Decision 2's Technical Architect fit assessment this ADR activates; Decision 4's isolation pattern this ADR follows
- [ADR-0021: `data.analysis` — a Data-Analyst Review Capability](ADR-0021-data-analysis-capability.md) — the immediately preceding capability built from the same admission policy, whose findings-shape/deployment pattern this ADR mirrors file-for-file

## References

- `.claude/agents/marcus-chen.md` — the Technical Architect persona this capability's prompt tone draws from, copied at build time per ADR-0018 Decision 4's precedent (no runtime coupling to Claude Code's subagent mechanism)
- `src/ai_platform/agents/data_analysis_agent/` — the template this capability's domain module mirrors file-for-file
