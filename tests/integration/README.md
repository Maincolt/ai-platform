# Integration Tests (External-Service)

Tests in this directory are **external-service tests** as defined by
[docs/testing/README.md](../../docs/testing/README.md): they talk to real,
locally isolated PostgreSQL and Apache Kafka instances rather than fakes or
in-process substitutes. They are opt-in and excluded from the default
`uv run pytest` run.

## Running

```bash
uv run pytest -m external_service tests/integration/ -v
```

The default `uv run pytest` invocation (no `-m`) never collects-and-runs these
tests for real work: `pyproject.toml` sets
`addopts = "-ra -m \"not external_service\""`, so the fast local suite stays
offline and deterministic.

### If the host-published ports are unreliable (Windows/WSL2)

On some Windows/WSL2 + Podman hosts, `localhost:5433`/`localhost:19093` can
accept a bare TCP connection while still failing to reliably relay actual
protocol traffic — a bare `socket.connect()` succeeds, but `psycopg`'s
connection handshake or Kafka's SASL exchange hangs and times out. This can
happen regardless of whether WSL2's automatic localhost forwarding or an
explicit `netsh interface portproxy` rule is in front of it; the underlying
double-hop relay (Windows → WSL2 → Podman's own container NAT) is not always
reliable for anything beyond the initial handshake.

If `uv run pytest -m external_service` reports every test skipped with a
connection-timeout reason even though `podman ps` shows the services
healthy, run the suite from inside a throwaway container on the compose
network instead — this talks to PostgreSQL/Kafka by internal service name
(`postgres:5432`, `kafka:9092`) and never crosses the Windows/WSL boundary:

```bash
bash tests/integration/run-in-network.sh
# or, to pass pytest args through:
bash tests/integration/run-in-network.sh tests/integration/test_smoke.py -v
```

This requires the `infrastructure/compose/` topology already running and
its secrets already generated (see
[infrastructure/README.md](../../infrastructure/README.md)); it builds a
disposable virtual environment inside the container each run (`uv sync
--locked` against a `/tmp/venv` that never touches the host's own
`.venv/`), so the first run is slower than subsequent ones.

The `AI_PLATFORM_TEST_POSTGRES_HOST`, `AI_PLATFORM_TEST_POSTGRES_PORT`,
`AI_PLATFORM_TEST_KAFKA_BOOTSTRAP_SERVERS`, and
`AI_PLATFORM_TEST_SKIP_COMPOSE_UP` environment variables that make this
possible are read directly by `conftest.py`.

### `test_recovery.py` needs the opposite: run it directly on the host

`test_recovery.py` is the one file that does **not** work through
`run-in-network.sh`. It exercises the real `platform`/`test-agent`
application containers (kill, restart, `podman exec` for HTTP calls and
`psql` queries), so it needs the `podman` CLI itself — which the minimal
container `run-in-network.sh` uses does not have. Run it directly:

```bash
uv run pytest -m external_service tests/integration/test_recovery.py -v
```

This works even on hosts where the *other* files' host-forwarded-port path
is unreliable, because `test_recovery.py` never makes a direct TCP
connection to a published port — everything goes through `podman exec`.
It requires the `platform`/`test-agent` containers already running (see
[infrastructure/README.md](../../infrastructure/README.md)'s "Running the
application against the topology"); if they aren't, its tests skip with a
clear reason rather than failing. It also skips cleanly (rather than
erroring) if run where `podman` itself isn't on `PATH`, e.g. inside
`run-in-network.sh`'s container.

Because it kills and restarts the shared application containers, don't run
it concurrently with anything else exercising that same topology.

In short, on a host with the flaky Windows/WSL2 port-forwarding path: run
everything **except** `test_recovery.py` via `run-in-network.sh`, and run
`test_recovery.py` directly. There is currently no single command that
runs the complete `external_service` suite correctly on such a host in one
shot.

## What these tests need

The `infrastructure/compose/` topology from Sprint 6 (see
[infrastructure/README.md](../../infrastructure/README.md)) must be
reachable:

- PostgreSQL 17 on `localhost:5433`, database `ai_platform`.
- Apache Kafka 3.9 (KRaft) on `localhost:19093`, the `EXTERNAL` SASL_PLAINTEXT
  / SCRAM-SHA-256 listener.

`tests/integration/conftest.py` provides session-scoped fixtures that:

1. Check whether Podman is available and the compose services are already
   reachable.
2. If not reachable, attempt to bring them up automatically
   (`podman compose up -d postgres kafka` from `infrastructure/compose/`),
   generating secrets first via `scripts/generate-secrets.sh` if
   `infrastructure/compose/secrets/` does not yet exist, then wait for both
   services to answer.
3. If the topology still cannot be reached after a bounded wait, every test
   under the `external_service` marker is **skipped** (not failed) with a
   message explaining what to run manually.
4. Never tear the topology down at the end of the session — it is the same
   shared local dev stack other Sprint 6/7 work depends on staying up, and
   Kafka's startup time makes repeated teardown/setup between test runs
   impractical.

## Fixtures

- `postgres_dsn` — a `postgresql://` DSN string using the `postgres`
  administrator credentials from `infrastructure/compose/secrets/`, pointed
  at `localhost:5433/ai_platform`.
- `postgres_connection` — a real `psycopg.Connection` opened against that DSN
  (one per test, closed afterward).
- `kafka_bootstrap_servers` — `localhost:19093`, the host-reachable `EXTERNAL`
  Kafka listener (see `infrastructure/compose/kafka/entrypoint.sh`).
- `kafka_admin_client_config` — a `confluent_kafka` client config `dict`
  (bootstrap servers + `SASL_PLAINTEXT`/`SCRAM-SHA-256` credentials) for the
  `admin` principal, provisioned by
  `infrastructure/compose/scripts/init-kafka.sh`.
- `kafka_admin_client` — a `confluent_kafka.admin.AdminClient` built from the
  config above.

These are scaffolding only. The actual Section 19/20 external-service test
scenarios (Phase 7 of `docs/implementation/vertical-slice-01.md`) are built on
top of these fixtures in later work.
