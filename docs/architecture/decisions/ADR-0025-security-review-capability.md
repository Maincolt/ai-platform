# ADR-0025: `security.review` — a Security-Reviewer Review Capability

- **Status:** Accepted
- **Date:** 2026-08-16
- **Supersedes:** None
- **Superseded by:** None

## Context

ADR-0018 Decision 2 assessed **twelve** software-team personas and found
six fit this platform's bounded-advisory execution model: Solution
Architect, Technical Architect, Principal Developer, QA, UI/UX Designer,
and Data Analyst. All six are now built (`code.review`, `ui.review`,
`architecture.review`, `data.analysis`, `technical.review`), and
ADR-0022's Negative section already flagged the consequence: "any further
software-team-persona capability needs a fresh fit assessment ... rather
than reuse of an existing pre-approved slot."

**Security review was never one of the twelve** — there is no dedicated
Security persona in `.claude/agents/`, and ADR-0018 Decision 2 did not
consider or reject it. This ADR performs that fresh fit assessment
against ADR-0018 Decision 1's general admission policy: a role becomes a
candidate platform capability only if its work is a bounded request/
response task — one input, one output, no external side effect beyond
the AI Router call itself, output advisory only, never autonomously
applied. Security review of caller-supplied code, configuration, or
infrastructure-as-code text clearly fits: given a diff, config file, or
design description, produce a structured list of security findings for a
human to act on — the same shape `code.review` already established, just
with a narrower, adversarial lens (injection, authentication/
authorization gaps, secrets handling, insecure defaults, SSRF/path-
traversal-shaped issues, unsafe deserialization) instead of general code
quality.

