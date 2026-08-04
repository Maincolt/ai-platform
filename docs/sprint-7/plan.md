# Sprint 7 — Integration, Recovery, Security, and End-to-End Tests

> Sprint goal: implement Vertical Slice 01, Phase 7.
> Branch: `feature/sprint-7-integration-recovery-security-e2e`
> Scope authority: [Vertical Slice 01, Section 19 and Section 20 Phase 7](../implementation/vertical-slice-01.md#19-testable-acceptance-criteria)

## Context

Sprint 6 delivered the concrete PostgreSQL/Kafka adapters and local
deployment topology, and validated a substantial amount of Phase 7's
required behavior **manually** against real services (end-to-end
submission, crash recovery of both processes, Kafka assignment fencing,
quarantine) — see [docs/sprint-6/progress.md](../sprint-6/progress.md).
Sprint 7's job is to turn the Section 19 acceptance matrix into an
automated, repeatable `external_service`-marked pytest suite that runs
against the real, isolated `infrastructure/compose/` topology, so this
coverage survives beyond one manual session.

## Scope

Section 19 lists thirteen test categories and ~25 critical scenarios. This
sprint automates a deliberately chosen high-value subset rather than every
row, consistent with this repo's pattern of explicit, documented scope
management (see `docs/sprint-6/plan.md`'s own "Out of scope" section).

**In scope:**

- Test infrastructure: an `external_service` pytest marker (opt-in,
  excluded from the default `uv run pytest` run) and `tests/integration/`
  fixtures that reach the real `infrastructure/compose/` PostgreSQL +
  Kafka topology.
- **Event Bus delivery**: keyed ordering, manual acknowledgment/at-least-once
  redelivery, malformed-message quarantine — against the real broker.
- **Concurrency**: duplicate command, duplicate result, deadline race —
  against the real database and broker.
- **Security boundary**: PostgreSQL role isolation and migration/runtime
  privilege separation, a full Kafka ACL matrix (not just the one pair
  Sprint 6 proved by hand), secret redaction, and audit-failure rollback —
  against real services.
- **Recovery/crash window**: automating the container-level crash scenarios
  Sprint 6 proved by hand (Test Agent killed mid-flight, platform killed
  after dispatch, the deadline-vs-late-outcome race) so they're repeatable.

**Explicitly out of scope for this sprint** (candidates for a future
sprint, not silently dropped):

- The remaining Section 19 categories not listed above: Contract,
  Persistence/transaction (beyond what Concurrency/Recovery already
  exercise), Idempotency (fingerprint/replay matrix — already covered at
  the API/component level per `docs/qa/sprint-5-signoff.md`), Ownership/
  disclosure, Inbox/outbox (beyond what Recovery exercises), State machine,
  Agent selection/readiness, and Audit/observability beyond the one
  audit-failure scenario listed above.
- The full Correlation Normalization Scenarios table (Section 19) — already
  substantially covered at the API/component level in Sprint 5.
- A true End-to-End test running the complete `platform`/`test-agent`
  Docker containers under pytest automation (Sprint 6 proved this by hand;
  automating the full container lifecycle under pytest is real additional
  work, not a natural extension of the database/broker-level tests here).
- Phase 8 operational documentation.
- Production authentication, high availability, Kubernetes, managed
  services, AI Router integration, model execution.

## Acceptance criteria

- [ ] `uv run ruff format --check .` succeeds.
- [ ] `uv run ruff check .` succeeds.
- [ ] `uv run basedpyright` succeeds in strict mode.
- [ ] `uv run pytest -q` succeeds and is unaffected (same pass count as
      before this sprint, `external_service`-marked tests excluded by
      default).
- [ ] `uv run pytest -m external_service` succeeds against the real local
      topology and covers the categories listed above.
- [ ] Sprint completion and QA documents distinguish demonstrated behavior
      from the explicitly deferred remainder and make no production-readiness
      claim.

## Out of scope

See "Explicitly out of scope for this sprint" above.
