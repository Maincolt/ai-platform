# Sprint 6 — Concrete Adapters and Local Deployment

> Sprint goal: implement Vertical Slice 01, Phase 6.  
> Branch: `feature/sprint-6-concrete-adapters`  
> Scope authority: [Vertical Slice 01, Section 20, Phase 6](../implementation/vertical-slice-01.md#20-implementation-phases)

## Workstreams

| # | Workstream | Deliverable | Status |
| --- | --- | --- | --- |
| 1 | Persistence boundaries | Async transaction ports and atomic Orchestrator/Agent units of work | Implemented; final gate pending |
| 2 | PostgreSQL | Psycopg 3 adapters, versioned migrations, separate schemas and least-privilege roles | Implemented; real database validation pending |
| 3 | Event Bus | Broker-neutral port, `confluent-kafka` adapter, exact bytes, manual progress, recovery and quarantine | Implemented; real broker validation pending |
| 4 | Runtime | Platform/Test Agent composition, publishers, consumers, readiness, health, lifecycle and shutdown | Implemented; final consumer review pending |
| 5 | Local deployment | Application image, PostgreSQL/Redpanda topology, topics, ACLs, secrets and health ordering | Application image only; owner/environment blocked |
| 6 | QA and handoff | Local quality gates, real-service smoke checks, accurate sprint/QA documentation | In progress |

## Execution order

1. Reconcile persistence and runtime behavior with Accepted ADRs and the
   Vertical Slice transaction/failure tables.
2. Implement and locally verify concrete adapters and process composition.
3. Complete the ADR-0005 Redpanda license review before adding or deploying
   Redpanda resources.
4. Provision the isolated local topology and broker/database security.
5. Run local deployment lifecycle and recovery checks.
6. Run the repository quality gates, record evidence, and mark the sprint done
   only if every Phase 6 requirement is met.

## Acceptance criteria

- [ ] `uv run ruff format --check .` succeeds.
- [ ] `uv run ruff check .` succeeds.
- [ ] `uv run basedpyright` succeeds in strict mode.
- [ ] `uv run pytest -q` succeeds.
- [ ] PostgreSQL migrations and least-privilege roles are exercised against an
      isolated real database.
- [ ] Kafka publication, consumption, manual progress, quarantine, recovery,
      assignment fencing and ACL boundaries are exercised against an isolated
      real broker.
- [ ] The Docker image and complete local topology build and start with
      protected, separate credentials and no non-loopback public exposure.
- [ ] Platform startup, Agent-independent queries, readiness, shutdown and
      restart recovery are demonstrated.
- [ ] Sprint completion and QA documents distinguish demonstrated behavior
      from limitations and make no production-readiness claim.

## Current blockers

See [progress.md](progress.md). The repository owner must approve the Redpanda
Community Edition license gate from ADR-0005, and an isolated container or
equivalent real-service environment must be available. These prerequisites
also gate Phase 7 and the demonstrated procedures required by Phase 8.

## Out of scope

- Phase 7 integration/recovery/security/end-to-end suites beyond the Phase 6
  deployment smoke checks.
- Phase 8 operational documentation.
- Production authentication, high availability, Kubernetes, managed services,
  AI Router integration, model execution, and irreversible external effects.
