# Sprint 7 — Done

> Scope: Vertical Slice 01, Phase 7 (integration, recovery, security, and
> end-to-end tests)
> Branch: `feature/sprint-7-integration-recovery-security-e2e`
> Completed: 2026-08-04

## What was built

An automated, opt-in `external_service` pytest suite (49 tests across five
files under `tests/integration/`) that exercises Sprint 6's real
PostgreSQL + Apache Kafka topology directly — not mocks, not in-memory
fakes — turning a substantial part of Sprint 6's manual real-service
validation into repeatable, CI-shaped coverage:

- **Infrastructure** (`conftest.py`, `pyproject.toml`'s `external_service`
  marker, `run-in-network.sh`): reaches the real topology, skips cleanly
  with a clear reason when it can't, and supports running from inside a
  container on the compose network as a documented fallback for hosts
  where direct host-port connections are unreliable.
- **Event Bus delivery** (`test_event_bus_delivery.py`): keyed ordering,
  manual acknowledgment/redelivery, malformed-message quarantine through
  the real runtime pipeline.
- **Concurrency** (`test_concurrency.py`): duplicate command/result
  idempotency, deadline race — against the real database's actual
  transaction serialization.
- **Security boundary** (`test_postgres_role_isolation.py`,
  `test_kafka_acl_matrix.py`, `test_secret_redaction.py`,
  `test_audit_failure_rollback.py`): PostgreSQL cross-schema isolation and
  migration/runtime privilege separation, a full Kafka ACL matrix (23
  cases), secret redaction, and audit-failure transaction rollback.
- **Recovery/crash window** (`test_recovery.py`): Test Agent and platform
  container crash-recovery, driven through `podman exec` against the real
  application containers (the platform's API is intentionally
  loopback-only, so this is the only way to reach it from outside the
  container).

## What was validated, for real

See [progress.md](progress.md) for the full account, including a detailed
record of a genuine multi-layered Windows/WSL2/Podman host-networking
problem encountered and resolved during this sprint (stale NAT rules, the
WSL2 Hyper-V Firewall, and a still-unexplained direct-connection
reliability gap that led to the container-network fallback becoming a
first-class, documented way to run this suite).

Full-suite result, confirming complete coverage across the two required
run paths:

- `bash tests/integration/run-in-network.sh -v`: 47 passed, 2 skipped
  (by design — see below).
- `uv run pytest -m external_service tests/integration/test_recovery.py -v`:
  2 passed.

`test_recovery.py` needs the `podman` CLI directly (it drives the real
containers) and cannot run inside `run-in-network.sh`'s container sandbox;
every other file needs the opposite path on hosts where direct
host-forwarded-port connections are unreliable. Both paths are documented
in `tests/integration/README.md`.

## Quality gates

All four local acceptance gates from [plan.md](plan.md) pass:

- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run basedpyright` (strict)
- `uv run pytest -q` — 339 passed, 49 deselected (unaffected; the new
  suite is opt-in and excluded by default)

## What needed manual setup

- Same prerequisites as Sprint 6: `infrastructure/compose/scripts/generate-secrets.sh`
  and `generate-app-secrets.sh` must have been run once.
- The application image (`ai-platform:sprint6`) and the `platform`/
  `test-agent` containers must be running for `test_recovery.py` (see
  `infrastructure/README.md`).
- On hosts where the Windows/WSL2 host-forwarded-port path is unreliable,
  running the DB/Kafka-direct tests requires
  `tests/integration/run-in-network.sh` instead of the plain
  `uv run pytest -m external_service` invocation. This is a genuine,
  documented environment characteristic of this specific development
  host, not something the test suite itself can paper over.

## What's not done / explicitly out of scope

Per [plan.md](plan.md)'s declared "Explicitly out of scope for this
sprint" and reiterated in [progress.md](progress.md): the remaining
Section 19 test categories not automated this sprint (Contract,
Idempotency's full fingerprint/replay matrix, Ownership/disclosure, State
machine, Agent selection/readiness, most of Audit/observability), the full
Correlation Normalization Scenarios table, a dedicated pytest-automated
full-container End-to-End harness, the Kafka producer/consumer-group/
quarantine authorization-proof design question (still open, flagged in
Sprint 6), deliberate quarantine replay, Phase 8 operational
documentation, and anything production-facing (auth, HA, Kubernetes,
managed services, AI Router, model execution).

## Files changed / created

`tests/integration/` gained `conftest.py` (extended with host/port
overrides), `run-in-network.sh`, `test_smoke.py`, `test_event_bus_delivery.py`,
`test_concurrency.py`, `test_postgres_role_isolation.py`,
`test_kafka_acl_matrix.py`, `test_secret_redaction.py`,
`test_audit_failure_rollback.py`, `test_recovery.py`, and `README.md`.
`pyproject.toml` registers the `external_service` marker. See the pull
request diff for the complete list.
