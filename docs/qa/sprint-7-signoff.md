# QA Sprint 7 Sign-Off

Date: 2026-08-04
Tester: Ivy (QA)

## Scope

Vertical Slice 01, Phase 7 (partial, explicitly scoped — see
[docs/sprint-7/plan.md](../sprint-7/plan.md)): an automated
`external_service` pytest suite covering Event Bus delivery, Concurrency,
Security boundary, and Recovery/crash window against the real
`infrastructure/compose/` PostgreSQL + Apache Kafka topology from Sprint 6.
See [docs/sprint-7/done.md](../sprint-7/done.md) for the complete account
and [docs/sprint-7/progress.md](../sprint-7/progress.md) for exact
commands and the host-networking investigation.

## Test Results

- Local suite: 339 passed, 49 deselected (`uv run pytest -q`) — unaffected
  by this sprint.
- External-service suite: 49 passed across two required run paths (see
  below) — 0 failed.

Commands: `uv run pytest -q`; `bash tests/integration/run-in-network.sh -v`;
`uv run pytest -m external_service tests/integration/test_recovery.py -v`.

## Tooling Verification

- `uv run ruff format --check .` — no reformatting needed.
- `uv run ruff check .` — all checks passed.
- `uv run basedpyright` (strict mode) — 0 errors, 0 warnings, 0 notes.

## Real-Service Verification

Exercised against the real, Podman-managed local PostgreSQL 17 and Apache
Kafka 3.9 (KRaft) topology:

- **Event Bus delivery**: keyed ordering, manual acknowledgment/at-least-once
  redelivery, and malformed-payload quarantine through the real runtime
  pipeline (validator + quarantine coordinator + Kafka adapter).
- **Concurrency**: duplicate command execution and duplicate terminal
  outcome each produce exactly one durable effect; a deadline race produces
  exactly one terminal winner, using the real database's transaction
  serialization.
- **Security boundary**: PostgreSQL role isolation confirmed by connecting
  as the real `_app` logins and observing real `InsufficientPrivilege`
  errors on cross-schema access and on DDL; a 23-case Kafka ACL matrix
  across all four principals confirms real `TOPIC_AUTHORIZATION_FAILED`/
  `GROUP_AUTHORIZATION_FAILED` denial outside each principal's allow-list;
  secret redaction confirmed against real credential material; a forced
  audit-write failure confirmed to roll back the entire submission
  transaction, with the revoked grant independently verified restored
  afterward.
- **Recovery/crash window**: Test Agent killed mid-flight recovers via
  Kafka redelivery with no duplicate receipt/outcome (run twice, passed
  both times); platform killed after dispatch recovers the backlogged
  outcome, with the test correctly handling both sides of the genuine
  deadline-vs-recovery-speed race observed across repeated runs.

## Behavior Coverage

- Real-broker-backed coverage of guarantees previously proven only by
  in-memory unit tests or one-off manual sessions: message ordering,
  redelivery, quarantine, idempotent duplicate handling, deadline races,
  database role/privilege boundaries, Kafka ACL boundaries, and process
  crash recovery.
- A genuine, reproducible host-networking failure mode (Windows/WSL2/Podman
  port-forwarding unreliability) was diagnosed, worked around with a
  documented dual run path, and left as a permanent, tested capability
  (`tests/integration/run-in-network.sh`) rather than a one-time fix.

## Blockers

NONE

## Issues Filed

None new. Carried forward from Sprint 6, still open and out of this
sprint's scope: the Kafka producer/consumer-group/quarantine
*authorization*-proof design question for deployment readiness. New items
explicitly deferred rather than silently dropped: the remaining Section 19
categories not automated this sprint (see
[docs/sprint-7/plan.md](../sprint-7/plan.md)'s "Out of scope"), a dedicated
pytest-automated full-container end-to-end harness, and deliberate
quarantine replay.

## Result

✅ PASS — No blockers. Sprint 7 (Phase 7, scoped subset) is ready to merge.
The remainder of Phase 7's Section 19 matrix and Phase 8 operational
documentation remain explicitly out of scope for this sprint and have not
started.
