# QA Sprint 9 Sign-Off

Date: 2026-08-06
Tester: Ivy (QA)

## Scope

ADR-0014 (AI Router and the First AI-Backed Agent) and ADR-0015 (Generic
Capability Result Model). See [docs/sprint-9/done.md](../sprint-9/done.md)
for the complete account.

## Test Results

- Local suite: **420 passed, 49 deselected** (`uv run pytest -q`), up from
  339 at sprint start.
- `text.word-count` (the pre-existing capability) was proven not to
  regress under the ADR-0015 result-model generalization: its full unit,
  component, and `external_service`-marked test coverage was updated and
  re-run against the migrated schema before any `text.summarize` code was
  written, per ADR-0015 Section 5's explicit sequencing requirement.
- `text.summarize`'s lifecycle is covered by 25 new tests against a fake
  `AIRouterPort` and fake/in-memory persistence: success with usage
  attached, provider failure with and without usage, deadline expiry never
  claiming or calling the router, a redelivery finding its own unresolved
  claim resolving to `PROVIDER_CALL_OUTCOME_UNKNOWN` without a second
  provider call, duplicate-commit short-circuit, and command
  identity/integrity conflicts via both the existing-outcome and
  existing-claim paths.
- The AI Router's Anthropic/OpenAI adapters have 57 tests, all against
  injected fake in-process clients — confirmed via grep that no test reads
  a real API key from the environment and no HTTP call is actually
  dispatched (the only references to the provider domains are inert
  `httpx.Request` objects used to construct SDK exceptions).

## Tooling Verification

- `uv run ruff format --check .` — no reformatting needed.
- `uv run ruff check .` — all checks passed.
- `uv run basedpyright` (strict mode) — 0 errors, 0 warnings, 0 notes.

## Real-Service Verification

**Not performed this sprint**, and stated here plainly rather than
omitted or assumed. The local Compose topology already running on this
host predates this sprint's schema migrations (`0003`–`0007`) and Kafka
topic changes (capability-scoped `task-commands`): its Postgres volume was
last initialized with migrations `0001`/`0002` only, and its Kafka broker
still has only the single pre-ADR-0014-Section-6 topic. Bringing it up to
date and re-running the `external_service` suite and a real end-to-end
workflow submission against it is recorded as the concrete next step in
[docs/sprint-9/done.md](../sprint-9/done.md), not claimed as done here.
This is a deliberate scope boundary for this sign-off, matching this
project's practice of never asserting real-service validation that was
not actually executed (see Sprints 6–8's sign-offs for the same standard
applied to their own real-service claims).

Real Anthropic/OpenAI provider validation was never in scope for this
sprint (ADR-0014 Section 9) — this environment has no provider
credentials; the checked-in `ai_router_anthropic_api_key.txt`/
`ai_router_openai_api_key.txt` are obviously-fake placeholders.

## Behavior Coverage

- ADR-0015's generic result model: covered by the full existing
  `text.word-count` suite (proving no regression) plus a new
  `tests/contract/test_task_completed_result_discrimination.py` exercising
  the wire contract's `if`/`then` discrimination both ways.
- ADR-0014's AI Router, provider adapters, fallback routing, and the
  `text.summarize` Agent's claim/reconciliation model: covered as
  described above under Test Results — all against fakes/doubles, not real
  services or providers, consistent with this sprint's stated scope.
- Capability-scoped Kafka routing (`command_topic_binding_for_capability`,
  `KafkaEventPublisher._resolve_topic`): covered by unit tests against the
  pure topic-computation function and the publisher's routing branch; not
  yet exercised against a real broker with two live capability-scoped
  topics (see Real-Service Verification above).

## Blockers

NONE — nothing found blocks the code itself from merging. The deferred
real-topology validation is a recommended pre-merge or immediate
post-merge follow-up, not a defect.

## Issues Filed

None new beyond what is already recorded plainly in
[docs/sprint-9/done.md](../sprint-9/done.md)'s "What was not done" section:
the deferred real-topology re-validation, ADR-0014's five still-open
questions (Section 8), and everything ADR-0014 Section 9 already scoped
out.

## Result

✅ PASS, with one explicit deferred item — **real-topology re-validation
of this sprint's own infrastructure changes has not been performed** and
should happen before or immediately after merge. No production-readiness
claim is made anywhere in this sprint's documentation; real-provider
behavior is explicitly unvalidated per scope.
