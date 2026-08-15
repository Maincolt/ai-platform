# ADR-0023: `assignment.route` — Team-Based Assignment Routing

- **Status:** Accepted
- **Date:** 2026-08-15
- **Supersedes:** None
- **Superseded by:** None

## Context

The platform now has six content-review capabilities
(`text.summarize`, `code.review`, `ui.review`, `architecture.review`,
`data.analysis`, `technical.review`), each requiring the caller to already
know and specify which one applies. As the "team" of capabilities grew,
that became the friction point: a caller with a free-text assignment (a
design proposal, a PR description, a dataset dump) has to decide up front
which single specialist to submit it to, and has no way to get more than
one specialist's perspective on the same input without manually
resubmitting it several times.

Unlike `code.review` through `technical.review`, **this capability is not
one of the twelve software-team personas ADR-0018 Decision 2 assessed** —
it is a new kind of capability: a triage/routing function that reads an
assignment and recommends which of the team's specialists should look at
it, rather than reviewing content itself. It still fits ADR-0018 Decision
1's general admission policy exactly ("bounded input/output, LLM-only,
advisory, no new platform capability required"), so no new execution
architecture is needed — only a fresh, explicit fit judgment, made here
rather than inherited from ADR-0018 Decision 2.

The deeper question this ADR has to answer is scope, not fit: the request
behind it — "agents must be able to work together as a team" — could mean
anything from "pick the one best specialist" to a fully agentic pipeline
where capabilities call each other. [ADR-0017](ADR-0017-ai-router-follow-up-decisions.md)
already resolved ADR-0014 Section 8's open questions except one,
deliberately: **Orchestrator-level AI Router invocation** was ratified as
staying out of scope. [ADR-0014](ADR-0014-ai-router-and-first-ai-backed-agent.md)
Section 9 separately scoped out any capability that grants a model tool
use or the ability to trigger platform actions from its own output. A
literal "agents call each other" design would cross both boundaries at
once. This ADR deliberately does not reopen either one.

## Decision

### 1. Execution model: identical to every capability since `code.review`

One AI Router call, same durable pre-call claim (ADR-0016), same
idempotent-replay/deadline handling, same outcome-commit/event-publish
path. `assignment.route` itself is a completely ordinary bounded-advisory
capability — it reads text, returns structured output, and does nothing
else. It does not call the Orchestrator, does not submit workflows, and
does not know any capability's implementation exists beyond its name and
one-line description in its own prompt. No new idempotency mechanism, no
new claim model, no new side-effect category.

### 2. Capability contract shape: a recommendation list, not a findings list

`capability_name = "assignment.route"`, `capability_version = "1.0"`,
following [ADR-0015](ADR-0015-generic-capability-result-model.md)'s
generic result model:

- **Input**: the existing generic `payload.input` string field, holding
  the free-text assignment description to route.
- **Result**: `result_data = {"assignments": [...]}`, where each item is
  `{capability: string (one of the six eligible capability names),
  rationale: string (1–2000 chars)}`, 1–6 items. This is a *list* — the
  same structural shape every findings-list capability already uses —
  but its items name *capabilities to route to*, not review findings
  about the input itself. `text.word-count` is deliberately excluded
  from the eligible set (a trivial deterministic capability, not a real
  assignment target), and `assignment.route` cannot recommend itself.
  Advisory-only, same as everything else: nothing is dispatched
  automatically by this capability. It only makes the recommendation.

### 3. Model reuse: no new model-approval question

Reuses [ADR-0017](ADR-0017-ai-router-follow-up-decisions.md) Decision 3's
approved allowlist unchanged. Real Anthropic/OpenAI credentials already
configured in this environment; `assignment-route-agent` uses the same
real credentials.

### 4. New deployable: `assignment-route-agent`

Its own Agent deployable — own container (the shared `ai-platform:sprint6`
image), own Kafka principal/ACLs and capability-scoped topic pair, own
Capability Registry binding — following the exact isolation pattern
ADR-0018 Decision 4 established. This is the eighth such deployable.

### 5. "Working together as a team" happens outside the platform runtime

The actual fan-out — submitting the same assignment to every capability
`assignment.route` recommends, then combining their results into one
report — is **not** built as platform/Orchestrator/Agent architecture.
It is a caller-side script
(`infrastructure/compose/scripts/submit-assignment.py`) that:

1. Submits the assignment text to `assignment.route` through the
   ordinary Workflow API, exactly like any other submission.
