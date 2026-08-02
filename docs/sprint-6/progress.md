# Sprint 6 Progress — Concrete Adapters and Local Deployment

> Status: In progress  
> Updated: 2026-08-02  
> Scope: Vertical Slice 01, Phase 6

## Implemented locally

- Asynchronous, transaction-shaped Orchestrator and Test Agent persistence
  boundaries.
- Psycopg 3 adapters for submission, terminal outcomes, deadlines, workflow
  queries, access audit, inbox/outbox, Agent receipts/outcomes, and recovery.
- Atomic component-owned PostgreSQL migrations whose compatibility marker is
  written only after the complete migration succeeds.
- Credential-free PostgreSQL permission roles separating Orchestrator and
  Agent migration/runtime access.
- A broker-neutral Event Bus port and a `confluent-kafka` adapter using the
  ADR-0005 Kafka capability subset.
- Exact immutable message-byte publication, keyed routing, manual source
  progress, bounded publication attempts, durable quarantine, and startup
  reconciliation of confirmed quarantine offsets.
- Platform and Test Agent process composition, typed configuration, protected
  secret-file references, schema compatibility gates, runtime health,
  independent platform startup, Agent readiness, publishers, consumers,
  deadline reconciliation, structured JSON logs, and bounded shutdown.
- A Docker application image definition.
- Unit and component coverage for the new adapters and runtime boundaries.

## Architecture corrections made during review

- New submissions check current Agent readiness before workflow creation;
  authorized replay and workflow queries remain available independently.
- Recovery of already-dispatched work no longer depends on the current
  Capability Registry revision.
- Terminal outcomes are checked against the persisted selection, dispatched
  command, capability, producer, causation, and immutable input evidence.
- First-seen late or conflicting terminal messages record inbox disposition and
  required audit evidence atomically; duplicate delivery does not duplicate the
  audit record.
- Agent readiness identity includes the declaration revision/digest and exact
  command/event contract sets. Its bounded response parser rejects oversized,
  compressed, malformed, or duplicate-key documents.
- Availability TTL is measured with a process-local monotonic clock.
- Incomplete durable quarantine causes the consumer service to fail closed for
  process recovery rather than remaining falsely healthy.

## Validation completed without external services

Focused adapter/runtime checks have passed during development, including Ruff,
strict BasedPyright, and broker-free unit/component suites. A final repository-
wide gate will be recorded before the Sprint 6 checkpoint commit.

These checks do **not** establish PostgreSQL transaction behavior, Kafka
delivery/rebalance behavior, broker ACL correctness, image buildability, or
restart recovery against real services.

## Update: container engine and broker prerequisites resolved

Both items in the "Required repository-owner action" section below as
originally written are now resolved:

- Podman 6.0.2 (WSL-backed machine) is installed and running on the
  development host and was verified with a real container pull/run. The
  "no usable container engine" statement was stale.
- The repository owner selected Apache Kafka as the initial self-hosted
  broker instead of waiting on the Redpanda BSL license review; see
  [ADR-0013](../architecture/decisions/ADR-0013-initial-broker-selection-apache-kafka.md),
  which supersedes only the broker-selection clauses of ADR-0005.

