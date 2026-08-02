# QA Sprint 6 Sign-Off

Date: 2026-08-02
Tester: Ivy (QA)

## Scope

Vertical Slice 01, Phase 6: concrete Psycopg 3 PostgreSQL adapters and
`confluent-kafka` Event Bus adapter, platform/Test Agent process
composition, the application Docker image, and the local PostgreSQL +
Apache Kafka Compose deployment topology. See
[docs/sprint-6/done.md](../sprint-6/done.md) for the complete account and
[docs/sprint-6/progress.md](../sprint-6/progress.md) for exact commands and
raw validation output.

## Test Results

- Tests run: 339 (offline unit/component suite; no live PostgreSQL/Kafka
  required at this level per [docs/testing/README.md](../testing/README.md))
- Tests passed: 339
- Tests failed: 0

Command: `uv run pytest -q`

## Tooling Verification

- `uv run ruff format --check .` — no reformatting needed.
- `uv run ruff check .` — all checks passed.
- `uv run basedpyright` (strict mode) — 0 errors, 0 warnings, 0 notes.

## Real-Service Verification

Exercised against a real, Podman-managed local PostgreSQL 17 and Apache
Kafka 3.9 (KRaft) topology — not mocks, not simulated:

- **Migrations/roles:** both component migrations applied through
  dedicated, `SET ROLE`-gated migrator logins; schema/table ownership
  confirmed isolated per component (`orchestrator` vs. `agent`).
- **Topics/ACLs:** all four ADR-0005 topics created; least-privilege ACLs
  confirmed both directions — `orchestrator-producer` can write
  `task-commands` and is denied (`TopicAuthorizationException`) writing
  `task-outcomes`.
- **End-to-end submission:** `POST /api/v1/workflows` through to
  `GET .../{id}` returning `COMPLETED` with the correct `word_count`, via
  the real PostgreSQL outbox/inbox and Kafka `task-commands`/`task-outcomes`
  path (not the in-memory reference ports).
- **Agent-independent queries:** workflow reads succeed independent of
  Agent readiness.
- **Crash recovery:** Test Agent killed mid-flight recovered via Kafka
  offset redelivery with no duplicate receipt/outcome. Platform killed
  after dispatch: Agent completed and published its outcome independently;
  the delayed outcome correctly triggered both `DeadlineReconciler`
  (`TASK_RESULT_DEADLINE_EXCEEDED`) and, on the outcome consumer catching
  up, a correctly rejected late terminal event (`late_after_terminal`,
  terminal state not overwritten).
- **Assignment fencing:** two Test Agent replicas sharing one consumer
  group split the topic's partitions with no overlap; killing one replica
  correctly rebalanced its partitions onto the survivor, which continued
  processing correctly afterward.
- **Quarantine:** malformed and schema-invalid messages correctly
  quarantined with `CONFIRMED` disposition.

## Behavior Coverage

- Submission, terminal-outcome, deadline, access-audit, inbox/outbox, and
  recovery transaction boundaries (unit + component, from the existing
  Phase 2–5 suites plus new Phase 6 adapter/runtime coverage).
- Kafka adapter capability boundary: exact byte/identity preservation,
  keyed partitioning, manual offset commit, quarantine classification, and
  startup reconciliation (unit, in-memory transport) — confirmed against a
  real broker as above.
- Runtime configuration validation (secret-file references, loopback-only
  host/URL enforcement, bounded numeric ranges) and process lifecycle
  (startup gates, graceful shutdown).

## Blockers

NONE

## Issues Filed

None new. Two items are explicitly deferred, not silently dropped:

- How runtime/deployment readiness proves the required Kafka producer,
  consumer-group, and quarantine *authorization* (not just broker
  reachability) remains an open architectural question — see
  [docs/sprint-6/progress.md](../sprint-6/progress.md), "Remaining Sprint 6
  work." Not a blocker for this sprint's declared scope.
- Deliberate, operator-initiated quarantine replay was not exercised
  (quarantine itself was, incidentally and repeatedly, during ACL and
  recovery testing). Out of this sprint's declared scope per
  [docs/sprint-6/plan.md](../sprint-6/plan.md).

## Result

✅ PASS — No blockers. Sprint 6 (Phase 6) is ready to merge. Phase 7
(integration/recovery/security/end-to-end suites) and Phase 8 (operational
documentation) remain explicitly out of scope for this sprint and have not
started.
