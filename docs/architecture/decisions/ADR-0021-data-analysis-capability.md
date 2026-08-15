# ADR-0021: `data.analysis` — a Data-Analyst Review Capability

- **Status:** Accepted
- **Date:** 2026-08-15
- **Supersedes:** None
- **Superseded by:** None

## Context

ADR-0018 Decision 2 assessed twelve software-team personas for fit against
this platform's bounded-advisory execution model and found six that fit
now, including **Data Analyst**: "read this input, return structured
analysis" — the same shape as `text.summarize`, `code.review`,
`ui.review`, and `architecture.review` (ADR-0020), differing only in
prompt and output structure. ADR-0020's own "Negative" consequences
already flagged Data Analyst as the next unbuilt persona from that
original six, "same 'future ADR, not an easy default' posture" as the
personas ADR-0018 rejected outright — this ADR is that future ADR.

Like `architecture.review`, this capability introduces **no new external
side effect and no new architecture**: the input is caller-supplied text
(a dataset excerpt, a metrics/usage summary, or a report — the same
"caller already has the content" shape every prior capability's input
has), and the only external call is the existing single AI Router
`complete()` call. Structurally identical to `architecture.review` end to
end, differing only in the findings' locator key and the review prompt's
persona/framing.

## Decision

### 1. Execution model: identical to `architecture.review`/`code.review`

One AI Router call, same durable pre-call claim (ADR-0016), same
idempotent-replay/deadline handling, same outcome-commit/event-publish
path. No new idempotency mechanism, no new claim model.

### 2. Capability contract shape

`capability_name = "data.analysis"`, `capability_version = "1.0"`,
following [ADR-0015](ADR-0015-generic-capability-result-model.md)'s
generic result model:

- **Input**: the existing generic `payload.input` string field, holding
  the dataset excerpt, metrics summary, or usage/cost report text to
  analyze.
- **Result**: `result_data = {"findings": [...]}`, where each finding is
  `{metric: string (1–200 chars), summary: string (1–2000 chars),
  severity: "low"|"medium"|"high"}` — `metric` identifies which metric,
  data point, or observation the finding refers to (e.g. "p95 latency",
  "monthly active users", "AI provider cost"), the same free-text-locator
  role `architecture.review`'s `section` and `ui.review`'s `area` play.
  Advisory-only, never applied automatically — unchanged from every prior
  AI-backed capability.

### 3. Model reuse: no new model-approval question

Reuses [ADR-0017](ADR-0017-ai-router-follow-up-decisions.md) Decision 3's
approved allowlist unchanged (`claude-haiku-4-5` / `gpt-5-mini`), the same
precedent ADR-0018 Decision 5, ADR-0019 Decision 3, and ADR-0020 Decision 3
already established. Real Anthropic/OpenAI credentials are already
configured in this environment — `data-analysis-agent` uses the same real
credentials, no new provider-cost decision required.

### 4. New deployable: `data-analysis-agent`

Its own Agent deployable — own container (the shared `ai-platform:sprint6`
image; no new runtime dependency, same as `architecture-review-agent`),
own Kafka principal/ACLs and capability-scoped topic pair, own Capability
Registry binding — following the exact isolation pattern ADR-0018
Decision 4 established and every capability since has followed.

## Security

