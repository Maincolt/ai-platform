# Sprint 9 — Done

> Scope: ADR-0014 (AI Router and the First AI-Backed Agent) and ADR-0015
> (Generic Capability Result Model)
> Branch: `feature/sprint-9-ai-router-and-summarize-agent`
> Completed: 2026-08-06

## What was built

### 1. Generic capability result model (ADR-0015)

- `AgentOutcome.result_data: Mapping[str, object] | None` and
  `WorkflowResult.result_data: Mapping[str, object]` replace the
  `word_count`-specific fields across the Agent and Orchestrator domain
  layers.
- Persistence: `agent.outcomes.result_data`, `orchestrator.workflows/tasks/
  task_attempts.result_data` are now `JSONB` (migrations `0003`, `0004`),
  each migrated in place from the existing `word_count` integer column.
- Wire contracts: `execute_task`/`task_completed`/`task_failed` schemas
  accept a capability `enum` (`text.word-count`, `text.summarize`) instead
  of a single `const`; `task_completed.schema.json` discriminates its
  `payload.result` shape per capability via `if`/`then` (`result.word_count`
  vs `result.summary`).
- Public API: `WorkflowResultModel` is now a deliberately generic,
  capability-agnostic passthrough (`extra="allow"`, no declared fields)
  instead of a `word_count`-shaped model requiring a contract version bump
  per new capability.
- `text.word-count` was fully re-pointed at the new model with no behavior
  change — this was proven by re-running its full existing test suite
  (unit, component, and the `external_service` suite) against the migrated
  schema before any new capability code was written, per ADR-0015 Section 5.

### 2. AI Router (ADR-0014 Sections 1–3)

- `src/ai_platform/ports/ai_router/` — `AIRouterPort` (`complete(request) ->
  result`), `AICompletionRequest`/`AICompletionResult`/`AICompletionUsage`,
  a closed `AICompletionFailureCode` set (`PROVIDER_UNAVAILABLE`,
  `PROVIDER_RATE_LIMITED`, `PROVIDER_TIMEOUT`, `PROVIDER_REJECTED_INPUT`,
  `PROVIDER_REJECTED_OUTPUT`, `ALL_PROVIDERS_EXHAUSTED`).
- `src/ai_platform/adapters/ai_router/` — `AnthropicProviderAdapter` and
  `OpenAIProviderAdapter` (official SDKs, no third-party abstraction
  library, per the repository owner's "multi-provider from day one"
  scoping decision), and `FallbackAIRouter`, a deterministic,
  configuration-ordered fallback router with a bounded total-attempt
  budget.
- Durable, redacted usage tracking: `agent.provider_call_usage` (migration
  `0007`), populated from `AgentOutcomeCommitIntent.usage` inside the same
  transaction as the outcome commit — internal evidence only, never
  surfaced on the public API (ADR-0010's internal-evidence/
  public-disclosure separation).

### 3. Capability-scoped Kafka routing (ADR-0014 Section 6)

Resolves ADR-0005 Section 5's explicit review requirement for a second
Agent class. `task-commands` remains one logical channel; its physical
topic mapping is now capability-scoped
(`ai-platform.<environment>.task-commands.<capability-slug>.v1`, computed
deterministically by `command_topic_binding_for_capability`). The
Orchestrator's command publisher resolves the physical topic per
selection's `capability_name` at publish time; each Agent process still
just points at one topic name via its own deployment configuration.

### 4. `text.summarize` v1.0 — the first AI-backed Agent (ADR-0014 Sections 4–5)

- `src/ai_platform/agents/summarize_agent/` mirrors `test_agent/`'s
  lifecycle skeleton (resolve completed receipt → check deadline →
  execute) but replaces the deterministic recompute-on-redelivery model
  with a durable pre-call claim: before calling the AI Router, the Agent
  atomically claims the `task_attempt_id`
  (`AgentOutcomeTransactionPort.claim_provider_call`), so a crash between
  claiming and receiving a provider response is detectable on redelivery.
- A redelivery that finds its own unresolved claim never re-calls the
  provider — it commits a `FAILED` outcome with failure_code
  `PROVIDER_CALL_OUTCOME_UNKNOWN`. ADR-0014 Section 8 Q1 leaves the bounded
  reconciliation window and operator procedure for this case open; this
  sprint resolves it conservatively and immediately instead, which is a
  deliberate, documented scoping choice (see the comment at the top of
  `summarize_agent/agent.py`), not the ADR's final answer to that question.
- On success, the outcome's `result_data` is `{"summary": <text>}` and the
  provider call's usage is attached to the commit as internal evidence.

### 5. Runtime, Registry, and Compose wiring

- `runtime/composition.py`'s `build_agent_process()` now selects the
  executor (`TestAgent` vs `SummarizeAgent`) from the loaded declaration's
  `capability_name`, failing closed on anything else.
