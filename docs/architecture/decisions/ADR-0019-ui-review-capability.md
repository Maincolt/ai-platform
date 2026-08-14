# ADR-0019: `ui.review` — a Playwright-Backed UI Review Capability

- **Status:** Proposed
- **Date:** 2026-08-14
- **Supersedes:** None
- **Superseded by:** None

## Context

The platform has two AI-backed advisory capabilities today: `text.summarize`
([ADR-0014](ADR-0014-ai-router-and-first-ai-backed-agent.md)) and
`code.review` ([ADR-0018](ADR-0018-software-team-persona-capabilities.md)).
Both share one execution shape: one bounded input, one synchronous
`AIRouterPort.complete()` call, one structured advisory output. `AIRouterPort`
itself is strictly single-shot — `AICompletionRequest.prompt` is a plain
string; there is no tool-calling, no multi-turn message history, and no
multimodal (image) input anywhere in the codebase. ADR-0014 Section 9
explicitly scoped out "any Agent capability that grants the model tool use,
code execution, or an ability to trigger a further platform action from its
output" — that boundary is unchanged and this ADR does not touch it.

This ADR adds a third capability, `ui.review`, that reviews a web page for
UI/UX/accessibility/console-error problems. The motivating case is the
platform reviewing its own Vue dashboard
(`frontend/dashboard/`, added alongside `GET /api/v1/agents`). Unlike
`code.review` (reviews an already-computed diff) or `text.summarize`
(reviews already-provided text), producing that input requires the platform
itself to fetch a page — a capture step neither existing capability needs.

ADR-0018 Decision 1's admission policy for this class of capability requires
"no external side effect beyond the AI Router call itself." A page fetch is
a second external side effect, and if the fetched URL were caller-influenced
and unconstrained, it would be an SSRF vector: the platform would issue
outbound requests, from inside the Docker network, to wherever a caller
asked. This ADR is filed specifically to resolve that deviation explicitly
rather than let it slide in as an unreviewed extension of ADR-0018 — the
same reasoning ADR-0007 Section 20 already applies to every side-effecting
capability.

## Decision

### 1. Execution model: deterministic capture, then one AI Router call

`ui.review`'s Agent code performs two steps, in order:

