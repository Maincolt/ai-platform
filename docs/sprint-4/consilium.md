# Sprint 4 — Team Consilium

> Reviewing Sprint 4 scope: Vertical Slice 01, Phase 4 ("Test Agent") — the
> built-in `text.word-count` capability, its bounded lifecycle, completed-
> receipt deduplication, outcome/event/outbox persistence, and a readiness
> boundary. Still pure Python domain/application code composed over the
> Phase 2 Agent-side ports; no Event Bus consumer, no real adapters
> (Phase 6).

## Remy (Producer)

This phase is smaller than Phase 3 and mostly self-contained — it's the
mirror image of the Orchestrator side, consuming the same contracts
(`ExecuteTask` in, `TaskCompleted`/`TaskFailed` out) that Sprint 1 defined
and Sprint 3's `SubmissionOrchestrator` already produces. No parallel split
needed this sprint; it's one coherent unit of work for one engineer. My
job is making sure we don't accidentally reach into `orchestrator/*`
internals — the Agent must only share *contracts*, never import
Orchestrator domain/application modules directly (AGENTS.md: agents
"remain independent of the location and implementation of other Agents").

## Sage (Domain/Application Engineer)

The lifecycle in [vertical-slice-01.md Section 14](../implementation/vertical-slice-01.md#14-test-agent-execution)
and ADR-0007 Section 4 is precise about ordering: resolve any completed
receipt **before** deciding whether the deadline has expired, so a
redelivered duplicate never gets a different outcome just because time has
passed. Only a genuinely new attempt checks the deadline and, if still
live, executes the deterministic `word_count` calculation — which is just
`len(text.split())`, since Python's default `str.split()` already treats
runs of Unicode whitespace as separators and discards empty segments,
exactly matching "maximal nonempty text segments separated by Unicode
whitespace" with no trimming or normalization needed beyond what `split()`
already does.

For the readiness boundary (ADR-0008 Section 7: "The Agent loads only its
trusted deployment declaration... exposes the loaded declaration identity
through the readiness boundary"), I'm deliberately *not* importing the
Orchestrator's `registry.availability` types. The Agent and Orchestrator
are separate deployables; sharing a module between them would be a real
architectural boundary violation, not just a style preference. I'm
defining a small Agent-owned `AgentReadiness`/`ReadinessClassification` in
`agents/test_agent/readiness.py` instead — a few duplicated lines of enum
values in exchange for genuine deployability independence.

## Ivy (QA Engineer)

Test surface: the deterministic `word_count` function against Unicode
whitespace edge cases (tabs, newlines, multiple/leading/trailing spaces,
empty string); the full lifecycle via in-memory fakes for the three
Agent-side ports (receipt, outcome, event outbox) — first execution
completes and enqueues one event; a redelivered identical command
(same `task_attempt_id`, same `message_id`, same digest) returns the
stored outcome without re-executing or enqueuing a second event; a
different `message_id` for the same attempt is a permanent identity
conflict; a matching `message_id` with different bytes is an integrity
conflict; a command whose deadline has already elapsed before execution
produces a safe `TASK_RESULT_DEADLINE_EXCEEDED` failure without running
the capability at all; and a concurrent duplicate at commit time (two
"first-time" contexts racing for the same attempt) resolves to one durable
outcome, matching ADR-0006's "one logical effect, not exactly-once
computation."

## Disagreements

1. **Sage vs. Remy — should the Agent validate `capability_name`/`version`
   itself, or trust the Orchestrator's selection.** Remy initially wanted
   to skip this validation since Sprint 3's Registry already guarantees an
   exact match before dispatch. Sage points out ADR-0007 Section 2
   explicitly lists "transport, contract, target, capability, input, and
   policy validation" as something the *Agent* owns, independent of
   whatever the Orchestrator believes it selected — the Agent must not
   trust the Orchestrator's selection blindly, since defense-in-depth
   against a misconfigured or stale Registry snapshot is exactly why this
   validation exists as a separate boundary. **Resolution:** the Test
   Agent validates `capability_name`/`capability_version` against its own
   fixed constants before executing, and raises a stable rejection error
   for a mismatch — this is cheap and directly required by ADR-0007.

2. **Ivy vs. Sage — should "lifecycle interruption" (shutdown/restart/
   rebalance cancellation) be modeled in Phase 4.** Ivy wants test coverage
   for every row in Section 14/15; Sage argues lifecycle interruption is
   fundamentally a *process/transport* concern (asyncio task cancellation,
   consumer rebalance) that doesn't exist until a real Event Bus consumer
   is built in Phase 6 — there is no "in-flight execution to interrupt" in
   a synchronous domain-level `handle()` call. **Resolution:** Phase 4
   models only the outcomes that are meaningful at the domain/application
   level (duplicate resolution, identity/integrity conflicts, deadline-
   before-execution, successful completion, concurrent-duplicate
   arbitration). Lifecycle/cancellation behavior is explicitly deferred to
   Phase 6, where a real asyncio-based consumer exists to interrupt.

## Outcome

Sprint 4 scope confirmed as the domain/application-level portion of Phase
4: the deterministic `text.word-count` capability, the Test Agent's
receipt-first idempotency lifecycle, capability validation, and a
readiness boundary — all composed over the Phase 2 Agent-side ports, with
no Event Bus consumer or concrete adapter. Proceeding to
`docs/sprint-4/plan.md`.