2. Reads the recommended `capability` list from the completed result.
3. Submits the *same* assignment text as one ordinary workflow per
   recommended capability — plain, independent `POST /api/v1/workflows`
   calls, nothing new.
4. Polls each workflow to a terminal state through the ordinary read
   endpoint and prints a combined report.

Every individual step this script performs is something any caller could
already do by hand with the existing Workflow API — the script only
automates the sequence. No platform process gains a new capability to
call another capability, submit a workflow, or invoke the AI Router
outside an ordinary Agent's own single call. This is deliberately the
narrowest design that satisfies "agents work together as a team": the
team's members (the six capabilities) each still only ever do one bounded
job, and the coordination between them is external orchestration, not a
new architectural primitive inside the platform.

## Security

Structurally identical to every prior AI-backed capability's posture: the
routed text is untrusted input to the provider, the completion is
untrusted output to the platform (stored as an opaque recommendation
list, never parsed as commands or used to bypass normal submission
validation — each fan-out submission from the dispatch script still goes
through the platform's ordinary `WorkflowSubmitRequest` validation, so a
malformed or out-of-enum recommendation is rejected the same way a
hand-typed bad capability name would be); no human-approval gate required
(advisory output only); no new credential class; no SSRF or
external-fetch consideration.

The dispatch script itself makes multiple ordinary, already-exposed
Workflow API calls under the caller's own existing access — it is not a
new privilege, just automation of calls a caller could already make one
at a time.

## Alternatives Considered

### An in-platform "coordinator" Agent that calls other Agents/submits follow-up work

Rejected. This is precisely the Orchestrator-level AI Router invocation
ADR-0017 deliberately left out of scope, combined with the tool-use/
platform-action capability ADR-0014 Section 9 scoped out. Building it
would mean designing real agentic tool-calling architecture (a new port,
a new trust boundary for an Agent-initiated submission, a human-approval-
gate question per ADR-0007 Section 20) — a materially larger undertaking
than this ADR's actual need, and the same class of gap that stopped the
Azure infrastructure agent proposal earlier. If a genuine need for
in-platform multi-step orchestration emerges later, it deserves its own
ADR built on purpose, not as a byproduct of a routing convenience.

### Recommend exactly one capability instead of a list

Considered and rejected once the user's own framing ("agents must be able
to work together as a team") was clarified to mean multiple specialists
may need to weigh in on one assignment, not just the single best match.
A list with 1–6 items covers both cases: the model returns one item for a
narrowly-scoped assignment and several for a broader one, with no
separate "single mode" needed.

## Consequences

### Positive

- Reuses effectively all of `technical.review`'s machinery — the only new
  engineering surface is one new capability contract (a recommendation-
  list shape instead of a findings-list shape, but the same list-of-
  bounded-objects pattern), one new domain module, one new deployable,
  and one caller-side dispatch script with no platform-architecture
  footprint.
- Lets a caller submit one assignment and get every genuinely relevant
  specialist's perspective without hand-picking a capability or manually
  resubmitting the same text multiple times.
- Keeps both of ADR-0014/ADR-0017's deliberately-deferred boundaries
  (Orchestrator-level AI invocation, tool-calling/platform-action
  capabilities) untouched — this ADR does not quietly reopen either one.

### Negative

- An eighth Agent deployable to operate (own container, principals, topic
  pair, Registry binding).