- `runtime/loading.py`'s `load_agent_deployment_declaration` now selects a
  binding from `registry.json` by `agent_id` rather than requiring exactly
  one binding in the whole file, since the Registry now carries one binding
  per built-in Agent class.
- `infrastructure/compose/runtime/registry.json` carries both bindings.
- `infrastructure/compose/docker-compose.yml` adds a `summarize-agent`
  service (its own Kafka principal pair, its own capability-scoped topic,
  its own AI Router provider secrets) and re-points `test-agent`/
  `test-agent-2` at the narrowed `text-word-count` topic.
- `infrastructure/compose/scripts/init-kafka.sh` creates both
  capability-scoped command topics and narrows `agent-producer`/
  `agent-consumer`'s ACLs to `text-word-count` only, adding a new
  `summarize-agent-producer`/`summarize-agent-consumer` principal pair
  scoped to `text-summarize`.
- The Postgres schema-compatibility gate (`AsyncPsycopgPool`'s
  `expected_schema_version`) is now actually wired to the real, current
  per-component version (orchestrator 3, agent 4) — previously it silently
  defaulted to 1 forever, a latent gap from Sprint 9's own earlier
  migrations (0003/0004) that this sprint also fixed while it was already
  touching this code.

## What was validated

- All four quality gates pass: `uv run ruff format --check .`,
  `uv run ruff check .`, `uv run basedpyright` (strict, 0 errors), and
  `uv run pytest -q` — **420 passed, 49 deselected** (up from 339 at the
  start of the sprint: the ADR-0015 refactor's fixed/added tests, the AI
  Router's 57 tests, and the `text.summarize` Agent's 25 tests).
- `text.summarize`'s full lifecycle (success with usage, provider failure
  with/without usage, deadline expiry never claiming or calling the
  router, unresolved-claim redelivery resolving to
  `PROVIDER_CALL_OUTCOME_UNKNOWN` without a second router call, duplicate
  short-circuit, identity/integrity conflicts via both the existing-outcome
  and existing-claim paths) is demonstrated against a fake `AIRouterPort`
  and a fake/in-memory `AgentOutcomeTransactionPort` — not against a real
  provider or real Postgres.
- The AI Router adapters were verified to never touch real network or
  credentials in tests (confirmed by grep for `os.environ`/`getenv` API-key
  reads and for dispatched HTTP calls to the provider domains — the only
  matches are inert `httpx.Request` objects used to satisfy SDK exception
  constructors).

## What was not done / explicitly deferred

- **Real-provider (Anthropic/OpenAI) validation.** This environment has no
  real credentials. `infrastructure/compose/secrets/ai_router_anthropic_api_key.txt`
  and `ai_router_openai_api_key.txt` are obviously-fake placeholders
  (documented in `infrastructure/README.md`); a real `text.summarize`
  submission through the live Compose topology would reach the provider
  call and fail there, not at startup. Stated plainly per ADR-0014 Section
  9 and this sprint's plan, not simulated or assumed to work.
- **Real-topology re-validation of this sprint's infrastructure changes.**
  The local Compose topology already running on this host (`podman compose
  ps`) predates this sprint's code: its Postgres volume was initialized
  with only migrations `0001`/`0002`, and its Kafka broker still only has
  the single pre-ADR-0014-Section-6 `task-commands.v1` topic. Bringing that
  topology up to date (rebuild the application image, re-run
  `postgres-init` for migrations `0003`–`0007`, re-run `kafka-init` for the
  new capability-scoped topics, start `summarize-agent`, and submit a real
  workflow end-to-end) was **not performed in this session** — it is a
  meaningful additional operational step, not incidental to writing the
  code, and this project's own established practice (Sprints 6–8) is not
  to claim real-service validation that was not actually run. This is the
  natural next step before merging, and does not depend on real provider
  credentials (a `text.summarize` submission through the real stack will
  legitimately fail at the provider call with a classified `FAILED`
  outcome — that failure path itself is worth observing for real, and
  `text.word-count`'s existing `external_service` suite should be re-run
  first to confirm the schema migrations are safe against a real database).
- ADR-0014's five open questions (Section 8) remain open, as scoped:
  reconciliation window/operator procedure, exact retry-budget numbers,
  approved model list, Orchestrator-level AI Router invocation, and
  same-provider-fallback-before-cross-provider ordering.
- Everything ADR-0014 Section 9 already listed as explicitly out of scope
  (cost-based routing, billing integration, streaming, tool use, Skills as
  a layer) remains out of scope.

## Quality gates

- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run basedpyright` (strict) — 0 errors, 0 warnings, 0 notes
- `uv run pytest -q` — 420 passed, 49 deselected
