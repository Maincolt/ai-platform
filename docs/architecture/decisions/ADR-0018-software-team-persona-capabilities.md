# ADR-0018: Software-Team-Persona Capabilities — Scope and First Candidate

- **Status:** Accepted
- **Date:** 2026-08-09
- **Supersedes:** None
- **Superseded by:** None

## Context

A twelve-person "software development team" (Solution Architect, Technical
Architect, Principal Developer, Senior/Junior Backend Developer, Senior/
Junior Frontend Developer, UI/UX Designer, QA, Product Owner, Scrum
Master, Data Analyst) was built as Claude Code subagents under
`.claude/agents/*.md`. These are prompts a Claude Code session can
delegate to, entirely inside that session — they have no container, are
not registered anywhere, and cost nothing beyond ordinary Claude Code
usage. They are not part of the running ai-platform system, and this ADR
does not change that: the two are separate mechanisms serving separate
purposes, and this document exists specifically because the distinction
was initially unclear.

The request this ADR resolves is different: whether any of these twelve
roles should also exist as real platform Agents — deployables registered
in the Capability Registry, invoked by the Orchestrator over real Kafka
`ExecuteTask` commands, the same way `test-agent` (`text.word-count`) and
`summarize-agent` (`text.summarize`) already are. That is a genuine
architectural question, not a naming exercise: it means a new capability
contract, a new deployable, and — for any role whose output requires real
reasoning rather than deterministic logic — a real AI Router call with
real per-invocation provider cost, the same category of cost ADR-0014/
ADR-0016/ADR-0017 already treat with deliberate care.

ADR-0007's Agent execution model is request/response and bounded: the
Orchestrator dispatches one `ExecuteTask` for one well-defined unit of
work; the Agent returns exactly one `TaskCompleted` or `TaskFailed`.
ADR-0007 Section 20 also requires that any side-effecting capability be
reviewed by ADR before it ships. Not every one of the twelve roles fits
that shape, and some would require platform capabilities (real source
control write access, code execution) that do not exist today and are
themselves a separate, larger architectural surface — this ADR draws that
line explicitly rather than let scope creep in one role at a time.

## Decision

### 1. General admission policy for software-team-persona capabilities

A role becomes a candidate platform capability only if its work is
genuinely a bounded request/response task: one input, one output, no
external side effect beyond the AI Router call itself (the same
side-effect class ADR-0007 Section 19 already assigns to AI provider
calls), and the output is advisory — read by a human or fed into a
downstream review step, never autonomously applied (no auto-committing
code, no auto-merging a PR, no unsupervised edits to a real system). This
preserves the platform's existing human-in-the-loop posture and keeps
every such capability in the same risk class as `text.summarize` rather
than opening a new one.

### 2. Role-by-role fit assessment

**Fits the model now** (bounded input/output, LLM-only, advisory,
no new platform capability required): Solution Architect, Technical
Architect, Principal Developer, QA, UI/UX Designer, and Data Analyst
personas can each be expressed as "read this input, return structured
analysis" — the same shape as `text.summarize`, differing only in prompt
and output structure.

**Does not fit, not pursued by this ADR**: Product Owner and Scrum Master
are continuous facilitation/prioritization roles, not one-shot
request/response work — forcing them into `ExecuteTask`/`TaskCompleted`
would produce a thinner, less useful version of the actual job. Senior/
Junior Backend and Frontend Developer roles would need real source
control write access and code execution to do anything a "developer"
capability should actually do — that is a fundamentally larger
architectural surface (sandboxed execution, git/PR flow, human approval
gates per ADR-0007 Section 20) than an LLM call, and is explicitly out of
scope for this ADR. It may be worth its own future ADR once the platform
has reason to build that surface deliberately, not as a byproduct of this
one.

### 3. First candidate: `code.review`

The first (and only, for this ADR) capability to build is **`code.review`**
— input: a diff/patch plus optional surrounding context; output: a
structured list of review findings (file, line, summary, severity),
never applied automatically. Chosen as the lowest-risk starting point:

- Same side-effect class as `text.summarize` (one AI Router call, no
  other external effect) — no new side-effect category to review under
  ADR-0007 Section 20.
