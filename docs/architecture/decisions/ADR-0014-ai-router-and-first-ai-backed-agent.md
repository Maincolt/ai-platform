# ADR-0014: AI Router and the First AI-Backed Agent

- **Status:** Accepted
- **Date:** 2026-08-06
- **Supersedes:** None (elaborates ADR-0002 Section 2's placeholder AI
  Router contract; does not change any ADR-0002 decision)
- **Superseded by:** None

## Context

Vertical Slice 01 deliberately proved the platform's orchestration
architecture — Orchestrator, Event Bus, Agent, Registry, persistence,
recovery — using exactly one deterministic, non-AI Agent
(`text.word-count`). This was an explicit, documented choice, not an
oversight: Vertical Slice 01 Section 21 ("Explicit Deferrals") lists "Real
AI/model execution and AI Router" and "Multiple Agent implementations/
deployments" as deferred specifically so the orchestration model could be
proven "without provider nondeterminism or credentials" and "without
inventing scheduling."

That deferral is now being lifted deliberately, at the repository owner's
direction, not discovered as a gap. Three Accepted ADRs already anticipated
this moment and left explicit markers for what must be decided before it
happens:

- **ADR-0002 Section 2** ("Synchronous AI Router Contract") already
  decided that the AI Router exposes a synchronous request-response
  contract, invocable by the Orchestrator and by authorized Agents, but
  explicitly deferred the request/response models, authorization,
  timeouts, cancellation, error semantics, and version compatibility to a
  later decision. This ADR is that later decision.
- **ADR-0005 Section 5** decided the first slice's `task-commands` channel
  is shared by exactly one Agent consumer group, and explicitly warned:
  *"Future heterogeneous Agent types cannot simply use independent
  consumer groups on `task-commands`, because every group would receive
  every retained command. Before adding another command-consuming Agent
  class, the routing model must be reviewed for capability-oriented
  subscriptions or additional bounded-purpose channels."* Adding a second
  Agent class is exactly what this ADR proposes, so that review is part of
  this decision.
- **ADR-0007 Section 20** ("Side-Effect Policy") decided that Vertical
  Slice 01 performs no external side effect, and required: *"Before any
  side-effecting Agent is introduced, a separate ADR or explicitly
  reviewed extension must define: external idempotency-key support and
  result lookup; operation ledger and unknown-outcome reconciliation;
  durable execution claim and fencing where required; partial-success and
  compensation behavior; confirmation, human approval, or policy gates."*
  An AI provider call is exactly the kind of external dependency ADR-0007
  Section 19 already scoped into this category (it lists AI providers
  alongside databases, HTTP services, and shell/process execution as
  requiring a technology-neutral capability port with side-effect
  classification). This ADR provides that review.

### Scope decided by the repository owner

Three scoping questions were resolved directly by the repository owner
before drafting:

1. **Multi-provider from the start.** The AI Router targets more than one
   external AI provider from this first implementation, not a single
   provider with a promise to generalize later.
2. **A narrow, structured Agent capability**, not open-ended chat/Q&A.
   This ADR proposes `text.summarize` — bounded input, bounded output,
   easy to validate structurally, and a natural sibling to the existing
   `text.word-count` capability's `text.*` naming — as the concrete
   proposal for review, not a foreclosed decision; the repository owner
   may redirect this in review.
3. **A fuller Router from the start**: routing/fallback policy across
   providers, and durable cost/usage tracking, are in scope now rather
   than deferred to a second pass.

## Decision Drivers

- ADR-0001's modular, vendor-neutral boundary principle: the AI Router
  must isolate provider SDKs, credentials, and provider-specific error
  shapes from the rest of the platform, exactly as `docs/architecture/README.md`
  already specifies for this component.
- ADR-0002 Section 2's already-decided synchronous contract shape.
- ADR-0005's keyed-partition, bounded-purpose channel model, and its
  explicit routing-model review requirement for a second Agent class.
- ADR-0007's Agent execution model (bounded concurrency lanes, truthful
  outcomes, deterministic recovery) and its Section 19/20 requirements for
  external dependency ports and side-effect policy.
- ADR-0009's structured logging, durable audit, and redaction requirements
  — a real AI call introduces real cost, real latency variance, and real
  untrusted content (both directions) that ADR-0009's existing model must
  absorb without new exceptions.
- ADR-0010's security boundary model and `SECURITY.md`'s already-written
  "External AI Providers," "Prompt Injection and Untrusted Input," and
  "Human Approval for High-Impact Actions" sections — this ADR must
  satisfy those, not restate them.