1. **Deterministic capture** (the Agent's own Python code, not the model):
   navigate to a fixed target URL using headless Chromium via Playwright,
   and capture the HTTP response status, console errors/warnings emitted
   during load, the page's accessibility tree snapshot, the page title, and
   bounded visible text. This is read-only — `page.goto()` only, no click,
   no form submission, no state mutation on the target.
2. **AI review** — exactly one `AIRouterPort.complete()` call, built from the
   captured signals, asking the model to return structured findings. Same
   shape as `code.review`'s single call; no tool use, no multi-turn
   conversation, no image/screenshot sent to the model (out of scope — see
   "Alternatives Considered").

This keeps `ui.review` inside the AI Router's existing single-shot contract
and ADR-0014 Section 9's tool-use exclusion unchanged. Everything downstream
of the capture step — the durable pre-call claim (ADR-0016), idempotent
replay, deadline handling, outcome commit, event publication — is identical
to `code.review`'s lifecycle; no new idempotency mechanism is introduced.

### 2. Capability contract shape

`capability_name = "ui.review"`, `capability_version = "1.0"`, following
[ADR-0015](ADR-0015-generic-capability-result-model.md)'s generic result
model:

- **Input**: the existing generic `payload.input` string field, holding the
  target URL. The Agent validates it against the hardcoded allowed target
  (Decision 4) before Playwright ever navigates.
- **Result**: `result_data = {"findings": [...]}`, where each finding is
  `{area: string (1–200 chars), summary: string (1–2000 chars), severity:
  "low"|"medium"|"high"}` — the same shape as `code.review`'s
  `{file, line, summary, severity}`, minus `file`/`line` (no file/line
  concept for a web page) and with `area` as a required free-text locator
  instead (e.g. "header navigation", "console", "accessibility").
  Advisory-only, never applied automatically — unchanged from `code.review`.

### 3. Model reuse: no new model-approval question

`ui.review` reuses [ADR-0017](ADR-0017-ai-router-follow-up-decisions.md)
Decision 3's approved allowlist unchanged — `claude-haiku-4-5` (Anthropic),
`gpt-5-mini` (OpenAI) — the same precedent ADR-0018 Decision 5 already
established for `code.review`. This is a text-in/structured-JSON-out task
(captured DOM text, console messages, accessibility tree; no screenshots,
no vision input in this scope) with the same cost/latency profile as
`code.review`'s diff review. No real provider credentials are configured by
this ADR — same posture as `text.summarize`/`code.review` shipped with.

### 4. Resolving the Decision-1 deviation: a hardcoded review target, not an allowlist

The one external side effect beyond the AI Router call — Playwright's page
fetch — is bounded to stay in the same risk class ADR-0018 Decision 1
requires:

- The allowed target is **hardcoded to the platform's own dashboard**,
  `http://platform:80` (the dashboard shares `platform`'s network namespace
  via `network_mode: "service:platform"`; its nginx listens on container
  port 80). There is no configuration path that widens this — reviewing
  anything else requires a deliberate code change, not a config edit.
- The Agent validates the input URL as an exact match against this constant
  before any network call; any mismatch fails closed with
  `DISALLOWED_REVIEW_TARGET`, with no provider-call claim taken and no
  Playwright navigation attempted.
- Playwright does not follow redirects off the allowed host: navigation is
  re-validated against the same exact-match check after any redirect, and
  a mismatch is treated as a capture failure (`PAGE_CAPTURE_FAILED`), not a
  silent follow.

This keeps the fetch bounded, read-only, and non-configurable — the same
"deny-by-default, narrowly scoped" posture `SECURITY.md`'s "Least Privilege"
section requires — rather than introducing an operator-configurable
allowlist, which would be a wider, config-editable surface for the one real
use case this ADR authorizes.

### 5. New deployable: `ui-review-agent`, dedicated image

`ui.review` ships as its own Agent deployable, `ui-review-agent` — own
container, own Kafka principal/ACLs and capability-scoped topic pair, own
Capability Registry binding — following the exact isolation pattern
ADR-0018 Decision 4 established for `review-agent`. Unlike every other
Agent, it needs Chromium, which is a substantial dependency (several
hundred MB, a real build-time cost) that no other service needs. Rather
than bake it into the shared `ai-platform:sprint6` image every other
service (`platform`, `test-agent`, `summarize-agent`, `review-agent`)
builds from, `ui-review-agent` gets its **own dedicated Dockerfile/image**
— keeping every other service's image exactly as small and fast-building
as today.

## Security

This section states how this capability satisfies `SECURITY.md`'s "Least
Privilege," "External AI Providers," "Human Approval for High-Impact
Actions," and "Prompt Injection and Untrusted Input" sections, mirroring
ADR-0014 Section 4's structure; it does not restate or reinterpret those
rules.

- **Data classification.** The captured page content (DOM text, console
  messages, accessibility tree) is the platform's own dashboard rendering
  its own already-public API data — no higher sensitivity than what
  `GET /api/v1/agents` already returns. Sent to the AI Router with
  `DataClassification.NO_SPECIAL_HANDLING`, same as `text.summarize`/
  `code.review`.
- **Untrusted input and output.** The captured page content is untrusted
  input to the provider (it is rendered HTML/JS output, not authored by a
  trusted operator); the completion is untrusted output to the platform —
  stored and returned as opaque structured findings, never parsed as
  commands, matching ADR-0014 Section 4's existing rule for this class of
  boundary.
- **Least privilege / SSRF.** The Playwright fetch is the one piece this
  capability adds beyond `text.summarize`/`code.review`'s risk class. It is
  bounded by Decision 4: a hardcoded target, no redirect-follow past it, no
  configuration path to widen it, deny-by-default (a target mismatch fails
  closed before any network call). This is deliberately not a
  general-purpose "review any URL" capability.
- **No human-approval gate required.** Per `SECURITY.md`'s "Human Approval
  for High-Impact Actions" and ADR-0014 Section 4's identical conclusion
  for `text.summarize`: Playwright's navigation is read-only (no click, no
  form submission, no state mutation), and the findings output is
  advisory-only, never autonomously applied. Not destructive, irreversible,
  or high-impact.