`infrastructure/compose/` now provides a local PostgreSQL 17 and Apache
Kafka 3.9 (KRaft, SASL_PLAINTEXT/SCRAM-SHA-256) topology — see
[infrastructure/README.md](../../infrastructure/README.md#local-compose-topology).
Brought up with Podman and validated directly:

- `postgres-init` applied `postgresql/bootstrap_roles.sql` and both
  component migrations (`0001_orchestrator_schema.sql`,
  `0002_agent_schema.sql`) through dedicated per-component migrator logins
  that must `SET ROLE` before DDL executes; the `orchestrator` and `agent`
  schemas and all tables are owned by their respective migration role, not
  by the administrator or by each other.
- `kafka-init` created the four ADR-0005 Section 6 topics and least-privilege
  ACLs. Verified directly: `orchestrator-producer` authenticates via
  SCRAM-SHA-256 and can publish to `task-commands`, and is denied
  (`TopicAuthorizationException`) when attempting to publish to
  `task-outcomes`, confirming `StandardAuthorizer` deny-by-default is in
  effect.
- This exercises the **topology only** — no application process has run
  against it yet. The `AI_PLATFORM_*` runtime configuration in
  `src/ai_platform/runtime/configuration.py` is not yet wired to these
  services (bootstrap servers, DSNs, principals, topic names).

A gap surfaced by this validation and fixed in the same pass:
`postgresql/bootstrap_roles.sql` did not grant database-level `CREATE` to the
migration roles, so `CREATE SCHEMA IF NOT EXISTS` failed for a migration
login even when the schema already existed. Fixed by granting `CREATE ON
DATABASE` to the two migration roles only.

## Update: full real-service round trip validated end-to-end

`infrastructure/Dockerfile` was built (`ai-platform:sprint6`), and
`infrastructure/compose/docker-compose.yml` now has `platform` and
`test-agent` application services (behind the `app` Compose profile — see
[infrastructure/README.md](../../infrastructure/README.md#running-the-application-against-the-topology)).
Both processes were started against the real PostgreSQL/Kafka topology and a
workflow was submitted and completed through the real path:

`POST /api/v1/workflows` → Orchestrator submission → PostgreSQL outbox
(`ACKNOWLEDGED`) → Kafka `task-commands` → Test Agent consumer (lag `0`) →
deterministic `text.word-count` execution → Agent PostgreSQL receipt/outcome
→ Kafka `task-outcomes` → Orchestrator consumer (lag `0`) → PostgreSQL
terminal state → `GET /api/v1/workflows/{id}` returned `COMPLETED` with the
correct `word_count`.

Two real configuration requirements surfaced and are now documented in
`infrastructure/README.md`, not just discovered and fixed silently:

- `AI_PLATFORM_ORCHESTRATOR_INSTANCE_ID` and
  `AI_PLATFORM_AGENT_PUBLISHER_INSTANCE_ID` must be UUIDv7 strings, not
  free-form identifiers — they become `producer.instance_id` in the
  ADR-0004 envelope, which the canonical schemas constrain by pattern. A
  non-UUID value fails configuration loading silently at the schema-validation
  step later (consumer-side quarantine as `SCHEMA_INVALID`), not at startup.
- The platform and Test Agent must share a network namespace
  (`network_mode: "service:platform"` in Compose) because
  `AI_PLATFORM_API_HOST` and the Agent readiness host/URL are all validated
  as loopback literals.

The host-published `8000`/`8100` ports are not reachable from outside the
container on this host's `netavark` network backend, because a listener
bound strictly to `127.0.0.1` does not receive NAT-forwarded traffic that
arrives on the container's bridge interface. Validation used `podman exec`
into the container's own network namespace instead. This is a consequence
of the intentional loopback-only local-development posture (ADR-0005
Section 17), not a gap to close.

## Update: crash recovery validated against real services

Two SIGKILL crash-recovery scenarios were exercised against the running
`platform`/`test-agent` containers, both with real PostgreSQL and Kafka.

**Test Agent killed mid-flight.** A workflow was submitted and the
`test-agent` container was killed (`SIGKILL`) immediately after dispatch,
before it could poll the command. The workflow correctly stayed
`DISPATCHED` while the Agent was down. On restart, the Agent's consumer
(manual offset commit only after durable processing, so nothing was
committed before the kill) redelivered the uncommitted message and completed
the workflow normally (`COMPLETED`, correct `word_count`). `agent.completed_receipts`
and `agent.outcomes` each show exactly one row for the attempt — no
duplicate side effect from the redelivery.

**Platform killed after dispatch.** A workflow was submitted and `platform`
was killed immediately after the request returned 202 (the outbox row had
already reached `ACKNOWLEDGED` in the race — the publisher worker won). With
`platform` down, the Test Agent still processed the command and published
`TaskCompleted` to Kafka on schedule (`agent.outcomes` shows a completed row
timestamped seconds after dispatch). Recovering `platform` correctly took
Compose several manual steps (see below), long enough that the
`task_result_deadline` (60s, `AI_PLATFORM_TASK_RESULT_TIMEOUT_SECONDS`)
expired before the outcome consumer caught up. The result exercised two
independent correctness paths in the same run, both correct:

1. `DeadlineReconciler` correctly failed the workflow
   (`TASK_RESULT_DEADLINE_EXCEEDED`) once its deadline passed while still
   `DISPATCHED`.
2. When the outcome consumer rejoined and delivered the backlogged
   `TaskCompleted` moments later, `PsycopgOrchestratorPersistence.apply_terminal_outcome`
   (`src/ai_platform/adapters/persistence/orchestrator.py:195`) found the
   workflow already terminal and recorded it as `late_after_terminal` in
   `orchestrator.inbox` rather than overwriting the `FAILED` state — proving
   terminal-state immutability holds even when a legitimate, correctly
   computed outcome arrives after its deadline.

This is a stronger result than a clean "it recovered" would have been: it is
a live demonstration of the deadline-vs-late-outcome race from ADR-0002/ADR-0006
being handled safely, not just described.

**Operational finding, not an application bug:** `test-agent` uses
`network_mode: "service:platform"` (required — see
[infrastructure/README.md](../../infrastructure/README.md#running-the-application-against-the-topology)).
Restarting the `platform` container (even `podman start` on the same,
un-removed container) breaks the Agent's network namespace reference —
`librdkafka` then fails DNS resolution for `kafka:9092` — because the shared
namespace is tied to the platform container's original instantiation.
Recovering `platform` in this topology requires recreating `test-agent`
afterward (`podman rm -f` + `podman compose --profile app up -d test-agent`),
not just restarting it. This is documented in `infrastructure/README.md` as
an operational note for anyone else exercising this topology.

## Update: Kafka assignment fencing and rebalance validated with two Agent replicas

A second Test Agent replica (`test-agent-2`, same `ai-platform:sprint6` image,
same `AI_PLATFORM_AGENT_COMMAND_CONSUMER_GROUP_ID=ai-platform-agent-commands`
and same Kafka/Postgres secrets, reaching `kafka:9092`/`postgres:5432` by
service name on the default Compose network rather than sharing `platform`'s
network namespace) was added to `infrastructure/compose/docker-compose.yml`
behind the same `app` profile and started alongside the existing `platform`
and `test-agent` containers.

`kafka-consumer-groups.sh --describe --group ai-platform-agent-commands`
(admin SCRAM credential, as in `init-kafka.sh`) before adding the second
replica showed all 3 partitions of `ai-platform.development.task-commands.v1`
assigned to the one existing consumer ID. After the second replica joined,
the same describe showed the group correctly split across two distinct
consumer IDs — partitions 0 and 1 on the new replica, partition 2 on the
original — confirming exclusive, non-overlapping partition assignment
(fencing) across members of the same group. Four workflows were submitted
through `POST /api/v1/workflows` with both replicas active and all reached
`COMPLETED` with the correct `word_count`.

The second replica was then killed (`podman kill`). Immediately after the
kill, the describe output still showed the (now-dead) replica's consumer ID
holding partitions 0/1 with advancing offsets — consumer-group metadata does
not update until the broker's session timeout expires. After waiting past
that timeout (~30s), re-describing the group showed all 3 partitions
correctly rebalanced onto the sole surviving consumer ID. A workflow
submitted after the rebalance completed normally (`COMPLETED`, correct
`word_count`), confirming the survivor picked up full coverage with no
manual intervention.

The second replica's container was removed after validation
(`podman rm -f ai-platform-local-test-agent-2-1`); its Compose service
definition remains in `docker-compose.yml` behind the `app` profile for
future re-use but is not started by a normal `--profile app up`.

## Remaining Sprint 6 work

- Decide how runtime/deployment readiness proves the required Kafka producer,
  consumer-group, and quarantine authorization. Metadata alone proves broker
  reachability, not operation permissions; introducing a canary resource or
  granting ACL introspection would be an architectural choice.
- Exercise the quarantine replay path deliberately as an authorized operator
  action (malformed/schema-invalid messages were quarantined correctly
  during this and earlier ACL testing — `orchestrator.transport_rejections`
  and `agent.transport_rejections` both show `CONFIRMED` quarantine records —
  but replay itself has not been exercised).

## Scope not claimed

- Sprint 6 is not complete.
- Phase 7 and Phase 8 have not started.
- Production readiness is not claimed. `infrastructure/compose/` is
  explicitly local-only: single broker, single database node, no TLS, and
  the application ports are not reachable from the host by design.
