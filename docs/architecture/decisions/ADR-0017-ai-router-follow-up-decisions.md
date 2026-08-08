# ADR-0017: AI Router Follow-Up Decisions and Multi-Agent Readiness Routing

- **Status:** Accepted
- **Date:** 2026-08-07
- **Supersedes:** None (elaborates [ADR-0014](ADR-0014-ai-router-and-first-ai-backed-agent.md)
  Section 8 within its existing boundaries; [ADR-0016](ADR-0016-provider-call-claim-reconciliation.md)
  already resolved Open Question 1 of the same section)
- **Superseded by:** None

## Context

ADR-0014 Section 8 recorded five open questions, deliberately left
unresolved so `text.summarize` could ship without blocking on them.
ADR-0016 resolved Question 1 (the reconciliation window/operator
procedure). Sprint 10 picks up the remaining four, plus one question
ADR-0014 did not anticipate: bringing the local Compose topology up to
date with `summarize-agent` (Sprint 10 workstream 1,
`docs/sprint-10/progress.md`) found that a real `text.summarize`
submission never reaches Agent selection at all, because the platform's
Agent-readiness client can only ever reach one Agent process. This is a
direct structural consequence of ADR-0014 adding the platform's second
Agent, so it belongs with this ADR rather than as an unrelated bug fix.

Each of the four original questions was a decision only the repository
owner could make (a cost/quality/compliance choice, a scope-boundary
choice, or a reliability/cost tradeoff with no obviously correct
default) — they were not resolved unilaterally; the repository owner
was asked directly, and this ADR records those answers alongside their
rationale.

## Decision

### 1. Orchestrator-level AI Router invocation (ADR-0014 Section 8 Q4): stays out of scope

The Orchestrator will not invoke the AI Router directly. `text.summarize`
and every future AI-backed capability remain Agent-owned operations,
matching ADR-0007's existing Orchestrator/Agent boundary (the Orchestrator
coordinates; Agents execute capability-specific work, deterministic or
not). ADR-0002 still technically permits Orchestrator-level invocation if
a real use case emerges later — this decision closes the question for
now, not permanently; a future ADR would need a concrete use case to
reopen it, not just revisit the abstract possibility.

### 2. Fallback ordering (ADR-0014 Section 8 Q5): cross-provider, already correctly implemented

On a retryable failure, `FallbackAIRouter` moves to the *next configured
provider* immediately rather than retrying the same provider first. This
was true of the implementation before this ADR
(`src/ai_platform/adapters/ai_router/router.py`: a single pass over
`self._providers` in configured order, one attempt each, no same-provider
repeat) — this decision ratifies that existing behavior as intentional
rather than leaving it as an undocumented accident of how the loop
happens to be written. Rationale: retrying the provider that just failed
spends part of the already-small `maximum_total_attempts` budget
(default 3) on the same failure mode that just occurred; moving to a
different provider gives the request a qualitatively different chance of
succeeding within the same budget. No code change follows from this
decision.

### 3. Approved model allowlist (ADR-0014 Section 8 Q3): formalized, enforced at startup

`text.summarize` is approved to configure exactly these models, chosen
for cost/latency suitability against short-input summarization and
because both are the smallest/cheapest generally-available model in
their respective family as of this ADR (avoiding a larger, costlier model
being configured by accident):

- Anthropic: `claude-haiku-4-5`
- OpenAI: `gpt-5-mini`