- Strictly advisory output — a human (or another workflow step) decides
  what to do with the findings; the capability itself changes nothing.
- Bounded input/output size, no tool use required of the model.
- Reuses `text.summarize`'s existing machinery — AI Router adapters,
  durable pre-call claim (ADR-0014/ADR-0016), capability-scoped Kafka
  routing (ADR-0014 Section 6), model allowlist enforcement pattern
  (ADR-0017 Decision 3), per-binding readiness routing (ADR-0017
  Decision 5) — with no new provider integration.

`code.review` v1.0 is registered as its own capability
(`capability_version: "1.0"`, matching the existing `text.word-count`/
`text.summarize` pattern), with `result_data` shaped as a findings list
(file, line, summary, severity) rather than free text, following ADR-0015's
generic capability-result model.

### 4. New deployable: `review-agent`

`code.review` ships as its own Agent deployable, `review-agent` —
its own container, its own Kafka principal/ACLs and capability-scoped
topic pair, its own Capability Registry binding with its own
`readiness_url` (ADR-0017 Decision 5), following the exact pattern
`summarize-agent` established. It is not added as a second capability on
`summarize-agent`'s existing process: ADR-0014 Section 6 gave each Agent
class its own consumer group specifically for isolation and independent
blast radius, and a capability with a different persona/prompt and
potentially a different model choice warrants the same isolation. If
further LLM-only advisory capabilities accumulate later, whether to
consolidate them into one generic "advisory agent" process is a fair
question — but it is a future ADR's decision, made once there is a real
second and third example to generalize from, not a default taken now on
the strength of one data point.

`review-agent`'s system prompt draws on the QA/Principal-Developer voice
(Noah Fitzgerald and Elena Petrova's persona framing, from
`.claude/agents/noah-fitzgerald.md` / `.claude/agents/elena-petrova.md`)
for tonal consistency with the team persona already established, but the
running platform process has no runtime dependency on those files or on
Claude Code's subagent mechanism — the persona is copied into the Agent's
own prompt configuration at build time, not loaded from `.claude/agents/`
at runtime. The two systems stay fully decoupled.

### 5. Cost control before real deployment

`code.review`'s model allowlist (which specific Anthropic/OpenAI models
it may be configured with) is **not decided by this ADR** — matching
ADR-0017 Decision 3's own separation of "architecture decision" from
"model selection," and given the repository owner's explicit caution
about AI-provider spend, model selection and real-provider validation for
`code.review` require a deliberate, separate follow-up decision before
any real (non-placeholder) credential is ever configured against it. This
ADR authorizes building and validating `review-agent` against fake/double
`AIRouterPort` implementations only, the same posture `text.summarize`
shipped with initially (ADR-0014's "What doesn't work yet" real-provider
deferral) — no real spend is authorized by this ADR alone.

## Consequences

### Positive

- Draws an explicit, defensible line between the four roles that
  reasonably become platform capabilities today and the ones that would
  require either a mismatched execution model (Product Owner, Scrum
  Master) or a categorically larger architectural surface (the developer
  roles), instead of letting scope expand implicitly one role at a time.
- `code.review` reuses essentially all of `text.summarize`'s existing
  machinery, so the actual new engineering surface is small: one new
  capability contract, one new deployable, one new Registry binding —
  not a new class of platform risk.
- Keeps the human-in-the-loop / advisory-only posture explicit for every
  future software-team-persona capability, not just this first one.
- Explicitly defers real provider cost until a deliberate follow-up
  decision, consistent with the repository owner's stated caution.

### Negative

- Six of the twelve personas (Product Owner, Scrum Master, and the four
  developer roles) get no platform-capability equivalent under this ADR
  — they remain Claude-Code-only. If real demand emerges for a
  "developer capability" with real repo access, that is a materially
  larger future ADR, not an easy extension of this one.
- `review-agent` duplicates infrastructure `summarize-agent` already has
  (its own container, principals, topics, Registry binding) rather than
  sharing a process — more deployables to operate, traded deliberately
  for isolation, per Decision 4's reasoning.
