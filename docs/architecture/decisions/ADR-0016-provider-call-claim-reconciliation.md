# ADR-0016: Provider Call Claim Reconciliation

- **Status:** Accepted
- **Date:** 2026-08-06
- **Supersedes:** None (elaborates ADR-0014 Section 5 / Section 8 Q1 within its existing boundaries)
- **Superseded by:** None

## Context

[ADR-0014](ADR-0014-ai-router-and-first-ai-backed-agent.md) Section 5
requires `text.summarize` to durably claim a `task_attempt_id` before
calling the AI Router, so a crash between claiming and receiving a
provider response is detectable on redelivery. It also states that a
redelivery finding an unresolved claim must be "quarantined for operator
review rather than silently retried, so a possibly-already-billed,
possibly-already-generated completion is never silently duplicated or
silently discarded" — but explicitly left the bounded reconciliation
window and operator procedure as Open Question 1 (Section 8), not
resolved by that ADR.

Sprint 9's implementation (`src/ai_platform/agents/summarize_agent/agent.py`)
filled that gap with a deliberately conservative placeholder, documented
inline as not the ADR's final answer: **any** redelivery that finds its
own unresolved claim, regardless of how much time has passed, immediately
commits a `FAILED` outcome with failure_code `PROVIDER_CALL_OUTCOME_UNKNOWN`
via the ordinary outcome-commit path. This has two problems:

1. **No window at all.** A redelivery can legitimately arrive while the
   original attempt is still genuinely in flight (at-least-once delivery,
   consumer rebalance, a slow-but-healthy provider call). Treating that as
   "unknown" and immediately failing the workflow is premature — the
   original call may be about to succeed.
2. **Not actually a quarantine.** Committing an ordinary `FAILED` outcome
   through the same transaction path used for every other terminal outcome
   is operationally indistinguishable from a normal failure. It does not
   durably flag the case for the elevated scrutiny ADR-0014 calls for
   (a possibly-billed, possibly-generated result whose fate is unknown),
   and it does not use this platform's existing quarantine mechanism —
   it reinvents a narrower one.

Two pieces of existing, already-Accepted infrastructure are directly
applicable and were not reused by the Sprint 9 placeholder:

