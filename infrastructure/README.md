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

`compose/` provides a single-node PostgreSQL and Apache Kafka (KRaft)
topology for Sprint 6 real-service validation. It is not a production
deployment target and is never referenced from an application container
image; it exists to prove the concrete adapters in
`src/ai_platform/adapters/` against real services.

The broker is Apache Kafka rather than Redpanda — see
[ADR-0013](../docs/architecture/decisions/ADR-0013-initial-broker-selection-apache-kafka.md)
for why this differs from ADR-0005's preferred initial broker.

**Runs on a dedicated Docker host, not the developer's own machine.** The
topology runs on Docker Desktop on a Mac at `192.168.1.123` (LAN), reached
over SSH — see [docs/operations/README.md](../docs/operations/README.md)
Section 1 for the connection details and why (the local Windows/Podman/WSL2
setup this used to run on had unreliable container-port forwarding). Every
`docker ...` command below is run from an SSH session into that host, from
the repo checked out there — Docker's bind mounts resolve on whichever
machine runs the daemon, so the repo must exist on the Mac itself, not just
be referenced remotely.

```bash
ssh -i ~/.ssh/mac_docker gebruiker@192.168.1.123
cd ~/ai-platform/infrastructure/compose
bash scripts/generate-secrets.sh   # once, creates secrets/*.txt (git-ignored)
export KAFKA_EXTERNAL_ADVERTISED_HOST=192.168.1.123   # see kafka/entrypoint.sh
docker compose up -d postgres kafka
docker compose up postgres-init kafka-init   # apply migrations, topics, ACLs
```

**`KAFKA_EXTERNAL_ADVERTISED_HOST` matters for any client not running on the
Docker host itself.** Kafka's `EXTERNAL` listener answers a client's initial
bootstrap connection, then tells it where to reconnect for actual
metadata/produce/consume traffic (`advertised.listeners`). Left at the
default `localhost`, that reconnect address resolves to the *client's own
machine*, not the Mac — bootstrap succeeds, then every real request times
out. This was invisible before the host migration (client and broker were
the same machine) and needs setting explicitly now.

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
then start both processes (all from the SSH session into the Docker host,
repo root at `~/ai-platform`):

```bash
docker build -f infrastructure/Dockerfile -t ai-platform:sprint6 .   # from repo root
cd infrastructure/compose
bash scripts/generate-app-secrets.sh   # DSNs + shared readiness credential
docker compose --profile app up -d platform test-agent
```

`compose/runtime/registry.json` is one Registry/declaration artifact shared
by every process (the Orchestrator and every Agent deployment all point
`AI_PLATFORM_REGISTRY_PATH`/`AI_PLATFORM_AGENT_DECLARATION_PATH` at the same
file). As of ADR-0018 it carries one binding per Agent class -- `text.word-count`
(test-agent/test-agent-2), `text.summarize` (summarize-agent), and
`code.review` (review-agent) -- and each Agent process selects its own
binding from the shared file by `agent_id`, not by file position or binding
count (`load_agent_deployment_declaration` in
`src/ai_platform/runtime/loading.py`).

### Sprint 9: `summarize-agent` and the AI Router

`summarize-agent` runs the second built-in Agent class, `text.summarize`
(ADR-0014). It reuses the same `ai-platform-test-agent` console script as
`test-agent`/`test-agent-2` -- `build_agent_process()` selects the executor
class (`TestAgent` vs `SummarizeAgent`) from the loaded declaration's
`capability_name`, so there is only one generic Agent process entrypoint.
Per ADR-0014 Section 6, `task-commands` is now capability-scoped at the
physical-topic level (`...task-commands.text-word-count.v1` and
`...task-commands.text-summarize.v1`, each with its own `.quarantine`
companion), and Kafka ACLs are narrowed accordingly: `agent-producer`/
`agent-consumer` (test-agent/test-agent-2) now see only the
`text-word-count` command topic and their existing consumer group;
`summarize-agent-producer`/`summarize-agent-consumer` are new principals
scoped to `text-summarize`'s command topic, its own quarantine topic, and a
new `ai-platform-summarize-agent-commands` consumer group.

**`ai_router_anthropic_api_key.txt` / `ai_router_openai_api_key.txt` in
`compose/secrets/` are obviously-fake placeholders**
(`sk-ant-PLACEHOLDER-NOT-A-REAL-KEY-see-sprint-9-docs` /
`sk-PLACEHOLDER-NOT-A-REAL-KEY-see-sprint-9-docs`), not real provider
credentials -- this environment has no real Anthropic/OpenAI API access
(explicit Sprint 9 scope exclusion). `summarize-agent` therefore starts and
reaches `READY`, but any real `text.summarize` submission fails at the
provider call (`PROVIDER_UNAVAILABLE`/authentication failure translated by
the adapter, never a raw provider exception -- ADR-0014 Section 1). Replace
both files with real keys (never commit them; `compose/secrets/` is
git-ignored) to exercise a real completion.