- **Credentials.** No new credential class. Reuses the same file-injected
  AI Router provider credentials `summarize-agent`/`review-agent` already
  use, and the same Kafka SCRAM-credential pattern every Agent uses.
- **Container image.** The new dedicated Chromium-bearing image is held to
  the same `SECURITY.md` "Dependencies and Container Images" bar as every
  other image in this repository.

## Alternatives Considered

### An agentic, tool-calling Agent (the model drives Playwright turn-by-turn)

Rejected for this ADR. This would require: a new port contract supporting
multi-turn message history and tool definitions (`AICompletionRequest` is a
plain string today and cannot represent this); new adapter logic for both
Anthropic and OpenAI actually wiring `tools=`/`tool_choice=` and a
tool-result loop, which exists nowhere in this codebase; a new execution/
idempotency model, since the current durable-claim-before-one-call pattern
does not cover N interleaved provider calls and browser side effects; and,
most importantly, reopening ADR-0014 Section 9's explicit exclusion of
"any capability that grants the model tool use... or an ability to trigger
a further platform action from its output," which would need its own
SECURITY.md Human-Approval-for-High-Impact-Actions analysis given the model
would be able to trigger arbitrary browser actions. Comparable in size to
the entire ADR-0018 initiative; a future ADR's decision if a real use case
for it emerges, not a default reached for on this one's strength.

### Screenshot/vision-based review

Rejected for this scope. Genuine visual regression review (does the page
*look* broken) would need image content sent to the model, which
`AIRouterPort` does not support today (`prompt: str` only) — extending it
for images is a smaller change than full tool-calling, but still a real
contract change affecting both adapters, and the text-only signals
(console errors, accessibility tree, visible text) already cover the
motivating use case (dashboard content/accessibility review) without it.
Worth a future ADR if a genuine visual-diff use case emerges.

### Operator-configurable target allowlist (env var)

Considered, to let an operator later add more review targets (e.g. a
staging environment) without a code change. Rejected for v1: a wider,
config-editable surface than the one real use case needs, and a
misconfigured or overly broad allowlist is a real, easy way to
accidentally reopen the SSRF concern this ADR exists to close. A hardcoded
single target is simpler and more defensible; widening it later is a
deliberate follow-up decision, not a default reached for now.

### Bake Chromium into the shared `ai-platform:sprint6` image

Rejected — every other service (`platform`, `test-agent`,
`summarize-agent`, `review-agent`) would inherit several hundred MB and
meaningfully slower builds for a browser only one service uses. A
dedicated image keeps that cost isolated to the one service that needs it.

## Consequences

### Positive

- Reuses essentially all of `code.review`'s machinery (AI Router adapters,
  durable claim model, model allowlist, capability-scoped Kafka routing,
  Registry binding shape) — the genuinely new engineering surface is the
  Playwright capture step and the hardcoded-target validation, not a new
  platform capability class.
- The dashboard now gets automatic, standing coverage: this ADR's
  Implementation Status establishes the convention (also written into
  CONTRIBUTING.md) that every new Agent capability registers a Compose
  service + Registry binding, which is what made `GET /api/v1/agents` and
  the dashboard pick up `review-agent` with zero frontend changes — and
  will do the same for every capability after this one.
- Resolves the ADR-0018 Decision 1 deviation explicitly and narrowly
  (hardcoded single target) rather than leaving an unreviewed SSRF-shaped
  gap or over-engineering a configurable allowlist nobody asked for yet.

### Negative

- A fourth Agent deployable to operate, with its own dedicated image and
  build pipeline — more Compose/Dockerfile surface than `code.review`
  needed.
- Fixed to reviewing only the dashboard for v1; any other review target
  requires a deliberate code change. This is the intended tradeoff
  (Decision 4), not an oversight, but it does mean this capability cannot
  yet do the more general "review any of our UIs" job a future version
  might want.