- The dispatch script's fan-out is not itself durable or resumable the
  way the platform's own submission/outcome machinery is: if the script
  is killed mid-fan-out, already-submitted workflows still complete
  normally (they're ordinary workflows), but the combined report is lost
  and must be re-assembled by hand from the individual workflow IDs. This
  is an accepted limitation of keeping the orchestration outside the
  platform's durable transaction boundary — a durable version would
  require exactly the in-platform coordinator this ADR declined to build.
- `assignment.route`'s recommendation quality is only as good as the
  model's read of six one-line capability descriptions in its prompt; a
  genuinely ambiguous or multi-domain assignment may get an incomplete or
  overly broad recommendation list. Advisory-only mitigates this the same
  way it mitigates every other capability's imperfect output — a human
  can always submit directly to a specific capability instead.

## Implementation Status

**Landed in the accepting PR**: the `assignment.route` contract additions
(`execute_task.schema.json`, `task_completed.schema.json`,
`task_failed.schema.json` capability enums; `task_completed.schema.json`'s
new discriminated branch, `{assignments: [{capability, rationale}]}`) and
the `assignment_route_agent` domain module
(`src/ai_platform/agents/assignment_route_agent/`: capability identity,
the `AssignmentRouteAgent` execution lifecycle, recommendation parsing/
validation — including markdown-fence tolerance from day one — domain
errors), with unit, component, and contract-level test coverage
mirroring `technical_review_agent`'s. Also landed here: `runtime/loading.py`'s
`_SUPPORTED_CAPABILITY_NAMES` and `runtime/composition.py`'s executor
selection.

Deployment wiring (Compose service, Kafka principals/topics/ACLs,
Registry binding), the `submit-assignment.py` dispatch script, and live
verification against the real Mac Docker host follow as separate
commits/PRs, per this repository's established pattern.

**Update (2026-08-15) — deployment wiring, dispatch script, and live
verification landed**: PR #48 added the `assignment-route-agent` Compose
service (shared `ai-platform:sprint6` image), its own Kafka producer/
consumer principals/topic pair/ACLs (`assignment-route-agent-producer`/
`-consumer`, `task-commands.assignment-route.v1` + quarantine companion),
and a Capability Registry binding (revision `local-compose-9`);
`test_kafka_acl_matrix.py` gained matching isolation cases (143 cases
total across all eight capabilities). PR #49 added
`infrastructure/compose/scripts/submit-assignment.py`, the Decision 5
dispatch script.

Deployed to the Mac Docker host following the now-established playbook:
image rebuilt, new SCRAM credentials seeded against the already-
provisioned broker via `kafka-configs.sh --alter`, `platform`/
`test-agent`/`dashboard` recreated for the netns gotcha, and every other
already-running agent restarted per the registry-revision-bump gotcha.
`GET /api/v1/agents` reported all eight capabilities `READY`/`fresh:
true` on the first check. A real submission to `assignment.route` alone
correctly recommended `technical.review` and `data.analysis` for a
mixed schema-design-and-reporting assignment, with accurate rationale
for each. The full 143-case ACL matrix passed live.

`submit-assignment.py` was then run end to end against the same
assignment: it submitted to `assignment.route`, read the two-capability
recommendation, dispatched the same text to both `technical.review` and
`data.analysis` as independent workflows, and printed a combined report
with each capability's genuine, distinct findings (schema/API concerns
from `technical.review`; reporting/metrics concerns from `data.analysis`)
— confirming the "agents work together as a team" design works
end to end, entirely through ordinary Workflow API calls, with no
platform/Orchestrator/Agent architecture change.

## Related Decisions

- [ADR-0007: Agent Execution Model and Lifecycle](ADR-0007-agent-execution-model-and-lifecycle.md) — request/response shape this ADR applies
- [ADR-0008: Capability Registry and Agent Discovery](ADR-0008-capability-registry-and-agent-discovery.md) — `assignment-route-agent`'s Registry binding follows this shape
- [ADR-0014: AI Router and the First AI-Backed Agent](ADR-0014-ai-router-and-first-ai-backed-agent.md) — Section 9's tool-use/platform-action scope-out this ADR deliberately stays inside
- [ADR-0015: Generic Capability Result Model](ADR-0015-generic-capability-result-model.md) — `assignment.route`'s recommendation-list `result_data` shape
- [ADR-0016: Provider Call Claim Reconciliation](ADR-0016-provider-call-claim-reconciliation.md) — durable pre-call claim reused unchanged
- [ADR-0017: AI Router Follow-Up Decisions and Multi-Agent Readiness Routing](ADR-0017-ai-router-follow-up-decisions.md) — the deferred Orchestrator-level AI Router invocation question this ADR deliberately does not reopen; model allowlist reused unchanged
- [ADR-0018: Software-Team-Persona Capabilities — Scope and First Candidate](ADR-0018-software-team-persona-capabilities.md) — Decision 1's admission policy this ADR reuses (not Decision 2's persona list, since this capability is not one of the twelve); Decision 4's isolation pattern this ADR follows
- [ADR-0022: `technical.review` — a Technical-Architect Review Capability](ADR-0022-technical-review-capability.md) — the immediately preceding capability, whose deployment pattern this ADR mirrors file-for-file

## References

- `src/ai_platform/agents/technical_review_agent/` — the template this capability's domain module mirrors file-for-file (adapted for a recommendation-list rather than findings-list result shape)