Structurally identical to `architecture.review`'s security posture
(inherited unchanged): the analyzed text is untrusted input to the
provider, the completion is untrusted output to the platform (stored as
opaque structured findings, never parsed as commands); no human-approval
gate is required (advisory output only, no state mutation beyond the
platform's own outcome bookkeeping); no new credential class; no SSRF or
external-fetch consideration (no outbound call beyond the AI Router
itself).

## Alternatives Considered

### A broader "analyze any structured data" capability with real query access

Rejected for the same reason ADR-0020 rejected a generalized review
capability: unnecessarily broad for a first version, and — more
importantly — granting an Agent capability actual query access to a real
data store (rather than caller-supplied text) would be a materially
different, higher-risk architecture: it would need its own credential
class, its own data-access authorization question, and likely the same
kind of approval-gate design the Azure infrastructure agent proposal was
deferred over. This ADR deliberately stays inside the existing
"caller-supplied text in, advisory findings out" shape; a data-store-
connected variant, if ever wanted, is a future ADR's decision once there's
a concrete need and a real authorization design to go with it.

## Consequences

### Positive

- Reuses effectively all of `architecture.review`'s machinery — the only
  new engineering surface is one new capability contract, one new domain
  module (structurally a near-verbatim copy), and one new deployable.
- No new side-effect category, no new security surface, no new
  architecture.
- Closes out the original six-persona set ADR-0018 Decision 2 found
  fitting: Principal Developer/QA-flavored (`code.review`), UI/UX
  Designer-flavored (`ui.review`), Solution Architect
  (`architecture.review`), and now Data Analyst (`data.analysis`) are all
  built; only Technical Architect remains from that original six.

### Negative

- A sixth Agent deployable to operate (own container, principals, topic
  pair, Registry binding) — more deployables, traded for isolation per
  ADR-0018 Decision 4's established reasoning.
- Without real query access to a data store (see Alternatives), this
  capability's practical usefulness is bounded by what the caller already
  chooses to paste in as `payload.input` — a real, deliberate scope limit,
  not an oversight.

## Implementation Status

**Landed in the accepting PR**: the `data.analysis` contract additions
(`execute_task.schema.json`, `task_completed.schema.json`,
`task_failed.schema.json` capability enums; `task_completed.schema.json`'s
findings-list discriminated branch, `{metric, summary, severity}`) and the
`data_analysis_agent` domain module
(`src/ai_platform/agents/data_analysis_agent/`: capability identity, the
`DataAnalysisAgent` execution lifecycle, findings parsing/validation —
including markdown-fence tolerance from day one — domain errors), with
unit, component, and contract-level test coverage mirroring
`architecture_review_agent`'s. Also landed here: `runtime/loading.py`'s
`_SUPPORTED_CAPABILITY_NAMES` and `runtime/composition.py`'s executor
selection, reusing ADR-0017 Decision 3's exact approved model list
unchanged.

Deployment wiring (Compose service, Kafka principals/topics/ACLs,
Registry binding) and live verification against the real Mac Docker host
follow as a separate commit/PR, per this repository's established
pattern.

## Related Decisions

- [ADR-0007: Agent Execution Model and Lifecycle](ADR-0007-agent-execution-model-and-lifecycle.md) — request/response shape this ADR applies
- [ADR-0008: Capability Registry and Agent Discovery](ADR-0008-capability-registry-and-agent-discovery.md) — `data-analysis-agent`'s Registry binding follows this shape
- [ADR-0014: AI Router and the First AI-Backed Agent](ADR-0014-ai-router-and-first-ai-backed-agent.md) — the single-shot `AIRouterPort` contract this capability reuses unchanged
- [ADR-0015: Generic Capability Result Model](ADR-0015-generic-capability-result-model.md) — `data.analysis`'s findings-list `result_data` shape
- [ADR-0016: Provider Call Claim Reconciliation](ADR-0016-provider-call-claim-reconciliation.md) — durable pre-call claim reused unchanged
- [ADR-0017: AI Router Follow-Up Decisions and Multi-Agent Readiness Routing](ADR-0017-ai-router-follow-up-decisions.md) — model allowlist reused unchanged
- [ADR-0018: Software-Team-Persona Capabilities — Scope and First Candidate](ADR-0018-software-team-persona-capabilities.md) — Decision 1's admission policy and Decision 2's Data Analyst fit assessment this ADR activates; Decision 4's isolation pattern this ADR follows
- [ADR-0020: `architecture.review` — a Solution-Architect Review Capability](ADR-0020-architecture-review-capability.md) — the immediately preceding capability built from the same admission policy, whose findings-shape/deployment pattern this ADR mirrors file-for-file

## References

- `src/ai_platform/agents/architecture_review_agent/` — the template this capability's domain module mirrors file-for-file
