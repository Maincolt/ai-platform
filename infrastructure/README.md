# Infrastructure

This directory contains reproducible Infrastructure as Code and deployment
configuration.

Infrastructure should remain cloud-agnostic where practical, support
Docker-based operation, and treat Unraid as a first-class deployment target.
Provider-specific assets should be isolated behind clearly named boundaries.

## PostgreSQL execution boundary

Run `postgresql/bootstrap_roles.sql` once against the target database as a
trusted database administrator before applying component migrations. It creates
four fixed, credential-free `NOLOGIN` permission roles:

- `ai_platform_orchestrator_migration`;
- `ai_platform_orchestrator_runtime`;
- `ai_platform_agent_migration`; and
- `ai_platform_agent_runtime`.

An infrastructure or secrets administrator must create separate login
principals outside this repository, inject their credentials from protected
environment or secret-file storage, and grant each login exactly one permission
role. Do not pass passwords through committed SQL, command-line arguments, or
version-controlled environment files. Runtime DSNs are supplied through the
existing `AI_PLATFORM_*_DATABASE_DSN_FILE` configuration variables.

Apply each migration with a login that can `SET ROLE` only to its matching
migration role. For noninteractive `psql`, set the session role through a
protected execution environment and retain `ON_ERROR_STOP`; do not run
migrations with a runtime login. The scripts use an explicit transaction and
publish `schema_version` only at the end, so a failed invocation rolls back
instead of advertising a partial schema.

Runtime logins inherit only DML and required sequence privileges in their own
component schema. They receive no schema-creation, DDL, other-component schema,
or migration-role privileges. Provisioning login credentials, backup roles,
and administrator roles remains an infrastructure security operation outside
application containers.

## Local Compose topology

`compose/` provides a single-node, local-only PostgreSQL and Apache Kafka
(KRaft) topology for Sprint 6 real-service validation. It is not a
deployment target and is never referenced from an application container
image; it exists to prove the concrete adapters in
`src/ai_platform/adapters/` against real services.

The broker is Apache Kafka rather than Redpanda — see
[ADR-0013](../docs/architecture/decisions/ADR-0013-initial-broker-selection-apache-kafka.md)
for why this differs from ADR-0005's preferred initial broker.

```bash
cd infrastructure/compose
bash scripts/generate-secrets.sh   # once, creates secrets/*.txt (git-ignored)
podman compose up -d postgres kafka
podman compose up postgres-init kafka-init   # apply migrations, topics, ACLs
```

What each service does:

- `postgres` — PostgreSQL 17, database `ai_platform`.
- `postgres-init` — runs once: applies `postgresql/bootstrap_roles.sql` as
  the administrator, creates one LOGIN role per migration/runtime identity
  (`ai_platform_{orchestrator,agent}_{migrator,app}`), grants each its
  matching permission role (migrator logins `WITH INHERIT FALSE`, so they
  must `SET ROLE` before DDL runs), then applies `migrations/0001` and
  `migrations/0002` through the matching migrator login only.
- `kafka` — Apache Kafka 3.9 in combined KRaft broker/controller mode.
  `kafka/entrypoint.sh` seeds the `admin` principal and all four application
  SCRAM principals directly into the metadata log via
  `kafka-storage.sh format --add-scram` on first start, which avoids the
  bootstrap deadlock of requiring an authenticated connection to create the
  first SCRAM credential. The client listener is `SASL_PLAINTEXT` with
  `SCRAM-SHA-256`, matching `LOCAL_DEVELOPMENT_SASL_PLAINTEXT` in
  `src/ai_platform/adapters/event_bus/security.py`.
