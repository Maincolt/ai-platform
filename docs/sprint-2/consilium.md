# Sprint 2 — Team Consilium

> Reviewing the proposed Sprint 2 scope: Vertical Slice 01, Phase 2
> ("Workflow Domain and Persistence Ports") in full, as pure Python domain
> code and port interfaces — no database, no adapters (those are Phase 6).

## Remy (Producer)

Phase 2 is large on paper (five-state aggregate, accepted-request
arbitration, actor/owner/scope evidence, task/attempt, transition history,
audit, inbox, outbox, Agent receipt/outcome, persistence ports) but it is
*only* types and interfaces plus the state-machine rules that govern them —
no SQL, no Kafka, no framework. That keeps it tractable in one sprint. The
line I want held: ports are `Protocol` interfaces only. No in-memory
"reference implementation" gets treated as if it were a real adapter — test
fakes stay in `tests/`, not in `src/ai_platform/adapters/`, which remains
empty until Phase 6.

## Sage (Contracts/Domain Engineer)

The domain model has to encode exactly the rules in
[vertical-slice-01.md Section 9](../implementation/vertical-slice-01.md#9-workflow-state-and-transition-model)
(the five states and their legal edges), Section 6 (accepted-request
arbitration key and evidence), and Section 11 (what the submission
transaction stores). I'll model the workflow aggregate as a class that
owns its own transition rules (illegal edges raise, terminal states reject
further mutation, revision always increments, history is append-only) so
the business rules are enforced in one place instead of scattered across
future callers. Ports describe *capabilities* ("append a transition
atomically with the snapshot"), not CRUD — ADR-0006 Section 4 is explicit
that these can't be generic create/read/update methods without losing
correctness, so I will name port methods after the transactions in Section
11, not generic verbs.

## Dash (Tooling Engineer)

Nothing new in tooling this sprint — same `pyproject.toml`/Ruff/BasedPyright
strict/pytest stack from Sprint 1. I'll make sure the new `orchestrator`
subpackages stay import-clean (no accidental adapter/persistence imports
into domain code) and that BasedPyright strict still passes with zero
`Any` leaking out of the new modules.

## Ivy (QA Engineer)

This is finally testable domain behavior, not just contract shape. My test
surface: every legal transition in the Section 9 table succeeds and
appends exactly one history record with an incremented revision; every
illegal edge (e.g. `RECEIVED -> COMPLETED`, or mutating a terminal
workflow) raises a stable domain exception; duplicate/late completion or
failure on an already-terminal workflow does not append duplicate history
or change the recorded outcome; the accepted-request key and evidence
objects are immutable (frozen) so nothing can quietly mutate acceptance
identity after the fact. I will not write tests against Postgres or Kafka —
there isn't one yet, and pretending otherwise would misrepresent Phase 2's
actual scope.

## Disagreements

1. **Sage vs. Remy — should the Workflow aggregate enforce the deadline
   race rule (Section 9, "deadline reconciler wins workflow lock") in
   Phase 2, or defer it.** Sage wants to model it now since it's part of
   the same state table. Remy points out the deadline reconciler is a
   Phase 3 (Orchestrator) *process* concern — the aggregate can and should
   expose "is this workflow already terminal" so a future reconciler can
   respect it, but actually scheduling/racing a reconciler is out of scope
   for domain-only code. **Resolution:** the aggregate enforces that only
   one terminal transition (`COMPLETED` or `FAILED`) is ever accepted from
   `DISPATCHED`, and rejects any further transition once terminal — this
   is sufficient for both the normal outcome race and the future deadline
   race. The reconciler process itself is explicitly out of scope
   (Phase 3).

2. **Ivy vs. Sage — how much of the accepted-request arbitration table
   (Section 6) to encode as domain logic now versus leave to the future
   Orchestrator/API layer (Phase 3/5).** Ivy wants only the parts that are
   pure data/identity rules (the composite key, fingerprint comparison
   outcome as an enum) tested now; Sage initially wanted to also encode
   the full authorization/replay response selection (which HTTP status
   applies) as domain code. **Resolution:** Phase 2 models the composite
   key, the fingerprint-comparison outcome (`NEW`, `EQUIVALENT_REPLAY`,
   `FINGERPRINT_CONFLICT`), and the actor/owner evidence as data plus a
   pure comparison function. Mapping outcomes to HTTP responses is API
   contract behavior and stays deferred to Phase 5.

## Outcome

Sprint 2 scope confirmed as the whole of Phase 2, expressed as pure Python
domain types, a `Workflow` aggregate enforcing the Section 9 state machine,
accepted-request identity/fingerprint-comparison data and logic, and
capability-oriented persistence port `Protocol`s (no adapters). Proceeding
to `docs/sprint-2/plan.md`.