- **`DeliveryHandlingDisposition.RETRYABLE`**
  (`src/ai_platform/runtime/consumer.py`): `EventConsumerWorker` already
  retries a delivery up to `maximum_processing_attempts` (existing,
  deployment-configured) and then durably quarantines it through
  `RetryExhaustionHandlerPort.quarantine_retry_exhaustion` — the same
  `KafkaTransportQuarantineCoordinator` / `agent.transport_rejections`
  mechanism ADR-0005 already established for malformed/rejected
  messages. An **uncaught exception** from the executor already routes
  here too (`EventConsumerWorker._process_one`'s `except Exception:`),
  with no changes needed to `consumer.py` or `handlers.py`.
- **`DeadlineReconciler`** (`src/ai_platform/orchestrator/application/deadline.py`):
  already periodically expires (fails) any task attempt whose
  `task_result_deadline` passes with no recorded outcome, entirely on the
  Orchestrator side, independent of why the Agent never responded.

## Decision

**A redelivery that finds its own claim still unresolved is treated as
"possibly still in flight" and raises, rather than resolving to a
synthetic outcome.** No new reconciliation window, background worker, or
persistence is introduced — the two existing mechanisms above already
provide both halves ADR-0014 asked for.

1. `SummarizeAgent.handle()` no longer commits a `FAILED`
   `PROVIDER_CALL_OUTCOME_UNKNOWN` outcome when `claim_provider_call`
   returns an existing claim matching the current command's identity. It
   raises a new `ProviderCallReconciliationPendingError` (distinct from
   `CommandIdentityConflictError`/`CommandIntegrityError`, which remain
   unchanged for genuine identity/digest mismatches — those are
   corruption, not in-flight ambiguity). No outcome is committed and no
   claim state changes; the existing claim row is left exactly as it was.
2. This exception propagates uncaught through
   `ExecuteTaskDeliveryHandler.handle()` to `EventConsumerWorker`, which
   already treats any handler exception as retryable up to
   `maximum_processing_attempts`, then durably quarantines the *command
   message* via the existing transport-quarantine path.
   Command-message quarantine is the operator-review signal ADR-0014
   asked for: an operator inspecting `agent.transport_rejections` (or the
   `.quarantine` topic) can join on `task_attempt_id` against
   `agent.provider_call_claims` to see whether a provider call was ever
   claimed, and check the provider's own dashboard/billing for that
   `task_attempt_id`'s idempotency key before deciding what to do.
3. The workflow's own fate is **not** decided by the Agent at all in this
   case. It is decided by the Orchestrator's existing `DeadlineReconciler`:
   once `task_result_deadline` passes with no recorded outcome, the
   workflow fails through the same generic "Agent never responded" path
   every other timeout already uses. This *is* the "bounded reconciliation
   window" ADR-0014 Section 8 Q1 asked for — it is simply the attempt's
   own already-existing deadline, not a second, separate timer.
4. `agent.provider_call_claims` rows are never deleted or updated by this
   flow (already true; unchanged). They are permanent evidence for the
   manual, out-of-band operator reconciliation in (2) — no automated
   reconciliation, alerting, or operator UI is built. That remains
   explicitly out of scope (see below), matching this platform's existing
   quarantine model: quarantine means "durably parked for a human," not
   "automatically resolved."
5. `SummarizeAgentDisposition.PROVIDER_CALL_OUTCOME_UNKNOWN` and the
   failure_code `PROVIDER_CALL_OUTCOME_UNKNOWN` are removed — no outcome
   is ever committed with that shape anymore, so neither has a caller.

### Why the deadline is the right window, not a new one

A separate, shorter "is this actually stuck yet" timer was considered and
rejected: it would require new Agent-side scheduled work (this platform
has no per-command timer primitive today, only periodic workers and
event-driven redelivery), a new persistence column to track it, and a
judgment call about its duration divorced from the one duration that
already matters operationally — how long the workflow's caller is willing
to wait. Reusing `task_result_deadline` means the Agent needs no new
configuration, no new persistence, and no new periodic process; the
window is exactly as long as the workflow was already going to wait
regardless of this ADR.

## Consequences

### Positive

- Zero new infrastructure: no new table, no new background worker, no new
  timer. Every mechanism this decision relies on is already Accepted and
  already implemented for other reasons (ADR-0005 quarantine, ADR-0007
  deadline expiry).
- A genuinely in-flight redelivery is no longer punished with an
  immediate synthetic failure — it gets the same bounded-retry treatment
  every other transient processing condition already gets.
- The operator-review signal is a real quarantine (durably parked,
  distinct from ordinary failures, inspectable via the existing
  transport-rejection tooling) rather than an indistinguishable ordinary
  `FAILED` outcome.
- `agent.provider_call_claims` (added in Sprint 9, migration `0007`)
  needed no schema change for this decision.

### Negative

- Two independent signals (quarantined command + expired workflow) now
  correlate an unknown-outcome case, rather than one dedicated event. An
  operator must know to join them by `task_attempt_id`; this is not
  documented in an operator runbook yet (tracked as follow-up work, not
  this ADR's scope).
- The workflow does not fail until its full `task_result_deadline`
  elapses, even once the command is already quarantined and clearly not
  going to resolve on its own. A caller polling for a result waits the
  full deadline rather than failing fast the moment the ambiguity is
  detected. This is an accepted latency cost in exchange for reusing
  existing infrastructure instead of building a faster-but-new path.
- No automated reconciliation against the provider's own record of what
  happened exists or is planned by this ADR — an operator must manually
  check the provider dashboard/billing using the claim's idempotency key
  (`task_attempt_id`). This is a real operational gap, stated plainly
  rather than hidden, and remains open for a future ADR if it proves
  costly in practice.
- `maximum_processing_attempts` and its retry delay are shared,
  deployment-wide consumer configuration, not tunable specifically for
  this case. A very short retry budget would quarantine a genuinely
  in-flight call too eagerly; this ADR does not change that
  configuration's defaults, leaving the same tuning question ADR-0014
  Section 8 Q2 (retry-budget numbers) and ADR-0005's own open retry-count
  question already left open.

## Alternatives Considered

### A dedicated reconciliation window and background sweep

A new `agent.provider_call_claims.claimed_at`-driven periodic worker
(mirroring `DeadlineReconciler`'s shape) that scans for claims older than
a configured window and only then commits a synthetic `FAILED` outcome.
Rejected: requires new configuration, a new periodic process, and still
faces the same commit-race problem Sprint 9's placeholder had — if the
original in-flight call completes after the sweep already committed a
synthetic failure, the real result is silently discarded by the existing
`ON CONFLICT (task_attempt_id) DO NOTHING` outcome-commit race, exactly
the outcome ADR-0014 said must never happen silently.

### An operator-facing reconciliation API/UI

A new endpoint or admin surface for an operator to explicitly mark a
claim resolved (with the real outcome) after investigating the provider's
own record. Rejected as premature: this platform has no operator UI at
all yet (Vertical Slice 01 Section 21 explicitly defers it), and no
`text.summarize` traffic volume exists to justify building one before
knowing how often this case actually occurs.

### Immediate synthetic failure on any redelivery (Sprint 9's placeholder)

Kept only until this ADR, per its own inline documentation. Rejected as
this ADR's final answer for the reasons in Context above (no window,
not a real quarantine).

## Related Decisions

- [ADR-0005](ADR-0005-event-bus-and-messaging-infrastructure.md) — the
  quarantine mechanism this decision reuses unchanged.
- [ADR-0007](ADR-0007-agent-execution-model-and-lifecycle.md) — the
  deadline-expiry mechanism this decision reuses unchanged; Section
  19–20's side-effect/idempotency checklist this decision continues to
  satisfy for `text.summarize`.
- [ADR-0014](ADR-0014-ai-router-and-first-ai-backed-agent.md) — Section 5
  and Section 8 Q1, which this ADR resolves within ADR-0014's existing
  boundaries without superseding any of its clauses.

## References

- `src/ai_platform/runtime/consumer.py` — `DeliveryHandlingDisposition.RETRYABLE`,
  `EventConsumerWorker._handle_retryable`.
- `src/ai_platform/orchestrator/application/deadline.py` — `DeadlineReconciler`.
- `src/ai_platform/agents/summarize_agent/agent.py` — the Sprint 9
  placeholder this ADR replaces.
- `infrastructure/migrations/0007_agent_provider_call_claims.sql` —
  `agent.provider_call_claims`, unchanged by this ADR.