- `code.review`'s persona-consistency with `.claude/agents/` (Decision 4)
  is a soft coupling: if those persona files change meaningfully later,
  `review-agent`'s prompt will silently drift from them unless someone
  remembers to update it — there is no automated link between the two.

## Alternatives Considered

### Build all twelve roles as capabilities at once

Rejected as disproportionate risk, cost, and scope relative to this
platform's own precedent: `text.word-count` shipped alone and was fully
proven before `text.summarize` was attempted as a second, deliberately
scoped step. Twelve simultaneous new capabilities, several of them not
even a good fit for the execution model (Decision 2), would repeat the
mistake ADR-0007 Section 20 was written to prevent — shipping
side-effecting/complex capabilities without individual review.

### Start with a developer-role capability (real repo write access)

Rejected as the first candidate specifically because it needs platform
capabilities that do not exist yet (sandboxed code execution, git/PR
flow, approval gates) — a materially larger and riskier undertaking than
anything `text.summarize` required. Starting there first would mean
building foundational new architecture and validating a new capability
category at the same time, with no smaller precedent to learn from first.

### Add `code.review` to `summarize-agent`'s existing process

Considered, to avoid standing up a second near-identical Agent
deployable. Rejected for the same isolation reasoning ADR-0014 Section 6
already established for keeping Agent classes on separate consumer
groups/topics — a shared process would mean `code.review`'s persona,
prompt, and (potentially) model choice couple `summarize-agent`'s
deploy/scale/failure surface to a second, unrelated capability. Revisit
only if enough small LLM-only capabilities accumulate to justify a
dedicated future ADR for a generic multi-capability advisory process.

## Implementation Status

**Landed in the accepting PR**: the `code.review` contract additions
(`execute_task.schema.json`, `task_completed.schema.json`,
`task_failed.schema.json` capability enums; `task_completed.schema.json`'s
findings-list discriminated branch) and the `review_agent` domain module
(`src/ai_platform/agents/review_agent/`: capability identity, the
`ReviewAgent` execution lifecycle, findings parsing/validation, domain
errors), with unit, component, and contract-level test coverage mirroring
`summarize_agent`'s.

**Not yet implemented** — tracked as follow-up engineering work in a
separate PR, matching this repository's existing pattern of separating an
ADR's domain/contract layer from its deployment wiring (e.g. ADR-0017
Decisions 3 and 5): `runtime/composition.py` executor selection for
`code.review`, the `review-agent` Compose service and its Kafka
principals/topics/ACLs, and its Capability Registry binding. `code.review`
cannot be submitted against the running platform until that follow-up
lands. Real model selection and provider validation (Decision 5) remain a
further, separate, deliberate step after that.

## Related Decisions

- [ADR-0007: Agent Execution Model and Lifecycle](ADR-0007-agent-execution-model-and-lifecycle.md) — request/response shape and Section 20 side-effect review requirement this ADR applies
- [ADR-0008: Capability Registry and Agent Discovery](ADR-0008-capability-registry-and-agent-discovery.md) — `review-agent`'s Registry binding follows this shape
- [ADR-0014: AI Router and the First AI-Backed Agent](ADR-0014-ai-router-and-first-ai-backed-agent.md) — `code.review` reuses its AI Router adapters, claim model, and capability-scoped Kafka routing
- [ADR-0015: Generic Capability Result Model](ADR-0015-generic-capability-result-model.md) — `code.review`'s findings-list `result_data` shape
- [ADR-0016: Provider Call Claim Reconciliation](ADR-0016-provider-call-claim-reconciliation.md) — durable pre-call claim `review-agent` reuses
- [ADR-0017: AI Router Follow-Up Decisions and Multi-Agent Readiness Routing](ADR-0017-ai-router-follow-up-decisions.md) — model allowlist and per-binding readiness routing patterns `review-agent` follows

## References

- `.claude/agents/*.md` — the Claude Code subagent persona files this ADR distinguishes from platform Agents, and the source of `review-agent`'s prompt tone (Decision 4)
- `PROJECT_BRIEF.md` — platform architecture and current capability set