No data-classification limit is recorded beyond what ADR-0014 Section 4
already established (`text.summarize` grants no tool use; input is
submitted text only, not classified confidential/regulated data in this
environment). `_build_ai_router` (`src/ai_platform/runtime/composition.py`)
will validate `AI_PLATFORM_AGENT_AI_ROUTER_ANTHROPIC_MODEL`/
`AI_PLATFORM_AGENT_AI_ROUTER_OPENAI_MODEL` against this list at startup,
failing closed (`RuntimeConfigurationError`) on an unapproved value,
matching this platform's existing fail-closed configuration-validation
pattern (`runtime/configuration.py`'s bounded-value validators). Changing
the allowlist is a durable, reviewable change to this ADR (or a
superseding one), not a silent config edit — the list is enforced in
code specifically so an unreviewed model change cannot ship silently.

**Not yet implemented as of this ADR's acceptance** — tracked as follow-up
engineering work in a separate implementation PR, consistent with this
repository's existing pattern of separating ADR acceptance from its
implementation (e.g. ADR-0016 and its implementation PR).

### 4. Retry-budget numbers (ADR-0014 Section 8 Q2): raised defaults, architecture limitation stays open

The current deployment-wide defaults
(`AI_PLATFORM_CONSUMER_MAXIMUM_PROCESSING_ATTEMPTS=5`,
`AI_PLATFORM_CONSUMER_RETRY_DELAY_SECONDS=0.5`, from
`infrastructure/compose/docker-compose.yml`) give roughly a 2.5-second
bounded window before a redelivered command is quarantined. This is fine
for `text.word-count` (deterministic, no external I/O, effectively
instant) but is exactly the failure mode ADR-0016's "Negative"
consequences warned about for `text.summarize`: a real Anthropic/OpenAI
call can legitimately take several seconds, so a 2.5-second budget could
still quarantine a genuinely in-flight provider call on a slower
completion or a redelivery trigger that lands mid-call (consumer
rebalance, a brief network blip), not just a genuinely stuck one.

**Decision**: raise `AI_PLATFORM_CONSUMER_RETRY_DELAY_SECONDS` to `2`
(attempts stay at `5`), giving a ~10-second bounded retry window — long
enough to tolerate a typical in-flight completion without meaningfully
slowing down `text.word-count`'s already-fast path (an extra few seconds
of redelivery latency in the rare case it's ever needed is not
user-visible at word-count's scale).

**Explicitly not resolved by this ADR**: this remains one shared,
deployment-wide value across every consumer (the Orchestrator's outcome
consumer, and both Agents' command consumers), because
`consumer_maximum_processing_attempts`/`consumer_retry_delay_seconds`
are fields on `CommonRuntimeConfig`
(`src/ai_platform/runtime/configuration.py`), not per-capability or
per-consumer-group values. True per-capability tuning (so a future,
slower, or faster capability could have its own budget independent of
`text.word-count`/`text.summarize`) would require restructuring that
configuration shape — real architecture work, not a value change, and
out of scope here. The raised default is a reasonable compromise for the
two capabilities that exist today, not a claim that the shared-config
architecture itself is correct long-term.

### 5. Multi-agent readiness routing (found during Sprint 10, not one of ADR-0014's original five)

**Problem** (see `docs/sprint-10/progress.md` for the full account):
`PlatformRuntimeConfig` has exactly one `readiness_url`
(`AI_PLATFORM_AGENT_READINESS_URL`), and `refresh_agent_availability()`
(`runtime/composition.py`) calls one `AgentReadinessClient` built from
that single URL for *every* Registry binding, regardless of which
Agent/capability it is nominally checking. This worked by construction
when `test-agent` was the only Agent (it shares the platform container's
network namespace — `network_mode: "service:platform"` in
`docker-compose.yml` — so `127.0.0.1:8100` genuinely reaches it).
`summarize-agent`, added by ADR-0014, is a normal separate container
reachable at `summarize-agent:8100` on the Compose network — never at
`127.0.0.1:8100` — so its readiness is never observed, and every
`text.summarize` submission gets `AGENT_TEMPORARILY_UNAVAILABLE`
regardless of how long an operator waits.

**Decision**: move `readiness_url` from platform-level configuration to
the Registry's own binding data. `CapabilityBinding`
(`src/ai_platform/orchestrator/registry/declarations.py`) gains a
`readiness_url: str` field, validated as a well-formed `http(s)` URL
with a hostname at Registry-load time (`runtime/loading.py`, alongside
the other Registry-artifact validation) — deliberately *not* restricted
to a loopback literal the way `PlatformRuntimeConfig`'s single value was:
`summarize-agent`'s real address is its own Compose service DNS name
(`summarize-agent:8100`), never loopback, so a loopback-only check would
reject the exact value this decision requires. The Registry artifact is
a trusted, Git-owned deployment input at the same trust level as
`docker-compose.yml` itself, so well-formedness is what is validated
here, not reachability topology. `refresh_agent_availability()` builds (or reuses) one
`AgentReadinessClient` per distinct `readiness_url` instead of one
shared client for the whole Registry, and looks up each binding's own
URL when refreshing it. `registry.json` gains a `readiness_url` value per
binding (`test-agent`'s stays `http://127.0.0.1:8100/health/ready`;
`summarize-agent`'s becomes `http://summarize-agent:8100/health/ready`).
`AI_PLATFORM_AGENT_READINESS_URL` is removed from
`PlatformRuntimeConfig` entirely — every binding's URL now comes from the
Registry artifact, so there is no remaining use for a single
platform-wide fallback value, and keeping an unused one around would
just be a second, contradictory source of truth.

`AI_PLATFORM_READINESS_CREDENTIAL_FILE` (the bearer secret each Agent's
readiness endpoint checks) stays a single shared platform-wide value —
that part of today's design was never the problem (every Agent already
authenticates readiness requests against the same credential file by
design; only the URL was wrongly assumed to be singular).

**A second binding-side change, found while implementing this decision**:
routing to `summarize-agent:8100` only works if something is actually
listening there. `summarize-agent`'s readiness server previously bound
`AI_PLATFORM_AGENT_READINESS_HOST=127.0.0.1` like every other Agent — but
unlike `test-agent`, it does not share platform's network namespace, so a
loopback bind is only reachable from *inside its own container*, never
from platform's. `AgentRuntimeConfig`'s validation
(`runtime/configuration.py`) required a loopback literal unconditionally,
which would have made this unreachable by construction no matter what
`registry.json` said. The validation now also accepts `0.0.0.0` (bind
every interface), and `summarize-agent`'s Compose service configuration
is changed to it. This is still not a public exposure: the isolated
Compose network is not reachable from the host
(`infrastructure/README.md`), and every readiness request still requires
the shared bearer credential — the security property `docs/operations/README.md`
Section 8 describes as "loopback-only exposure" is preserved for
`test-agent`/`platform` (still genuinely loopback) and replaced with
"internal-network-only, credential-gated" for any Agent in its own
network namespace, which is the only way such an Agent's readiness can
be reachable at all.

**Not yet implemented as of this ADR's acceptance** — tracked as follow-up
engineering work in a separate implementation PR, same as Decision 3.

## Consequences

### Positive

- All four originally-open ADR-0014 questions plus the readiness-routing
  gap have durable, reviewable answers instead of remaining silently
  unresolved.
- The model allowlist closes a real gap: today, any string is accepted
  as `AI_PLATFORM_AGENT_AI_ROUTER_*_MODEL` with no review point before it
  reaches a real provider call.
- The readiness-routing fix is the one change in this ADR that unblocks
  real functionality (a `text.summarize` submission reaching Agent
  selection at all) rather than just formalizing an already-working
  default.

### Negative

- The retry-budget decision is an acknowledged compromise, not a
  complete fix — the underlying shared-config limitation ADR-0016 already
  flagged remains real and is explicitly not solved here.
- The readiness-routing fix touches Registry artifact shape
  (`CapabilityBinding`, `registry.json`, artifact-loading validation) and
  platform composition together — a real, multi-file architecture change,
  not a config-value fix, so it carries the normal risk of any such
  change (documented in the eventual implementation PR's test evidence,
  not assumed safe here).
- The model allowlist requires a durable-change process (edit this ADR
  or supersede it) for any future model change — a deliberate cost in
  exchange for the review guarantee it buys.

## Alternatives Considered

### Per-capability consumer retry configuration (Decision 4)

Restructuring `CommonRuntimeConfig` so `text.word-count` and
`text.summarize` (and any future capability) could each have their own
`maximum_processing_attempts`/`retry_delay_seconds` was considered and
rejected for this ADR specifically because it is real architecture work
disproportionate to what Sprint 10 workstream 3 scoped: resolving the
four already-open questions plus the readiness gap, not redesigning the
consumer configuration shape. Left as a candidate for
`docs/ideas-backlog.md` rather than expanding this ADR's scope.

### A readiness-URL template instead of per-binding values (Decision 5)

A single configured URL *template* (e.g. substituting
`{implementation_identity}` to compute each Agent's URL) was considered
instead of an explicit per-binding field. Rejected: `test-agent` and
`summarize-agent` are reachable through genuinely different mechanisms
(loopback via a shared network namespace vs. a real Compose service DNS
name) — no single template string can express both, so a template would
need per-binding overrides anyway, at which point the explicit field is
simpler and matches how every other binding-specific value
(`deployment_declaration_digest`, `implementation_identity`, and so on)
is already represented.

### Leaving Orchestrator-level AI Router invocation genuinely open (Decision 1)

Recording "still undecided" instead of "closed for now" was considered,
matching ADR-0014's original framing. Rejected once the repository owner
gave a direct answer (keep Agent-only) — recording an actual decision is
more useful to future readers than perpetuating an open question that
now has an answer, and the decision explicitly states it can be reopened
given a real use case rather than claiming permanence it does not have.

## Related Decisions

- [ADR-0014: AI Router and the First AI-Backed Agent](ADR-0014-ai-router-and-first-ai-backed-agent.md) — Section 8 Questions 2-5 resolved here
- [ADR-0016: Provider Call Claim Reconciliation](ADR-0016-provider-call-claim-reconciliation.md) — resolved Section 8 Question 1; this ADR's Decision 4 directly follows from its "Negative" consequences note about shared retry-budget configuration
- [ADR-0007: Agent Execution Model and Lifecycle](ADR-0007-agent-execution-model-and-lifecycle.md) — Orchestrator/Agent boundary Decision 1 preserves
- [ADR-0008: Capability Registry and Agent Discovery](ADR-0008-capability-registry-and-agent-discovery.md) — `CapabilityBinding` shape Decision 5 extends

## References

- `docs/sprint-10/progress.md` — the readiness-routing gap's discovery and root-cause account
- `docs/sprint-10/plan.md` — workstream 3's scope, including the split between engineering-scoped and repository-owner decisions
