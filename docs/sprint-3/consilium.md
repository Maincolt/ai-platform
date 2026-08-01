# Sprint 3 — Team Consilium

> Reviewing Sprint 3 scope: Vertical Slice 01, Phase 3 ("Orchestrator and
> Capability Registry") in full, as pure Python application services and a
> configuration-backed Registry — still composed only against the Phase 2
> `Protocol` ports, no real database/Kafka adapters (Phase 6).

## Remy (Producer)

Phase 3 is the biggest domain-logic phase yet: Registry loading/compatibility/
readiness/selection (ADR-0008), submission-transaction orchestration,
terminal-event processing, deadline reconciliation, and recovery — all
through ports. It splits cleanly into two mostly-independent halves: the
Registry (self-contained; only depends on Sprint 2's `SelectionIntent`
value object) and the Orchestrator application services (submission,
terminal processing, deadline reconciliation — all composed over Phase 2
ports plus whatever public interface the Registry exposes). I'm running
these in parallel this sprint: a background agent builds the Registry
module against a fixed interface spec I hand it up front, while the main
thread builds the application services against that same spec
simultaneously. Integration happens once both land.

## Sage (Domain/Application Engineer)

The submission orchestrator has to reproduce the exact sequence in
[vertical-slice-01.md Section 6](../implementation/vertical-slice-01.md#6-accepted-request-arbitration-and-replay)
and [Section 11](../implementation/vertical-slice-01.md#11-persistence-and-transaction-boundaries)
("Workflow Submission Transaction"): resolve any existing accepted mapping
first (equivalent replay never touches Registry readiness); only a genuinely
new request checks Registry/Agent readiness, freezes selection intent, and
then commits workflow+task+attempt+history+outbox+audit as one unit through
the ports. Terminal processing mirrors Section 11's "Result-Consumption
Transaction": inbox disposition and the workflow transition commit together,
and redelivery of an already-dispositioned message must return the existing
disposition without a second transition. Deadline reconciliation only ever
produces the *second* possible edge out of `DISPATCHED`
(`DISPATCHED -> FAILED`), and the `Workflow` aggregate from Sprint 2 already
guarantees exclusivity between that path and a genuine `TaskCompleted`/
`TaskFailed` — Phase 3 just needs a query capability to find candidates and
apply that existing rule, not new aggregate logic.

## Dash (Tooling/Registry Engineer, background sub-agent)

Delegated the Capability Registry module in full: declaration/binding
model, snapshot loading and validation (duplicate/conflict rejection per
ADR-0008 Section 2 and Section 7), an `AvailabilityPort` protocol plus
freshness classification, and `select_candidate` producing a
`SelectionIntent` (zero eligible -> a stable "no eligible agent" error;
more than one eligible -> a stable "ambiguous candidate" configuration
error, per Section 7's "more than one is a configuration error in this
slice"). Given a fixed interface spec up front so the main thread's
Orchestrator services can be written against it without waiting.

## Ivy (QA Engineer)

Two independent test surfaces this sprint, matching the parallel work: unit
tests for Registry loading/compatibility/selection edge cases (duplicate
declarations, disabled deployments, stale/unknown/unavailable readiness,
zero and multiple eligible candidates), and component tests for the
Orchestrator application services using in-memory fakes for every port
(reusing and extending the Sprint 2 fakes) — first acceptance, equivalent
replay bypassing readiness entirely, fingerprint conflict, terminal-event
idempotency (duplicate/late delivery through the inbox), and the deadline
reconciler racing (and losing to) a genuine terminal event, proving the
Sprint 2 aggregate's exclusivity guarantee actually holds end-to-end.

## Disagreements

1. **Remy vs. Sage — should Sprint 3 include a real recovery/startup-scan
   query capability, or stub it.** Remy wants to keep "recovery" scope
   narrow (just enough for the deadline reconciler to find candidates) since
   full Section 15 failure-window recovery assumes real transactional
   adapters that don't exist until Phase 6. Sage points out ADR-0006
   explicitly lists "deterministic recovery queries for not-attempted,
   unconfirmed, unknown-outcome, claimed, expired, and nonterminal work" as
   a Phase 2/3 port responsibility, not a Phase 6 one.
   **Resolution:** add one narrowly-scoped port,
   `NonterminalWorkflowQueryPort` (returns `DISPATCHED` workflows whose
   `task_result_deadline` has elapsed), sufficient for the deadline
   reconciler. Broader outbox/inbox recovery-query capabilities (not-
   attempted, unknown, claimed-expired publication rows) are explicitly
   deferred — they depend on the outbox/inbox adapters' concrete claim
   mechanics, which do not exist until Phase 6.

2. **Dash vs. Ivy — should the Registry's `select_candidate` accept an
   injected "current time" or read the clock itself.** Ivy wants an
   explicit `now: datetime` parameter so freshness/staleness tests are
   deterministic without patching the clock. Dash agrees this is strictly
   better for testability and no worse for production callers (the
   Orchestrator service already needs `now` for its own timestamps).
   **Resolution:** `now` is an explicit parameter throughout Sprint 3 code,
   never read from a wall clock inside domain/application/registry logic.

## Outcome

Sprint 3 scope confirmed as the whole of Phase 3: Capability Registry
(delegated to a background sub-agent against a fixed interface spec) plus
Orchestrator application services — submission orchestration, terminal
event processing, deadline reconciliation, and one narrowly-scoped recovery
query port — built in parallel on the main thread. Proceeding to
`docs/sprint-3/plan.md`.
