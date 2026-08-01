# Sprint 3 — Orchestrator and Capability Registry

> Sprint Goal: Implement Vertical Slice 01, Phase 3 in full: configuration-
> backed Capability Registry (loading, compatibility, bounded readiness,
> exactly-one selection), submission-transaction orchestration, terminal
> event processing, deadline reconciliation, and one recovery query
> capability — all as pure Python application services composed over the
> Phase 2 `Protocol` ports. No real database/Kafka adapters (Phase 6).
> Branch: `feature/sprint-3-orchestrator-and-registry`
> Scope authority: [Vertical Slice 01, Section 20, Phase 3](../implementation/vertical-slice-01.md#20-implementation-phases)
> See also: [Sprint 3 team consilium](consilium.md)

## Parallelization Plan

This sprint splits into two independent work streams running concurrently:

- **Background sub-agent (Dash):** the Capability Registry module
  (`src/ai_platform/orchestrator/registry/`), built against the fixed
  interface spec below. Depends only on Sprint 2's `SelectionIntent`.
- **Main thread (Sage/Remy):** the Orchestrator application services
  (`src/ai_platform/orchestrator/application/`), built against the same
  fixed interface spec, composed over the Phase 2 persistence ports.

Integration and end-to-end component tests happen once both land.

### Registry Interface Spec (fixed up front for parallel work)

```python
# src/ai_platform/orchestrator/registry/declarations.py
@dataclass(frozen=True, slots=True)
class CapabilityBinding:
    capability_name: str
    capability_version: str
    command_contract_name: str
    command_contract_versions: tuple[str, ...]
    event_contract_names: tuple[str, ...]
    event_contract_versions: tuple[str, ...]
    agent_id: AgentId
    implementation_identity: str
    implementation_version: str
    deployment_declaration_digest: str
    environment: str
    enabled: bool


# src/ai_platform/orchestrator/registry/snapshot.py
class RegistryValidationError(Exception): ...


@dataclass(frozen=True, slots=True)
class RegistrySnapshot:
    revision: str
    bindings: tuple[CapabilityBinding, ...]


def load_registry_snapshot(
    raw_bindings: Sequence[CapabilityBinding], *, revision: str
) -> RegistrySnapshot:
    """Validates and rejects duplicates/conflicts (ADR-0008 Section 2, 7).
    Duplicate (agent_id, capability_name, capability_version, environment)
    is a RegistryValidationError."""


# src/ai_platform/orchestrator/registry/availability.py
class AvailabilityClassification(Enum):
    READY = "READY"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    UNAVAILABLE = "UNAVAILABLE"
    DRAINING = "DRAINING"


@dataclass(frozen=True, slots=True)
class AvailabilityObservation:
    classification: AvailabilityClassification
    observed_at: datetime
    ttl_seconds: float


class AvailabilityPort(Protocol):
    def observe(
        self, agent_id: AgentId, capability_name: str, capability_version: str
    ) -> AvailabilityObservation: ...


def is_fresh(observation: AvailabilityObservation, *, now: datetime) -> bool: ...


# src/ai_platform/orchestrator/registry/selection.py
class NoEligibleAgentError(Exception): ...


class AmbiguousCandidateError(Exception): ...


def select_candidate(
    snapshot: RegistrySnapshot,
    *,
    capability_name: str,
    capability_version: str,
    command_contract_name: str,
    command_contract_version: str,
    event_contract_names: tuple[str, ...],
    event_contract_versions: tuple[str, ...],
    environment: str,
    availability_port: AvailabilityPort,
    now: datetime,
    selection_policy_version: str,
) -> SelectionIntent:
    """Zero eligible -> NoEligibleAgentError. More than one eligible -> a
    configuration error (AmbiguousCandidateError), per Section 7: 'more than
    one is a configuration error in this slice.' `now` is always an
    explicit parameter (see consilium disagreement 2)."""
```

## Prioritized Task List

| # | Task | Owner | Description |
|---|------|-------|-------------|
| 1 | Capability Registry module | Dash (background sub-agent) | `declarations.py`, `snapshot.py` (+ validation/conflict rejection), `availability.py` (+ freshness classification), `selection.py` (+ `select_candidate`), per ADR-0008 and the interface spec above |
| 2 | Registry unit tests | Dash (background sub-agent) | Duplicate/conflict rejection, disabled deployments, stale/unknown/unavailable readiness, zero-eligible and multiple-eligible (ambiguous) candidates, exact contract-version matching |
| 3 | Nonterminal-workflow recovery port | Sage | `NonterminalWorkflowQueryPort` in `ports/persistence/`: returns `DISPATCHED` task attempts whose `task_result_deadline` has elapsed as of `now` (see consilium disagreement 1) |
| 4 | Submission orchestration service | Sage | `SubmissionOrchestrator` in `orchestrator/application/submission.py`: accepted-request arbitration first (Section 6), Registry selection only for genuinely new requests, atomic construction of workflow/task/attempt/history/outbox/audit via ports (Section 11) |
| 5 | Terminal event processing service | Sage | `TerminalEventProcessor` in `orchestrator/application/terminal.py`: inbox-disposition-first idempotency, then `complete`/`fail` via the Workflow aggregate, persisted via ports (Section 11 "Result-Consumption Transaction") |
| 6 | Deadline reconciliation service | Sage | `DeadlineReconciler` in `orchestrator/application/deadline.py`: uses the recovery port to find expired `DISPATCHED` attempts and applies `workflow.fail(..., cause="deadline_expired")`, relying on the aggregate's existing terminal-exclusivity guarantee for the race against a genuine outcome |
| 7 | Application-service component tests | Ivy | `tests/component/orchestrator/test_application_services.py` — first acceptance, equivalent replay (bypasses readiness), fingerprint conflict, terminal idempotency (duplicate/late delivery), and deadline-reconciler-vs-real-outcome race, all via in-memory fakes |
| 8 | Integration of Registry + application services | Sage | Once task 1 lands: wire `select_candidate` into `SubmissionOrchestrator`; add one end-to-end in-memory test exercising accept -> select -> dispatch -> complete |
| 9 | Sprint coordination | Remy | Keep scope to Phase 3 only; no real adapters, no Workflow API, no Test Agent |

## Work Schedule

### Phase A: Parallel Build (tasks 1-6 concurrently)
- Background sub-agent builds and tests the Registry module independently.
- Main thread builds the recovery port and all three application services against the fixed interface spec, using a local stand-in for the Registry's `select_candidate` signature until the sub-agent's module lands.
- Checkpoint commit (main thread): `sprint-3: add orchestrator application services`.
- Checkpoint commit (sub-agent output, reviewed and merged by main thread): `sprint-3: add capability registry module`.

### Phase B: Integration and Tests (tasks 7-8)
- Replace the stand-in with the real Registry module; run and add end-to-end in-memory tests.
- Checkpoint commit: `sprint-3: integrate registry with submission orchestrator`.

### Phase C: Sign-off (task 9)
- QA sign-off (`docs/qa/sprint-3-signoff.md`).
- Final commit and PR.

## Success Criteria

- [ ] `uv run ruff format --check .` and `uv run ruff check .` succeed with no findings.
- [ ] `uv run basedpyright` succeeds in strict mode with no errors.
- [ ] `uv run pytest` succeeds, including new Registry, application-service, and integration tests.
- [ ] `load_registry_snapshot` rejects duplicate/conflicting declarations with a stable error.
- [ ] `select_candidate` returns a `SelectionIntent` for exactly one eligible candidate, raises `NoEligibleAgentError` for zero, and raises `AmbiguousCandidateError` for more than one.
- [ ] `SubmissionOrchestrator` never checks Registry/Agent readiness for an equivalent replay, and never creates a second workflow for a concurrently-resolved key.
- [ ] `TerminalEventProcessor` returns the same disposition for a redelivered message without appending a second transition.
- [ ] `DeadlineReconciler` never overrides an already-terminal workflow (proven via the Sprint 2 aggregate's `TerminalWorkflowError`).
- [ ] No module under `orchestrator/` or `registry/` imports `adapters/*`.
- [ ] `docs/sprint-3/done.md` and PROJECT_BRIEF.md Sections 6-8 are updated before merge.

## What's NOT in This Sprint

| Feature | Reason |
|---------|--------|
| Test Agent implementation (Phase 4) | Consumes `ExecuteTask`; not built yet |
| Workflow API implementation (Phase 5) | Maps orchestrator outcomes to HTTP; deferred |
| PostgreSQL/Redpanda adapters (Phase 6) | Ports remain interfaces; no real transaction/broker behavior |
| Full outbox/inbox recovery-query capabilities (not-attempted, unknown, claimed-expired) | Depend on concrete adapter claim mechanics (Phase 6); only the narrow deadline-reconciliation query is in scope (see consilium disagreement 1) |
| Dynamic Agent registration or heartbeat | Explicitly deferred by ADR-0008 for the whole vertical slice |

## Agent Prompt

> Read `PROJECT_BRIEF.md`, then read `docs/sprint-3/plan.md` and
> `docs/sprint-3/consilium.md`. Execute Sprint 3, Phase 3 of
> [vertical-slice-01.md](../implementation/vertical-slice-01.md) only.
>
> First: `git pull origin main && git checkout -b feature/sprint-3-orchestrator-and-registry`
>
> Update `docs/sprint-3/progress.md` after each phase (A/B/C above).
> When done, push and create a PR following `CONTRIBUTING.md` and
> Sections 12-14 of `PROJECT_BRIEF.md`. Do not implement any Phase 4+
> behavior or any concrete persistence/transport adapter.