### ADR-0018: `review-agent` and the `code.review` capability

`review-agent` runs the platform's third built-in Agent class, `code.review`
(ADR-0018) -- the first candidate from the software-team-persona capability
set, and the second to call the AI Router. It reuses the same generic Agent
process entrypoint as `test-agent`/`summarize-agent`
(`build_agent_process()` selects `ReviewAgent` from the loaded
declaration's `capability_name`). Its command topic is capability-scoped
the same way `text.summarize`'s is
(`...task-commands.code-review.v1` + `.quarantine`), with its own
`review-agent-producer`/`review-agent-consumer` principals and
`ai-platform-review-agent-commands` consumer group.

Per the repository owner's decision during this capability's deployment
wiring, `review-agent` reuses `summarize-agent`'s exact placeholder AI
Router setup: the same obviously-fake `ai_router_anthropic_api_key.txt`/
`ai_router_openai_api_key.txt` secrets, and the same ADR-0017 Decision 3
approved model list (`claude-haiku-4-5`/`gpt-5-mini`) -- see ADR-0018's
Implementation Status section. `review-agent` therefore starts and reaches
`READY`, but any real `code.review` submission fails at the provider call,
exactly like `summarize-agent`.

### Agent status dashboard (`dashboard`)

`dashboard` (`frontend/dashboard/`) is a Vue 3 + Vite single-page app,
containerized as a multi-stage build: `npm run build` produces a static
bundle, served by a minimal `nginx:1.27-alpine` image. It polls
`GET /api/v1/agents` every 5 seconds and renders a live, color-coded card
per declared Agent binding (Online/Stale/Unavailable/Unknown, derived from
the same READY-and-fresh rule candidate selection itself uses). Read-only:
it never submits work and never affects candidate selection.

Like `test-agent`, `dashboard` runs with `network_mode: "service:platform"`
rather than getting its own network namespace — deliberately, not for
convenience. `AI_PLATFORM_API_HOST` is validated as a loopback literal
(same rule referenced below) and this is an intentional, documented
security posture (`docs/operations/README.md` Section 8: "loopback-only
application exposure"), not something this dashboard should widen. Sharing
platform's namespace lets nginx reverse-proxy `/api/`/`/health/` to
`127.0.0.1:8000` — reaching the real Workflow API without exposing it to
the wider Compose network the way `summarize-agent`'s
`0.0.0.0`-bound readiness endpoint does. Because a `network_mode:
"service:platform"` container cannot declare its own `ports:`, `8080:80`
is published on the `platform` service block instead, the same way
`8000`/`8100` already are.

**A real deployment lesson hit while verifying this**: the running
`ai-platform:sprint6` image can silently predate the source tree if it was
last built before a merge that touched `src/` — `docker compose up` does
not rebuild automatically. The dashboard's proxy correctly reached
`platform`, but got a genuine `404` for `/api/v1/agents` until the image
was rebuilt (`docker build -f infrastructure/Dockerfile -t
ai-platform:sprint6 .`) to pick up that endpoint. Not a `dashboard`-specific
gap — any change to `src/` needs an image rebuild before the next
`compose up`, `docker compose build` alone does not imply this either. This
also means the Mac's copy of the repo needs to be re-synced (`git archive
HEAD | ssh ... "tar -x -C ~/ai-platform"`, or a plain `git pull` once the
Mac has Xcode Command Line Tools installed) before rebuilding, since the
image build reads from the Mac's own checkout.

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
container is currently named platform" — even `docker start` on the same,
un-removed container breaks it (`librdkafka` then fails DNS resolution for
`kafka:9092`). After restarting `platform` for any reason, recreate
`test-agent` too:

```bash
docker rm -f ai-platform-local-test-agent-1
docker compose --profile app up -d test-agent
```

The `platform`/`test-agent` containers were originally tested via `podman
exec` calls to `127.0.0.1` inside the container rather than via the
host-published `8000`/`8100` ports, because the local Windows/Podman
network backend (`netavark`) NATed host port publishing to the container's
bridge interface, not its loopback — so a listener bound strictly to
`127.0.0.1` (as this loopback-only-by-design configuration requires) was
unreachable from outside the container's network namespace by construction.
That constraint is unchanged on the current Docker Desktop for Mac host —
`8000`/`8100` are still not host-reachable, by the same loopback-binding
logic, regardless of host OS or container engine — so `docker exec` (not
the published ports) is still the right way to reach them. This is
consistent with the security posture in ADR-0005 Section 17
("loopback-limited exposure... explicitly non-production"), not a defect to
fix. What *did* change with the host migration is `postgres`/`kafka`/the
dashboard's `8080`: those bind to real interfaces and are now reachable
directly at `192.168.1.123:PORT` from any machine on the LAN, which was not
reliable under the old Windows/Podman/WSL2 `gvproxy` forwarding path.
