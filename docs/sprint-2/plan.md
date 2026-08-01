# Sprint 2 — Workflow Domain and Persistence Ports

> Sprint Goal: Implement Vertical Slice 01, Phase 2 in full: the five-state
> workflow aggregate, accepted-request arbitration identity/evidence,
> task/attempt, transition history, audit, inbox/outbox/receipt records, and
> capability-oriented persistence ports — as pure Python domain code and
> `Protocol` interfaces. No database, no adapters (Phase 6).
> Branch: `feature/sprint-2-domain-and-persistence-ports`
> Scope authority: [Vertical Slice 01, Section 20, Phase 2](../implementation/vertical-slice-01.md#20-implementation-phases)
> See also: [Sprint 2 team consilium](consilium.md)

## Prioritized Task List

| # | Task | Owner | Description |
|---|------|-------|-------------|
| 1 | Workflow state and identifiers | Sage | `WorkflowState` enum (`RECEIVED`, `PENDING`, `DISPATCHED`, `COMPLETED`, `FAILED`); typed identifier aliases for the lowercase-UUIDv7 IDs already defined in `contracts/` |
| 2 | Accepted-request identity and evidence | Sage | `AcceptedRequestKey` (`environment`, `operation`, `idempotency_scope_id`, `request_id`), `AcceptanceEvidence` (actor/owner/fingerprint fields), `FingerprintComparison` enum (`NEW`, `EQUIVALENT_REPLAY`, `FINGERPRINT_CONFLICT`) and a pure comparison function, per [Section 6](../implementation/vertical-slice-01.md#6-accepted-request-arbitration-and-replay) |
| 3 | Selection intent | Sage | `SelectionIntent` frozen dataclass capturing the immutable evidence listed in [Section 7](../implementation/vertical-slice-01.md#7-capability-registry-selection-and-readiness) ("Before the submission transaction...") |
| 4 | Task and task attempt | Sage | `Task`, `TaskAttempt` dataclasses (`attempt_number` fixed at 1 per Section 2) |
| 5 | Transition history | Sage | `TransitionRecord` (immutable) capturing `from_state`, `to_state`, `revision`, `occurred_at`, `cause` |
| 6 | Workflow aggregate | Sage | `Workflow` class enforcing the Section 9 state table: legal transitions only, revision increments, append-only history, terminal immutability, safe rejection of illegal/duplicate/late transitions via a stable domain exception |
| 7 | Result and failure | Sage | `WorkflowResult` (`word_count`), `WorkflowFailure` (`code`, `detail`) value objects matching the public contracts from Sprint 1 |
| 8 | Audit record | Sage | `AuditRecord` value object (kind, workflow_id, occurred_at, actor_id, bounded details) per ADR-0009/ADR-0006 coupled-audit responsibility |
| 9 | Inbox/outbox/receipt records | Sage | `OrchestratorOutboxRecord`, `OrchestratorInboxRecord`, `AgentCompletedReceipt`, `AgentOutcome`, `AgentEventOutboxRecord`, `PublicationState` enum, per [Section 12](../implementation/vertical-slice-01.md#12-transactional-outbox-and-delivery) and [Section 13](../implementation/vertical-slice-01.md#13-inbox-rejection-retry-and-quarantine) |
| 10 | Persistence ports | Sage | Capability-oriented `Protocol` interfaces per [ADR-0006 Section 4](../architecture/decisions/ADR-0006-persistence-state-and-recovery.md#4-persistence-port-boundaries): workflow repository, transition repository, accepted-request repository, task/attempt repositories, Orchestrator outbox/inbox repositories, Agent receipt/outcome/event-outbox repositories. Methods named after the transactions in Section 11, not generic CRUD. |
| 11 | Domain unit tests | Ivy | `tests/unit/orchestrator/` — every legal Section 9 transition succeeds with correct revision/history; every illegal/duplicate/late transition raises; terminal immutability; fingerprint comparison outcomes; accepted-request/evidence immutability |
| 12 | Port contract tests with in-memory fakes | Ivy | `tests/component/orchestrator/` — in-memory fakes (test-owned, not adapters) prove each port `Protocol` is implementable and exercises its documented capability (e.g. compare-and-set by revision, exactly-once outcome per `task_attempt_id`) |
| 13 | Sprint coordination | Remy | Keep scope to Phase 2 only; ports are `Protocol`s, no adapters/no I/O; triage any follow-up to `docs/ideas-backlog.md` |

## Work Schedule

### Phase A: Value Objects and Identity (tasks 1-5, 7-9)
- All immutable data types: state enum, accepted-request identity/evidence, selection intent, task/attempt, transition record, result/failure, audit, inbox/outbox/receipt records.
- Checkpoint commit: `sprint-2: add workflow domain value objects`.

### Phase B: Workflow Aggregate and Ports (tasks 6, 10)
- `Workflow` aggregate enforcing the state machine; persistence port `Protocol`s.
- Checkpoint commit: `sprint-2: add workflow aggregate and persistence ports`.

### Phase C: Tests and Sign-off (tasks 11-13)
- Unit and component (in-memory fake) tests.
- QA sign-off (`docs/qa/sprint-2-signoff.md`).
- Final commit and PR.

## Success Criteria

- [ ] `uv run ruff format --check .` and `uv run ruff check .` succeed with no findings.
- [ ] `uv run basedpyright` succeeds in strict mode with no errors.
- [ ] `uv run pytest` succeeds, including new unit and component suites.
- [ ] Every legal Section 9 transition is covered by a passing test with the correct resulting state, revision, and appended history entry.
- [ ] Every illegal transition (including from a terminal state) raises a stable domain exception and appends no history.
- [ ] `AcceptedRequestKey` and `AcceptanceEvidence` are immutable (frozen dataclasses); mutation attempts raise.
- [ ] The fingerprint-comparison function returns the correct outcome (`NEW`, `EQUIVALENT_REPLAY`, `FINGERPRINT_CONFLICT`) for representative cases from the Section 6 table.
- [ ] Every persistence port is a `Protocol` with no concrete database/transport dependency, and each has at least one in-memory fake proving it is implementable and behaviorally correct for its documented capability.
- [ ] No domain module imports `src/ai_platform/adapters/*`.
- [ ] `docs/sprint-2/done.md` and PROJECT_BRIEF.md Sections 7-8 are updated before merge.

## What's NOT in This Sprint

| Feature | Reason |
|---------|--------|
| Orchestrator process, Capability Registry (Phase 3) | Domain code only this sprint; no coordinating process |
| Test Agent implementation (Phase 4) | Depends on ports, not the other way around |
| Workflow API implementation (Phase 5) | API maps domain outcomes to HTTP; deferred |
| PostgreSQL/Redpanda adapters (Phase 6) | Ports are interfaces only; concrete adapters come later |
| Deadline reconciler process | A Phase 3 process concern; the aggregate only enforces terminal-state exclusivity (see consilium disagreement 1) |
| Mapping fingerprint/replay outcomes to HTTP status codes | API contract behavior (Phase 5), not domain logic (see consilium disagreement 2) |

## Agent Prompt

> Read `PROJECT_BRIEF.md`, then read `docs/sprint-2/plan.md` and
> `docs/sprint-2/consilium.md`. Execute Sprint 2, Phase 2 of
> [vertical-slice-01.md](../implementation/vertical-slice-01.md) only.
>
> First: `git pull origin main && git checkout -b feature/sprint-2-domain-and-persistence-ports`
>
> Update `docs/sprint-2/progress.md` after each phase (A/B/C above).
> When done, push and create a PR following `CONTRIBUTING.md` and
> Sections 12-14 of `PROJECT_BRIEF.md`. Do not implement any Phase 3+ behavior
> or any concrete persistence/transport adapter.