- No visual/screenshot-based review — findings are limited to what
  console messages, the accessibility tree, and visible text reveal, which
  will miss purely visual (CSS/layout) problems.

## Implementation Status

**Landed in the accepting PR**: the `ui.review` contract additions
(`execute_task.schema.json`, `task_completed.schema.json`,
`task_failed.schema.json` capability enums; `task_completed.schema.json`'s
findings-list discriminated branch, `{area, summary, severity}`) and the
`ui_review_agent` domain module (`src/ai_platform/agents/ui_review_agent/`:
capability identity, the `UiReviewAgent` execution lifecycle, the hardcoded
target-validation step, findings parsing/validation, domain errors, and the
`PageCapturePort` seam), with unit, component, and contract-level test
coverage mirroring `review_agent`'s.

Also landed here, ahead of `code.review`'s own precedent (which deferred
this to its follow-up PR): `runtime/loading.py`'s
`_SUPPORTED_CAPABILITY_NAMES` and `runtime/composition.py`'s executor
selection for `ui.review`, reusing ADR-0017 Decision 3's exact approved
model list unchanged (Decision 3 above).

**Landed in the second PR**: the real `PlaywrightPageCapture`
(`src/ai_platform/agents/ui_review_agent/capture.py`) — a fresh headless
Chromium instance per call, `page.goto()` only, console messages captured
via a bounded listener, the accessibility tree via Playwright's current
`locator.aria_snapshot()` API (the older `page.accessibility.snapshot()`
this ADR's Context section referenced no longer exists in Playwright
1.62), and the origin re-validation Decision 4 requires: the *landed*
URL's origin (after Playwright's own redirect-following) is checked
against the requested URL's origin, and any mismatch is a capture failure,
never a silent follow. `runtime/composition.py`'s executor selection now
constructs the real implementation instead of the Phase 1 placeholder.
Verified against a real installed Chromium (`uv run playwright install
chromium`), not just fakes: a fixture page's title/console error/
accessibility snapshot are all captured correctly, and a redirect-off-
origin fixture is correctly rejected as a capture failure — both proven
live, not inferred from the code alone (`tests/unit/agents/ui_review_agent/test_capture.py`,
opt-in behind the new `browser` pytest marker, same pattern as
`external_service`).

**Landed in the third PR**, deployment wiring, live-verified against the
real Mac Docker host topology (rebuilt images, real Postgres/Kafka, real
Compose services): the dedicated `ui-review-agent` Docker image
(`infrastructure/ui-review-agent/Dockerfile`, Chromium installed via
`playwright install --with-deps chromium` on `python:3.14-slim-trixie`,
no compatibility issues on Debian trixie); the `ui-review-agent` Compose
service, its own Kafka principals/capability-scoped topic pair/ACLs, and
its Capability Registry binding; the CONTRIBUTING.md standing convention.

`ui-review-agent` starts cleanly and reaches `READY`; `platform`'s own
readiness-refresh logs show a real `200 OK` from
`http://ui-review-agent:8100/health/ready`; `GET /api/v1/agents` lists it
as `READY`/`fresh` alongside the other three capabilities with zero
dashboard or endpoint code changes, confirming the CONTRIBUTING.md
convention actually works as designed. The full live Kafka ACL isolation
matrix (`tests/integration/test_kafka_acl_matrix.py`, all 73 cases
including the 15 new `ui-review-agent-producer`/`-consumer` ones) passed
against the real broker.

A real `POST /api/v1/workflows` submission with `ui.review` reached a real
terminal state: `FAILED`/`ALL_PROVIDERS_EXHAUSTED` — the entire pipeline
(submission → dispatch → Kafka delivery → target validation → real
Playwright/Chromium capture of the real dashboard page → durable
provider-call claim → AI Router call attempted) worked end to end and
only failed at the provider call itself, since no real Anthropic/OpenAI
credentials exist in this environment — the same terminal-state shape
`text.summarize`/`code.review` reach for the identical reason.

**Two genuine bugs were found only by this live deployment, neither of
them by any test beforehand**:

1. A pre-existing, unrelated platform bug, not specific to `ui.review`:
   `runtime/composition.py`'s Orchestrator `command_publisher` was never
   given `environment=`, so publishing *any* capability-scoped command
   (i.e. every real command since ADR-0014 Section 6) unconditionally
   raised `EventBusOperationError`, uncaught, crashing the whole `platform`
   process. This is the actual root cause of the `PLATFORM_SHUTDOWN_
   INCOMPLETE` flakiness previously misattributed to Windows/Podman host
   issues (Sprint 10) and later to unspecified "pre-existing host
   instability" (this ADR's own earlier drafts, and ADR-0018) — it just
   happened to reproduce on `ui.review`'s first-ever submission, on this
   Mac host, with PR #35's shutdown-diagnostics fix already in place to
   finally catch it. Root-caused and fixed to the `JsonLogFormatter` that
   was itself silently dropping the diagnostic `exc_info` PR #35 added
   (see PR #38, landed independently of this ADR since it is a
   platform-wide fix, not a `ui.review`-specific one).
2. `capture.py`'s `_origin()` compared raw, unnormalized `(scheme, netloc)`
   tuples: a real browser's landed `response.url` drops an explicit
   default port (`http://platform:80` navigates and lands on
   `http://platform/`), so the redirect-safety check (Decision 4) treated
   every successful default-port navigation as a redirect off-origin and
   rejected it. Fixed to normalize to `(scheme, hostname, effective_port)`
   with the scheme's default port filled in when none is explicit; a
   fixture-based unit test (`test_origin_normalizes_the_default_http_port`)
   now covers exactly this case.

Also found and fixed along the way (an operational gap, not a code bug):
`kafka/entrypoint.sh` seeds SCRAM credentials only at initial KRaft
formatting, which is a no-op against this host's already-provisioned
`kafka-data` volume — the new `ui-review-agent-producer`/`-consumer`
`--add-scram` lines had no effect until added dynamically via
`kafka-configs.sh` against the live broker. Documented as a standing
operational procedure in `docs/operations/README.md` Section 4.

Real model selection beyond the reused ADR-0017 Decision 3 list, and real
Anthropic/OpenAI provider validation, remain a further, separate,
deliberate step, same as `text.summarize`'s/`code.review`'s.

## Related Decisions

- [ADR-0007: Agent Execution Model and Lifecycle](ADR-0007-agent-execution-model-and-lifecycle.md) — request/response shape and Section 20 side-effect review requirement this ADR applies
- [ADR-0008: Capability Registry and Agent Discovery](ADR-0008-capability-registry-and-agent-discovery.md) — `ui-review-agent`'s Registry binding follows this shape
- [ADR-0014: AI Router and the First AI-Backed Agent](ADR-0014-ai-router-and-first-ai-backed-agent.md) — the single-shot `AIRouterPort` contract this capability stays within, and Section 9's tool-use exclusion this ADR does not reopen
- [ADR-0015: Generic Capability Result Model](ADR-0015-generic-capability-result-model.md) — `ui.review`'s findings-list `result_data` shape
- [ADR-0016: Provider Call Claim Reconciliation](ADR-0016-provider-call-claim-reconciliation.md) — durable pre-call claim reused unchanged
- [ADR-0017: AI Router Follow-Up Decisions and Multi-Agent Readiness Routing](ADR-0017-ai-router-follow-up-decisions.md) — model allowlist reused unchanged
- [ADR-0018: Software-Team-Persona Capabilities — Scope and First Candidate](ADR-0018-software-team-persona-capabilities.md) — Decision 1's admission policy, whose deviation this ADR resolves; Decision 4's isolation pattern this ADR follows

## References

- `SECURITY.md` — "Least Privilege," "External AI Providers," "Human
  Approval for High-Impact Actions," "Prompt Injection and Untrusted
  Input," "Dependencies and Container Images"
- `frontend/dashboard/` — the review target this capability's v1 is
  hardcoded to
- `src/ai_platform/api/app.py`'s `GET /api/v1/agents` — the endpoint that
  makes this (and every future) capability visible on the dashboard once
  registered