- Avoiding hidden nondeterminism: routing/fallback policy must be
  configuration-driven and auditable, not a black-box scoring function,
  consistent with how Registry candidate selection already works (ADR-0008).

## 1. AI Router Capability Boundary

The AI Router is a synchronous, technology-neutral port, matching
ADR-0002 Section 2 and ADR-0005 Section 3's direct-communication pattern
(the AI Router is one of the three components ADR-0002 Section 3 names as
exceptional direct-communication cases, alongside the workflow state store
and secrets provider).

### Port shape

```text
AIRouterPort.complete(request: AICompletionRequest) -> AICompletionResult
```

- `AICompletionRequest` carries: a capability-scoped prompt/content
  payload, a bounded maximum-output specification, a caller-supplied
  idempotency key (the calling Agent's `task_attempt_id`), a deadline
  derived from the remaining `task_result_deadline`, and a data
  classification tag (see Section 6).
- `AICompletionResult` is a discriminated outcome: a successful completion
  (normalized text output, provider identity, model identity, token usage,
  latency) or a classified failure (`PROVIDER_UNAVAILABLE`,
  `PROVIDER_RATE_LIMITED`, `PROVIDER_TIMEOUT`, `PROVIDER_REJECTED_INPUT`,
  `PROVIDER_REJECTED_OUTPUT`, `ALL_PROVIDERS_EXHAUSTED`). Callers never see
  a provider-specific exception type or provider-specific error shape.

The port is called by an Agent during its own command-processing
transaction lane (never directly by the Orchestrator in this slice — no
Orchestrator-level AI use case exists yet, so Orchestrator invocation
remains logically permitted per ADR-0002 but is not implemented here).

### Authorization

The caller (an Agent process) authenticates to the AI Router boundary
using the same category of protected, file-injected, environment-scoped
credential already established for Kafka/PostgreSQL access
(`AI_PLATFORM_*_CREDENTIAL_FILE` pattern from
`src/ai_platform/runtime/configuration.py`). The AI Router adapter itself
holds the actual provider API keys, injected the same way; provider
credentials never appear in a task payload, a log, or a durable outcome
record, matching `SECURITY.md`'s existing secret-handling rules.

### Timeout and cancellation

The Router enforces a hard deadline no later than the calling Agent's
remaining `task_result_deadline`, so a slow provider call cannot cause a
`TASK_RESULT_DEADLINE_EXCEEDED` failure to surface later or more
confusingly than a normal deterministic-capability timeout. Cancellation
propagates from the Agent's own bounded concurrency lane (ADR-0007's
existing lifecycle-cancellation model) into the Router call; the Router
does not invent a separate cancellation channel.

### Version compatibility

