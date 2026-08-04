# Sprint 7 Progress — Integration, Recovery, Security, and End-to-End Tests

> Status: Done
> Updated: 2026-08-04
> Scope: Vertical Slice 01, Phase 7 (see [plan.md](plan.md) for exact scope)

## Summary

Sprint 6 validated a substantial amount of Phase 7's required behavior
manually against real services. Sprint 7 turned that into an automated,
repeatable `external_service`-marked pytest suite: 49 new tests across five
files under `tests/integration/`, all passing against the real, isolated
`infrastructure/compose/` PostgreSQL + Apache Kafka topology — not mocks.

## Infrastructure: the `external_service` pytest marker and fixtures

- `pyproject.toml`: registered the `external_service` marker; default
  `addopts` excludes it (`-m "not external_service"`), so `uv run pytest`
  stays offline and fast (339 passed, 49 deselected).
- `tests/integration/conftest.py`: session-scoped fixtures that bring up
  (or reuse) the real topology, generating secrets if needed, and skip
  every test in the directory with a clear reason if it can't be reached —
  never a confusing failure deep inside a test body.

## A genuine host-networking problem, and how it was resolved

Early in this sprint, every `external_service` test reported skipped with
a PostgreSQL/Kafka connection-timeout reason even though `podman ps` showed
both containers healthy. This took substantial diagnosis across this
session (see the conversation history for the full blow-by-blow) and
turned out to be layered:

1. **Stale/duplicate NAT rules.** `nftables` inside the Podman machine had
   duplicate `DNAT` rules for the same ports pointing at different (some
   defunct) container IPs, left over from earlier container recreations.
   First-match-wins meant traffic sometimes routed to the wrong container
   entirely. Fixed by fully removing and recreating the containers/network
   so netavark regenerated clean rules.
2. **The Windows WSL2 Hyper-V Firewall.** A newer Windows networking
   feature that filters WSL VM traffic at the Windows Firewall layer,
   silently dropping forwarded container ports even when everything inside
   the WSL VM is correct. Diagnosed by confirming the port was reachable
   from *inside* the VM (`podman machine ssh`) but not from Windows, and by
   a systemic test with a disposable `nginx` container on an unused port.
   The user resolved this on the host with `netsh interface portproxy` +
   an explicit `netsh advfirewall` allow rule.