Structurally this introduces **no new external side effect and no new
architecture**: the input is caller-supplied text (the same "caller
already has the content" shape every prior capability's input has), and
the only external call is the existing single AI Router `complete()`
call. It is a near-verbatim mirror of `technical.review` (ADR-0022),
which is itself structurally identical to `architecture.review`/
`data.analysis` — differing only in the findings' locator key and the
review prompt's persona/framing.

## Decision

### 1. Execution model: identical to `technical.review`/`data.analysis`/`architecture.review`

One AI Router call, same durable pre-call claim (ADR-0016), same
idempotent-replay/deadline handling, same outcome-commit/event-publish
path. No new idempotency mechanism, no new claim model.

### 2. Capability contract shape

`capability_name = "security.review"`, `capability_version = "1.0"`,
following [ADR-0015](ADR-0015-generic-capability-result-model.md)'s
generic result model:

- **Input**: the existing generic `payload.input` string field, holding
  a code diff, configuration file, Dockerfile/infrastructure-as-code
  snippet, or design description to review for security concerns.
- **Result**: `result_data = {"findings": [...]}`, where each finding is
  `{location: string (1–200 chars), summary: string (1–2000 chars),
  severity: "low"|"medium"|"high"}` — `location` identifies where the
  finding applies (e.g. "Dockerfile line 12", "POST /api/v1/workflows
  input validation", "hardcoded credential in config.py"), the same
  free-text-locator role `technical.review`'s `component`,
  `architecture.review`'s `section`, and `data.analysis`'s `metric`
  play. Advisory-only, never applied automatically — unchanged from
  every prior AI-backed capability; nothing about reviewing *security*
  content changes this platform's existing no-auto-remediation posture.

### 3. Review prompt: an adversarial security lens

Unlike `code.review`'s general code-quality framing and
`technical.review`'s buildability framing, `security.review`'s prompt
explicitly instructs the model to look for injection vulnerabilities,
authentication/authorization gaps, secrets and credential handling,
insecure defaults, SSRF/path-traversal-shaped issues, and unsafe
deserialization. There is no existing `.claude/agents/*.md` persona file
for a Security role to draw tone from (unlike `code.review`'s QA/
Principal-Developer voice, per ADR-0018 Decision 4) — the persona is
defined directly in the prompt this ADR's implementation ships.

### 4. Model reuse: no new model-approval question

Reuses [ADR-0017](ADR-0017-ai-router-follow-up-decisions.md) Decision 3's
approved allowlist unchanged (`claude-haiku-4-5` / `gpt-5-mini`), the same
precedent every prior review capability has established. Real Anthropic/
OpenAI credentials are already configured in this environment —
`security-review-agent` uses the same real credentials, no new
provider-cost decision required.

### 5. New deployable: `security-review-agent`

Its own Agent deployable — own container (the shared `ai-platform:sprint6`
image; no new runtime dependency), own Kafka principal/ACLs and
capability-scoped topic pair, own Capability Registry binding —
following the exact isolation pattern ADR-0018 Decision 4 established and
every capability since has followed. This is the ninth Agent deployable.

### 6. Routable via `assignment.route`

`"security.review"` is added to `assignment.route`'s routable-capability
enum (`task_completed.schema.json`'s `assignments[].capability`), so
team-based assignment routing (ADR-0023) can dispatch work to it exactly
like every other review capability.

## Security

The reviewed text is untrusted input to the provider, and the completion
is untrusted output to the platform, stored as opaque structured findings
and never parsed as commands — the same posture every prior AI-backed
capability has. No human-approval gate is required: the output is
advisory only, with no state mutation beyond the platform's own outcome
bookkeeping — a `security.review` finding does not, and cannot, change
any system on its own. No new credential class. No SSRF or external-fetch
consideration, since there is no outbound call beyond the AI Router
itself. This capability's *subject matter* being security does not change
any of that: it is still exactly as bounded as `technical.review`, just
reviewing different content. The one genuinely new risk worth naming
explicitly is prompt injection via the reviewed text itself (e.g. text
that tries to instruct the model to report no findings) — this is not a
new risk class introduced by this ADR, but the same untrusted-input
handling every prior capability already assumes, and it is inherently
lower-stakes here than elsewhere: the worst case is a missed or
misleading advisory finding, still subject to human review before any
action is taken.

## Alternatives Considered

### A capability with real dependency-scanning or repository access

Rejected as a materially larger architectural surface: granting an Agent
capability access to a real filesystem, source-control system, or
dependency-vulnerability database (rather than caller-supplied text)
would need its own credential class, its own access-authorization
question, and likely change the risk posture enough to warrant the same
approval-gate design deferred for the Azure infrastructure agent
proposal. This ADR deliberately stays inside the existing "caller-
supplied text in, advisory findings out" shape, matching
`technical.review`'s equivalent rejected alternative; a repository- or
scanner-connected variant, if ever wanted, is a future ADR's decision
once there's a concrete need and a real authorization design to go with
it.

## Consequences

### Positive

- Reuses effectively all of `technical.review`'s machinery — the only
  new engineering surface is one new capability contract, one new domain
  module (structurally a near-verbatim copy), and one new deployable.
- No new side-effect category, no new security surface, no new
  architecture — including for a capability whose subject matter is
  security itself.
- Extends coverage to a role genuinely useful to this platform's own
  development, without requiring any of the twelve original personas to
  be revisited.

### Negative

- A ninth Agent deployable to operate (own container, principals, topic
  pair, Registry binding) — more deployables, traded for isolation per
  ADR-0018 Decision 4's established reasoning.
- No existing `.claude/agents/*.md` persona file to anchor prompt tone
  to, unlike `code.review` — the prompt persona is authored fresh here
  and could drift from how a "security reviewer" voice is understood
  elsewhere in the repo, with no automated link to keep them consistent.

## Implementation Status

**Landed in the accepting PR**: the `security.review` contract additions
(`execute_task.schema.json`, `task_completed.schema.json`,
`task_failed.schema.json` capability enums; `task_completed.schema.json`'s
findings-list discriminated branch, `{location, summary, severity}`; and
`security.review` added to `assignment.route`'s routable-capability enum)
and the `security_review_agent` domain module
(`src/ai_platform/agents/security_review_agent/`: capability identity,
the `SecurityReviewAgent` execution lifecycle, findings parsing/
validation — including markdown-fence tolerance from day one — domain
errors), with unit, component, and contract-level test coverage
mirroring `technical_review_agent`'s. Also landed here: `runtime/loading.py`'s
`_SUPPORTED_CAPABILITY_NAMES` and `runtime/composition.py`'s executor
selection, reusing ADR-0017 Decision 3's exact approved model list
unchanged.

Deployment wiring (Compose service, Kafka principals/topics/ACLs,
Registry binding) and live verification against the real Mac Docker host
follow as a separate commit/PR, per this repository's established
pattern.

**Update (2026-08-16) — deployment wiring landed and live-verified**: PR
#54 added the `security-review-agent` Compose service (shared
`ai-platform:sprint6` image), its own Kafka producer/consumer
principals/topic pair/ACLs (`security-review-agent-producer`/
`-consumer`, `task-commands.security-review.v1` + quarantine companion),
and a Capability Registry binding (revision `local-compose-10`); the new
Kafka secrets were declared in the top-level `secrets:` stanza from the
start, per the standing lesson from `architecture.review`'s deployment.
`test_kafka_acl_matrix.py` gained matching isolation cases (162 cases
total across all nine capabilities). Deployed to the Mac Docker host:
image rebuilt, new SCRAM credentials seeded against the already-
provisioned broker via `kafka-configs.sh --alter`, all eleven
agent/platform/dashboard/test-agent services recreated for the
registry-revision-bump gotcha. `GET /api/v1/agents` reported all nine
capabilities `READY`/`fresh: true` on the first check, confirmed
visually via a Playwright screenshot of the live dashboard showing
"9 / 9 online" with `security.review` as its own card and zero frontend
changes needed. A real submission (a deliberately vulnerable Python
snippet with SQL injection via string concatenation, a hardcoded live
API key, SQL injection via f-string interpolation, and a missing
auth/authz check on a destructive endpoint) reached `COMPLETED` with
four genuine, sharply specific findings from the real Anthropic
provider — not a placeholder/fixture response. The full 162-case ACL
matrix, including the new principals' isolation cases, passed live
against the broker.

## Related Decisions

- [ADR-0007: Agent Execution Model and Lifecycle](ADR-0007-agent-execution-model-and-lifecycle.md) — request/response shape this ADR applies
- [ADR-0008: Capability Registry and Agent Discovery](ADR-0008-capability-registry-and-agent-discovery.md) — `security-review-agent`'s Registry binding follows this shape
- [ADR-0014: AI Router and the First AI-Backed Agent](ADR-0014-ai-router-and-first-ai-backed-agent.md) — the single-shot `AIRouterPort` contract this capability reuses unchanged
- [ADR-0015: Generic Capability Result Model](ADR-0015-generic-capability-result-model.md) — `security.review`'s findings-list `result_data` shape
- [ADR-0016: Provider Call Claim Reconciliation](ADR-0016-provider-call-claim-reconciliation.md) — durable pre-call claim reused unchanged
- [ADR-0017: AI Router Follow-Up Decisions and Multi-Agent Readiness Routing](ADR-0017-ai-router-follow-up-decisions.md) — model allowlist reused unchanged
- [ADR-0018: Software-Team-Persona Capabilities — Scope and First Candidate](ADR-0018-software-team-persona-capabilities.md) — Decision 1's admission policy this ADR performs a fresh fit assessment against; Decision 4's isolation pattern this ADR follows
- [ADR-0022: `technical.review` — a Technical-Architect Review Capability](ADR-0022-technical-review-capability.md) — the immediately preceding capability built from the same admission policy, whose findings-shape/deployment pattern this ADR mirrors file-for-file
- [ADR-0023: `assignment.route` — Team-Based Assignment Routing](ADR-0023-assignment-route-capability.md) — the routable-capability enum this ADR extends

## References

- `src/ai_platform/agents/technical_review_agent/` — the template this capability's domain module mirrors file-for-file