`AICompletionRequest`/`AICompletionResult` are versioned platform
contracts (JSON Schema, following ADR-0004's existing contract standards),
independent of any provider's request/response version. A provider SDK
upgrade must not force a platform contract version bump unless the
platform-level request/response shape itself changes.

## 2. Provider Selection and Routing Policy

### Providers

Two initial providers, each behind its own adapter:

- **Anthropic Claude**, via the official `anthropic` Python SDK.
- **OpenAI**, via the official `openai` Python SDK.

No third-party multi-provider abstraction library (e.g. LiteLLM) is used.
This follows the same pattern already established for Kafka
(`confluent-kafka` wrapped by a platform-owned adapter, not a generic
messaging abstraction) and PostgreSQL (Psycopg wrapped by platform-owned
transaction ports): the platform owns the normalization and error-mapping
logic directly, so provider-specific behavior cannot leak through an
abstraction the platform does not control. This also keeps ADR-0003's
"no framework" posture for Agent-adjacent code consistent.

### Routing policy

Routing is **configuration-driven and deterministic**, not a scoring
model: each capability declares an ordered list of acceptable
(provider, model) pairs in its Registry-adjacent configuration (see
Section 5). The Router tries the first entry; on a classified retryable
failure (`PROVIDER_UNAVAILABLE`, `PROVIDER_RATE_LIMITED`,
`PROVIDER_TIMEOUT`) it falls through to the next configured entry, bounded
by the same kind of small fixed retry budget already used for Kafka
transport redelivery (ADR-0005 Section 10) — a small bounded number of
provider attempts total across the whole ordered list, not per-provider
unbounded retry. Exhausting the list produces
`ALL_PROVIDERS_EXHAUSTED`, which the calling Agent turns into a normal
`TaskFailed` outcome exactly like any other capability-operation failure
in ADR-0007 Section 18.

This is an explicit, reviewable configuration artifact (mirroring the
Capability Registry's configuration-backed model in ADR-0008), not a
runtime-learned or cost-optimized policy. Cost-based dynamic routing is
explicitly out of scope for this ADR (see Section 9).

## 3. Cost and Usage Tracking

Every completion (successful or failed after a real provider call) records
a durable usage entry: provider, model, input/output token counts (or the
closest provider-reported equivalent), latency, and the calling
`task_attempt_id`/`workflow_id` for correlation — never the raw prompt or
completion content, which stays inside the existing redaction boundary
ADR-0009 already defines for logs, traces, and audit. Usage entries are
operational signals (ADR-0009 Section "Operational Signals" style), not a
new business-audit category; they do not gate or affect workflow
correctness, matching ADR-0009's existing "optional telemetry failure
never changes workflow correctness" principle. No billing integration,
budget enforcement, or spend alerting is in scope for this ADR (Section 9).

## 4. Security

This section states how this ADR satisfies `SECURITY.md`'s existing
"External AI Providers" and "Prompt Injection and Untrusted Input"
sections for this specific boundary; it does not restate or reinterpret
those rules.

- **Data classification.** Every `AICompletionRequest` carries an explicit
  classification tag. `text.summarize`'s input is user-submitted workflow
  text with no assumed higher sensitivity than what the platform already
  accepts at the Workflow API boundary; it is not classified as
  confidential/regulated/customer data by default, and the platform makes
  no claim that submitted text is safe to send to a third-party provider
  beyond what `SECURITY.md` already requires the operator to have
  authorized.
- **Untrusted input and output.** Submitted text is untrusted input to the
  provider; the provider's completion is untrusted output to the platform.
  The Agent must not interpret a completion as containing platform
  instructions, authorization, or control data — it is stored and returned
  as opaque result text, structurally validated (bounded length, valid
  UTF-8) but never parsed as commands. This satisfies `SECURITY.md`'s
  "keep trusted instructions separate from untrusted data" and "do not
  allow embedded content to expand authorization" rules for this specific,
  narrow capability, which does not grant the model tool use, file access,
  or code execution.
- **No human-approval gate is required for `text.summarize`** under
  `SECURITY.md`'s "Human Approval for High-Impact Actions": generating a
  summary is not destructive, irreversible, or high-impact. A future
  Agent capability that takes an action based on model output (sending
  something, mutating durable state beyond its own outcome, invoking a
  tool) would need to satisfy that section separately and is out of scope
  here.
- **Credentials** follow the existing file-injected, environment-scoped
  pattern (Section 1); provider API keys are never logged, never part of
  a task/outcome payload, and redacted in any adapter `repr()`/error path,
  matching the pattern `KafkaSecurityConfig` already established in
  `src/ai_platform/adapters/event_bus/security.py`.

## 5. The First AI-Backed Agent: `text.summarize`

A new built-in Agent, `text.summarize` v1.0, structured identically to the
existing `text.word-count` Agent at the platform-boundary level (same
Registry binding shape, same command/event contracts family, same
lifecycle) but with a non-deterministic, provider-backed execution step in
place of the deterministic word-count computation.

- **Input**: bounded text (same shape as `text.word-count`'s `input`
  field — reusing that bound, not inventing a new one).
- **Output**: bounded summary text, plus the usage metadata from Section 3
  attached to the durable outcome record (not the public API response,
  consistent with ADR-0010's existing internal-evidence/public-disclosure
  separation).
- **Capability declaration**: registered in the Capability Registry
  exactly like `text.word-count` (ADR-0008's existing model needs no
  change — it already treats capability identity, contract versions, and
  Agent identity as configuration-backed data, not as an assumption that
  only one Agent class exists).

### Execution model implications (ADR-0007 Section 18–20)

- **Longer, variable execution time.** Unlike `text.word-count`'s
  near-instant computation, a provider call can take seconds and varies by
  provider load. The Agent's internal attempt budget and the AI Router's
  enforced deadline (Section 1) must fit within the workflow's
  `task_result_deadline` with margin for the existing Kafka/database
  round trip, not consume the entire budget.
- **Side-effect classification and idempotency (ADR-0007 Section 19–20
  checklist, addressed directly):**
  - *External idempotency-key support and result lookup*: the Agent
    supplies its own `task_attempt_id` as the idempotency key on every
    provider call where the provider SDK accepts one. Where a provider
    does not support a request-level idempotency key, the platform does
    not assume the provider deduplicates; it relies entirely on the next
    point.
  - *Durable execution claim and fencing*: before calling the AI Router,
    the Agent durably records a `CLAIMED` state for the `task_attempt_id`
    in the same outcome-persistence transaction shape already used for
    `text.word-count` (ADR-0006's atomic Agent-side unit of work), so a
    crash between claiming and receiving a provider response is
    detectable on redelivery. Unlike `text.word-count` (where recomputation
    after an uncommitted crash is explicitly permitted because the
    function is deterministic and free), a redelivered command that finds
    an existing `CLAIMED` (not yet `COMPLETED`/`FAILED`) record for its
    `task_attempt_id` does **not** blindly re-call the provider — it is
    classified as an unknown-outcome case (next bullet).
  - *Operation ledger and unknown-outcome reconciliation*: a `CLAIMED`
    record with no resolved outcome after a bounded reconciliation window
    is classified `PROVIDER_CALL_OUTCOME_UNKNOWN` and handled the same way
    ADR-0005's "unknown publication" case is already handled elsewhere in
    the platform — quarantined for operator review rather than silently
    retried, so a possibly-already-billed, possibly-already-generated
    completion is never silently duplicated or silently discarded. The
    exact reconciliation window and operator procedure are an open
    question (Section 8), not resolved by this ADR.
  - *Partial-success and compensation*: not applicable — `text.summarize`
    has no multi-step or partial-effect execution; a provider call either
    completes, fails, or is left in the unknown-outcome state above. This
    is stated explicitly rather than left silent, per ADR-0007 Section 20's
    checklist.
  - *Confirmation, human approval, or policy gates*: none required, per
    Section 4's security analysis above.

## 6. Kafka Routing Model for a Second Agent Class

Resolves ADR-0005 Section 5's explicit review requirement.

**Decision**: `task-commands` remains one logical channel (no change to
ADR-0005's logical channel model), but its **physical topic mapping
becomes capability-scoped**. Each capability that has its own Agent
consumer group gets its own physical topic, following ADR-0005 Section 6's
existing principle that physical naming is deployment configuration, not a
domain constant:

```text
ai-platform.<environment>.task-commands.<capability-slug>.v<contract-major>
```

e.g. `ai-platform.development.task-commands.text-word-count.v1` and
`ai-platform.development.task-commands.text-summarize.v1`, each with its
own `.quarantine` companion, matching the existing pattern.

The Orchestrator's command publisher selects the physical topic from the
selected candidate's capability at publish time (the Registry already
knows the capability for every selection — ADR-0008's `SelectionIntent`
already carries `capability_name`); this is a `KafkaTopicMapping`
extension (`src/ai_platform/adapters/event_bus/topics.py`), not a new
Kafka capability beyond ADR-0005 Section 2's already-approved allowlist.
`task-outcomes` remains a single shared topic/consumer group: the
Orchestrator's outcome consumer already correlates every outcome by
`task_attempt_id` regardless of which capability produced it, so there is
no "wrong consumer receives the wrong message" problem on the outcomes
side — only `task-commands` had the problem ADR-0005 flagged.

This keeps each Agent class's consumer group receiving only its own
commands, avoiding both the wasted-processing and the "must safely ignore
messages not addressed to me" complexity a shared-topic-with-app-level-filtering
approach would otherwise require.

## 7. Decision

- The AI Router is a synchronous, technology-neutral port
  (`AIRouterPort.complete`) per Section 1, satisfying ADR-0002 Section 2.
- Two initial providers (Anthropic Claude, OpenAI), each behind a
  platform-owned adapter, no third-party multi-provider abstraction
  library, per Section 2.
- Routing is configuration-driven ordered fallback per capability, bounded
  total retry budget, no dynamic/cost-based routing, per Section 2.
- Durable, redacted cost/usage tracking as an operational signal, no
  billing/budget enforcement, per Section 3.
- Security posture per Section 4, satisfying `SECURITY.md` for this
  specific, narrow, non-tool-using capability without modifying
  `SECURITY.md` itself.
- The first AI-backed Agent is `text.summarize` v1.0, structured like
  `text.word-count` at the platform boundary, with the durable claim/
  unknown-outcome-reconciliation model from Section 5 satisfying ADR-0007
  Section 20's required checklist.
- `task-commands` becomes capability-scoped at the physical-topic level
  per Section 6, resolving ADR-0005 Section 5's review requirement without
  changing ADR-0005's logical channel or Kafka-capability decisions.

## 8. Open Questions

1. What is the bounded reconciliation window and operator procedure for a
   `PROVIDER_CALL_OUTCOME_UNKNOWN` claim (Section 5)?
2. Exact retry-budget numbers (attempts per provider, total attempts
   across the fallback list, backoff) — deployment-tunable values requiring
   the same kind of evidence ADR-0005's open questions already await for
   Kafka retry counts.
3. Which specific Claude and OpenAI models are approved for `text.summarize`,
   and under what data-classification limits — a configuration decision,
   not an architectural one, but it must be recorded somewhere durable
   before deployment.
4. Whether Orchestrator-level (not just Agent-level) AI Router invocation
   is ever needed — ADR-0002 permits it; no use case requires it yet.
5. Whether a second, more capable model of the same provider should be a
   fallback entry before falling over to the other provider, or whether
   cross-provider fallback should always be the immediate second entry —
   a routing-policy configuration question, not resolved here.

## 9. Explicitly Out of Scope

- Cost-based, latency-based, or learned dynamic routing (Section 2 commits
  to deterministic configuration-driven routing only).
- Billing integration, budget enforcement, spend alerting (Section 3).
- Any Agent capability that grants the model tool use, code execution, or
  an ability to trigger a further platform action from its output —
  `text.summarize` returns opaque text only.
- Orchestrator-level AI Router invocation (permitted by ADR-0002, not
  implemented here — no use case yet).
- Open-ended chat/Q&A capabilities — explicitly not chosen for this first
  slice (see "Scope decided by the repository owner" in Context).
- Skills as a distinct reusable-capability layer (still deferred per
  Vertical Slice 01 Section 21; `text.summarize` calls the AI Router
  directly as an Agent-owned capability operation).
- Streaming completions — this Router contract is request/response only.
- Any change to `SECURITY.md`, ADR-0002, ADR-0005, ADR-0007, ADR-0008, or
  ADR-0009's existing Accepted decisions; this ADR elaborates and extends
  within the boundaries they already set.

## 10. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Provider call cost grows unnoticed | Durable per-call usage tracking (Section 3) from the first implementation, even without budget enforcement |
| Non-deterministic output complicates testing | Unit/component tests use a fake `AIRouterPort` implementation (same pattern as the in-memory Event Bus adapter); real-provider tests are external-service tests per `docs/testing/README.md`, opt-in and never required for the default suite |
| Duplicate provider calls on redelivery | Durable pre-call claim + unknown-outcome reconciliation (Section 5), not blind recomputation |
| Prompt injection via submitted text | `text.summarize` grants no tool use or authorization to the model; output is opaque text only (Section 4) |
| Kafka topic proliferation as capabilities grow | Capability-scoped physical topics are deployment configuration (Section 6), consistent with ADR-0005's existing naming-convention pattern, not a new mechanism per capability |
| Provider SDK API changes break the adapter silently | Platform-owned adapters (Section 2) isolate this to one file per provider, matching the existing Kafka/PostgreSQL adapter isolation pattern |

## Related Decisions

- [ADR-0001: Core Design Principles](ADR-0001-core-design-principles.md)
- [ADR-0002: Platform Communication and State](ADR-0002-platform-communication-and-state.md) — Section 2 elaborated here
- [ADR-0005: Event Bus and Messaging Infrastructure](ADR-0005-event-bus-and-messaging-infrastructure.md) — Section 5 routing-model review resolved here
- [ADR-0006: Persistence, State, and Recovery](ADR-0006-persistence-state-and-recovery.md)
- [ADR-0007: Agent Execution Model and Lifecycle](ADR-0007-agent-execution-model-and-lifecycle.md) — Sections 19–20 satisfied here
- [ADR-0008: Capability Registry and Agent Discovery](ADR-0008-capability-registry-and-agent-discovery.md)
- [ADR-0009: Observability, Telemetry, and Audit Correlation](ADR-0009-observability-telemetry-and-audit-correlation.md)
- [ADR-0010: Security, Identity, Authorization, and Trust Boundaries](ADR-0010-security-identity-authorization-and-trust-boundaries.md)

## References

- [Platform Architecture — AI Router](../README.md)
- [Vertical Slice 01, Section 21 — Explicit Deferrals](../../implementation/vertical-slice-01.md)
- [SECURITY.md](../../../SECURITY.md)
- [Anthropic Messages API documentation](https://docs.anthropic.com/en/api/messages)
- [OpenAI API reference](https://platform.openai.com/docs/api-reference)