3. **A deeper, still-unresolved reliability gap.** Even after both fixes,
   direct connections from Windows-native Python (`psycopg`,
   raw `socket.connect()` + payload) are **inconsistent**: a bare TCP
   connect can succeed instantly while the actual protocol handshake (e.g.
   PostgreSQL's SSL negotiation) hangs and times out. This is not fully
   understood and is documented as a known limitation rather than papered
   over — see `tests/integration/README.md`.

**The durable fix** was architectural, not another network tweak:
`tests/integration/conftest.py`'s connection targets became overridable
via `AI_PLATFORM_TEST_POSTGRES_HOST`/`_PORT`/`AI_PLATFORM_TEST_KAFKA_BOOTSTRAP_SERVERS`/
`AI_PLATFORM_TEST_SKIP_COMPOSE_UP`, and `tests/integration/run-in-network.sh`
runs the suite from inside a throwaway container on the compose network,
talking to PostgreSQL/Kafka by internal service name
(`postgres:5432`/`kafka:9092`) — sidestepping the Windows/WSL boundary
entirely. This is also arguably the *more correct* way to run isolated
external-service tests regardless of host quirks.

`test_recovery.py` is the one exception: it drives the real
`platform`/`test-agent` containers via `podman exec` (kill, restart, HTTP
calls, `psql` queries), so it needs the `podman` CLI itself, which
`run-in-network.sh`'s minimal container doesn't have. It runs directly on
the host instead — and works reliably there because it never makes a
direct TCP connection to a host-published port. See
`tests/integration/README.md` for the exact two-command split this
produces.

**Verified full-suite result**, confirming both paths together produce
complete coverage with no silent gaps:

- `bash tests/integration/run-in-network.sh -v`: 47 passed, 2 skipped
  (the 2 are `test_recovery.py`, skipped cleanly because `podman` isn't
  available inside that container — the intended behavior).
- `uv run pytest -m external_service tests/integration/test_recovery.py -v`
  (direct on host): 2 passed.
- `uv run pytest -m external_service tests/integration/ -v` (direct on
  host, for completeness): 2 passed (`test_recovery.py`), 47 skipped
  (the direct-connection tests, on this host — expected, use
  `run-in-network.sh` for those).

## Event Bus delivery and Concurrency (`test_event_bus_delivery.py`, `test_concurrency.py`)

Against the real broker/database, using the real adapter code
(`KafkaEventPublisher`/`KafkaEventConsumer`, `PsycopgOrchestratorPersistence`/
`PsycopgAgentPersistence`), not the mocked/in-memory unit-test transports:

- Keyed ordering is preserved for messages sharing a `workflow_id`.
- Manual acknowledgment: an uncommitted message (simulated crash before
  commit) is redelivered to a fresh consumer in the same group.
- A malformed payload is correctly quarantined through the real runtime
  pipeline (validator + quarantine coordinator + Kafka adapter wired
  exactly as `runtime/composition.py` wires them).
- Duplicate command delivery produces exactly one Agent receipt.
- Duplicate terminal-outcome delivery produces exactly one transition.
- A deadline-race (near-simultaneous terminal-outcome and deadline-expiry
  transactions) produces exactly one terminal winner, using the real
  database's transaction serialization.

## Security boundary (`test_postgres_role_isolation.py`, `test_kafka_acl_matrix.py`, `test_secret_redaction.py`, `test_audit_failure_rollback.py`)

- **PostgreSQL role isolation**: the real `ai_platform_orchestrator_app`/
  `ai_platform_agent_app` logins are confirmed denied cross-schema access;
  runtime (`_app`) logins are confirmed denied DDL, which only migrator
  logins can perform (and only after `SET ROLE`).
- **Kafka ACL matrix**: a parametrized 23-case matrix across all four
  provisioned principals and every topic/consumer-group from
  `init-kafka.sh`, confirming each principal is denied everything outside
  its documented allow-list (not just the one pair Sprint 6 proved by
  hand) via real `TOPIC_AUTHORIZATION_FAILED`/`GROUP_AUTHORIZATION_FAILED`
  errors.
- **Secret redaction**: a real `KafkaSecurityConfig` built from real
  credential files never leaks the password/username through `repr()`/
  `str()`, including inside a raised `KafkaSecurityConfigurationError`.
- **Audit-failure rollback**: `INSERT` on `orchestrator.audit` is
  temporarily revoked from the runtime role (restored in a `finally`
  fixture teardown, independently verified restored afterward), a real
  `commit_submission` call is driven through the real app login, and the
  entire integrity unit (workflow/task/outbox/audit) is confirmed rolled
  back together — not just the audit table.

## Recovery/crash window (`test_recovery.py`)

Drives the real `platform`/`test-agent` application containers, not just
the adapters:

- **Test Agent killed mid-flight**: `SIGKILL` before it can commit a Kafka
  offset; restarting it redelivers the uncommitted message and completes
  the workflow with exactly one receipt/outcome — no duplicate.
- **Platform killed after dispatch**: `SIGKILL` immediately after dispatch;
  the Agent keeps working and publishes its outcome independently. The
  container-recreation recovery this requires (`test-agent`'s
  `network_mode: "service:platform"` is tied to the platform container's
  specific instantiation — restarting it breaks the Agent's networking
  until it's recreated, an operational gotcha first found in Sprint 6) is
  slow enough that whether the platform beats `task_result_deadline` is a
  genuine race, confirmed by running the test twice and observing both
  outcomes land validly. Rather than assert one specific timing-dependent
  result, the test asserts the invariant that holds either way: a
  deterministic terminal state, exactly one Agent outcome, and — if the
  deadline wins — the late outcome safely recorded as `late_after_terminal`
  rather than corrupting the terminal state.

## What's deferred (see plan.md's "Out of scope")

- The remaining Section 19 categories not automated this sprint: Contract,
  Persistence/transaction beyond what Concurrency/Recovery exercise,
  Idempotency (fingerprint/replay matrix — covered at the API/component
  level already), Ownership/disclosure, Inbox/outbox beyond Recovery,
  State machine, Agent selection/readiness, Audit/observability beyond the
  one scenario above.
- The full Correlation Normalization Scenarios table.
- A true End-to-End test running the complete containers under pytest
  automation (Sprint 6 and this sprint both drive them via `podman exec`
  for specific scenarios; a dedicated E2E harness is separate work).
- How runtime/deployment readiness proves Kafka producer/consumer-group/
  quarantine *authorization* (not just reachability) — still an open
  architectural question flagged in Sprint 6, unchanged.
- Deliberate, operator-initiated quarantine replay.
- Phase 8 operational documentation.
- Production authentication, high availability, Kubernetes, managed
  services, AI Router integration, model execution.
