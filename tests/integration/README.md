# Integration Tests (External-Service)

Tests in this directory are **external-service tests** as defined by
[docs/testing/README.md](../../docs/testing/README.md): they talk to real,
locally isolated PostgreSQL and Apache Kafka instances rather than fakes or
in-process substitutes. They are opt-in and excluded from the default
`uv run pytest` run.

## Running

The topology runs on a dedicated Docker host (a Mac at `192.168.1.123`, see
[infrastructure/README.md](../../infrastructure/README.md) Section 1), not
on whichever machine runs pytest. `conftest.py`'s
`AI_PLATFORM_TEST_POSTGRES_HOST`/`AI_PLATFORM_TEST_KAFKA_BOOTSTRAP_SERVERS`
default to that host's LAN address, so as long as the topology is up and
`infrastructure/compose/secrets/` is present on whichever machine runs
pytest (either run from an SSH session on the Docker host itself, where
both already live, or copy `secrets/` down to your own checkout), this
just works over the LAN:

```bash
uv run pytest -m external_service tests/integration/ -v
```

The default `uv run pytest` invocation (no `-m`) never collects-and-runs these
tests for real work: `pyproject.toml` sets
`addopts = "-ra -m \"not external_service\""`, so the fast local suite stays
offline and deterministic.

### Historical: the Windows/WSL2/Podman dual-run-path workaround (no longer needed)

Through Sprint 10, this topology ran on the developer's own Windows machine
via Podman Desktop's WSL2 integration, where `localhost:5433`/`localhost:19093`
could accept a bare TCP connection while still failing to reliably relay
actual protocol traffic — `psycopg`'s connection handshake or Kafka's SASL
exchange would hang and time out, regardless of whether WSL2's automatic
localhost forwarding or an explicit `netsh interface portproxy` rule was in
front of it. Working around it required two separate run paths:
`run-in-network.sh` (running the suite from inside a throwaway container on
the compose network, talking to PostgreSQL/Kafka by internal service name
and never crossing the Windows/WSL boundary) for everything except
`test_recovery.py`, and running `test_recovery.py` directly since it only
ever used `podman exec` rather than a direct TCP connection.

That whole class of failure is gone now that the topology runs on a
dedicated Docker host with real host-interface port binding (see
[infrastructure/README.md](../../infrastructure/README.md)'s migration
notes) — a single `uv run pytest -m external_service tests/integration/ -v`
now covers the full suite including `test_recovery.py`, no split run path
needed. `run-in-network.sh` still exists and still works (see below) for
CI-like isolated runs, but is no longer required for correctness on this
host.

### `run-in-network.sh`: isolated runs from inside the compose network

```bash
bash tests/integration/run-in-network.sh
# or, to pass pytest args through:
bash tests/integration/run-in-network.sh tests/integration/test_smoke.py -v
```

This must run on the Docker host itself (over SSH) — its `docker run -v`
bind-mounts the repo checkout, which only resolves against whichever
machine's Docker daemon runs it. It requires the
`infrastructure/compose/` topology already running and its secrets already
generated (see [infrastructure/README.md](../../infrastructure/README.md));
it builds a disposable virtual environment inside the container each run
(`uv sync --locked` against a `/tmp/venv` that never touches the host's own
`.venv/`), so the first run is slower than subsequent ones.

The `AI_PLATFORM_TEST_POSTGRES_HOST`, `AI_PLATFORM_TEST_POSTGRES_PORT`, and
`AI_PLATFORM_TEST_KAFKA_BOOTSTRAP_SERVERS` environment variables that make
this possible are read directly by `conftest.py`.

`test_recovery.py` does **not** work through `run-in-network.sh`: it
exercises the real `platform`/`test-agent` application containers (kill,
restart, `docker exec` for HTTP calls and `psql` queries), so it needs the
`docker` CLI itself — which the minimal container `run-in-network.sh` uses
does not have. It skips cleanly (rather than erroring) in that
environment, and should be run as part of the normal full-suite invocation
directly on the Docker host instead. Because it kills and restarts the
shared application containers, don't run it concurrently with anything
else exercising that same topology.

## What these tests need

The `infrastructure/compose/` topology from Sprint 6 (see
[infrastructure/README.md](../../infrastructure/README.md)) must be
reachable:

- PostgreSQL 17 on `192.168.1.123:5433` (the Docker host's LAN address;
  `localhost:5433` if running directly on that host), database `ai_platform`.
- Apache Kafka 3.9 (KRaft) on `192.168.1.123:19093`, the `EXTERNAL`
  SASL_PLAINTEXT / SCRAM-SHA-256 listener.

`tests/integration/conftest.py` provides session-scoped fixtures that:

1. Check that `infrastructure/compose/secrets/` is present (locally, or
   copied down from the Docker host) and the compose services are already
   reachable at the Docker host's LAN address. It never brings the topology
   up itself — the topology is managed independently on the Docker host
   (see [infrastructure/README.md](../../infrastructure/README.md)), not by
   a single test run.
2. If the topology cannot be reached after a bounded wait, every test under
   the `external_service` marker is **skipped** (not failed) with a message
   explaining what to check.
3. Never tear the topology down at the end of the session — it is the same
   shared dev stack other work depends on staying up, and Kafka's startup
   time makes repeated teardown/setup between test runs impractical.

## Fixtures

- `postgres_dsn` — a `postgresql://` DSN string using the `postgres`
  administrator credentials from `infrastructure/compose/secrets/`, pointed
  at the Docker host's `5433/ai_platform` (`192.168.1.123:5433` by default,
  overridable via `AI_PLATFORM_TEST_POSTGRES_HOST`/`_PORT`).
- `postgres_connection` — a real `psycopg.Connection` opened against that DSN
  (one per test, closed afterward).
- `kafka_bootstrap_servers` — the Docker host's host-reachable `EXTERNAL`
  Kafka listener, port `19093` (see `infrastructure/compose/kafka/entrypoint.sh`),
  overridable via `AI_PLATFORM_TEST_KAFKA_BOOTSTRAP_SERVERS`.
- `kafka_admin_client_config` — a `confluent_kafka` client config `dict`
  (bootstrap servers + `SASL_PLAINTEXT`/`SCRAM-SHA-256` credentials) for the
  `admin` principal, provisioned by
  `infrastructure/compose/scripts/init-kafka.sh`.
- `kafka_admin_client` — a `confluent_kafka.admin.AdminClient` built from the
  config above.

These are scaffolding only. The actual Section 19/20 external-service test
scenarios (Phase 7 of `docs/implementation/vertical-slice-01.md`) are built on
top of these fixtures in later work.