- `kafka-init` — runs once: creates the four ADR-0005 Section 6 topics
  (`ai-platform.development.task-commands.v1` and `task-outcomes.v1`, each
  with a `.quarantine` topic) and grants least-privilege ACLs so
  `orchestrator-producer` can only write commands, `orchestrator-consumer`
  can only read outcomes and write the outcomes quarantine topic,
  `agent-producer` can only write outcomes, and `agent-consumer` can only
  read commands and write the commands quarantine topic. `StandardAuthorizer`
  denies by default; only `admin` (and the unauthenticated,
  not-host-published controller listener's `ANONYMOUS` principal) is a
  super user.

Application runtime configuration is wired to this topology by the
`platform` and `test-agent` services below.

This is explicitly non-production: single broker, single database node, no
TLS, and locally generated credentials in `compose/secrets/` (git-ignored,
regenerate with `scripts/generate-secrets.sh`, never commit them).

## Running the application against the topology

`compose/docker-compose.yml` also defines `platform` and `test-agent`
services, gated behind the `app` Compose profile so a plain `up` never starts
them. Build the image first, generate the additional application secrets,
then start both processes:

```bash
podman build -f infrastructure/Dockerfile -t ai-platform:sprint6 .   # from repo root
cd infrastructure/compose
bash scripts/generate-app-secrets.sh   # DSNs + shared readiness credential
podman compose --profile app up -d platform test-agent
```

`compose/runtime/registry.json` is one Registry/declaration artifact shared
by both processes (the Test Agent's declaration format is the same
single-binding shape as the Orchestrator's Registry, so one file satisfies
both `AI_PLATFORM_REGISTRY_PATH` and `AI_PLATFORM_AGENT_DECLARATION_PATH`).

`test-agent` runs with `network_mode: "service:platform"` — it shares the
platform container's network namespace rather than getting its own. This is
required, not incidental: `AI_PLATFORM_API_HOST` and
`AI_PLATFORM_AGENT_READINESS_HOST`/`AI_PLATFORM_AGENT_READINESS_URL` are all
validated to be loopback literals (`src/ai_platform/runtime/configuration.py`
rejects anything else), so the platform can only reach the Agent's readiness
endpoint, and the Agent can only be reached, over `127.0.0.1` — which means
both must be in the same network namespace.

Two real configuration requirements this surfaced (not documented
elsewhere): `AI_PLATFORM_ORCHESTRATOR_INSTANCE_ID` and
`AI_PLATFORM_AGENT_PUBLISHER_INSTANCE_ID` are not free-form strings — they
become `producer.instance_id` in the ADR-0004 envelope, which
`execute_task.schema.json` / `task_completed.schema.json` /
`task_failed.schema.json` all constrain to the UUIDv7 pattern. A non-UUID
instance ID passes configuration loading but makes every published message
fail schema validation on the consuming side (quarantined as
`SCHEMA_INVALID`, silently, since production is not a debugging path).

Validated end-to-end with real services (2026-08-02): submitted a workflow
through `POST /api/v1/workflows`, confirmed it reached `COMPLETED` with the
correct `word_count` via `GET /api/v1/workflows/{id}`, and confirmed the
full path was exercised in PostgreSQL (`orchestrator.outbox` row
`ACKNOWLEDGED`, `agent.completed_receipts`/`agent.outcomes` populated) and
Kafka (consumer group lag `0` on both `ai-platform-orchestrator-outcomes`
and `ai-platform-agent-commands`).

Crash recovery was also validated directly: killing `test-agent` mid-flight
and restarting it correctly redelivered and completed the in-flight command
with no duplicate side effect; killing `platform` after dispatch let the
Agent finish and publish its outcome independently, and recovery correctly
exercised a real deadline-vs-late-outcome race (see `docs/sprint-6/progress.md`
for the full account). One operational gotcha from that exercise:
**restarting `platform` breaks `test-agent`'s networking.** Because
`test-agent` uses `network_mode: "service:platform"`, it is bound to the
platform container's original network namespace, not to "whichever
container is currently named platform" — even `podman start` on the same,
un-removed container breaks it (`librdkafka` then fails DNS resolution for
`kafka:9092`). After restarting `platform` for any reason, recreate
`test-agent` too:

```bash
podman rm -f ai-platform-local-test-agent-1
podman compose --profile app up -d test-agent
```

The `platform`/`test-agent` containers were tested via `podman exec` calls
to `127.0.0.1` inside the container, not via the host-published `8000`/`8100`
ports. On this host's Podman network backend (`netavark`), host port
publishing NATs to the container's bridge interface, not its loopback — so
a listener bound strictly to `127.0.0.1` (as this loopback-only-by-design
configuration requires) is unreachable from outside the container's network
namespace by construction. This is consistent with the security posture in
ADR-0005 Section 17 ("loopback-limited exposure... explicitly
non-production"), not a defect to fix.
