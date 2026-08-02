# Sprint 6 — Done

> Scope: Vertical Slice 01, Phase 6 (concrete adapters and local deployment)
> Branch: `feature/sprint-6-concrete-adapters`
> Completed: 2026-08-02

## What was built

- Asynchronous, transaction-shaped Orchestrator and Test Agent persistence
  ports, replacing the Sprint 2 synchronous shape assumed by earlier phases.
- Psycopg 3 adapters for submission, terminal outcomes, deadlines, workflow
  queries, access audit, inbox/outbox, Agent receipts/outcomes, and recovery,
  over component-owned PostgreSQL schemas (`orchestrator`, `agent`).
- Versioned PostgreSQL migrations (`infrastructure/migrations/`) that publish
  their `schema_version` compatibility marker only after the full migration
  transaction succeeds, plus a credential-free permission-role bootstrap
  (`infrastructure/postgresql/bootstrap_roles.sql`) separating Orchestrator
  and Agent migration/runtime access.
- A broker-neutral Event Bus port and a `confluent-kafka`-based adapter
  implementing only the ADR-0005 Section 2 capability subset: exact
  immutable message bytes, `workflow_id`-keyed partitioning, manual offset
  commit, bounded publication attempts, durable quarantine, and startup
  reconciliation of confirmed quarantine offsets.
- Platform and Test Agent process composition (`src/ai_platform/runtime/`):
  typed environment configuration, protected secret-file references, schema
  compatibility gates, independent platform startup, Agent readiness,
  outbox publishers, event consumers, deadline reconciliation, structured
  JSON logs, and bounded graceful shutdown.
- An application Docker image (`infrastructure/Dockerfile`).
- **[ADR-0013](../architecture/decisions/ADR-0013-initial-broker-selection-apache-kafka.md)**:
  selects Apache Kafka as the initial self-hosted broker instead of
  Redpanda, superseding only the broker-selection clauses of ADR-0005. This
  was a real architectural decision, not an implementation detail: the
  Redpanda BSL license review had no committed owner or timeline, and
  ADR-0005 itself reserved Apache Kafka as the tested fallback for exactly
  this situation.
- A local PostgreSQL + Apache Kafka (KRaft, SASL_PLAINTEXT/SCRAM-SHA-256)
  Compose topology (`infrastructure/compose/`): pinned images, migrations
  and role bootstrap, topic creation, least-privilege per-principal ACLs,
  file-based secrets, and health-ordered startup — plus the `platform` and
  `test-agent` application services wired to run against it.

## What was validated, against real services (not mocks)

All of the following were exercised against the actual local topology
(Podman-managed PostgreSQL 17 and Apache Kafka 3.9), not simulated:

- **Migrations and roles.** Both component migrations applied through
  dedicated per-component migrator logins that must `SET ROLE` before DDL
  runs; schema and table ownership confirmed isolated per component.
- **Topics and ACLs.** All four ADR-0005 topics created; confirmed
  `orchestrator-producer` can publish to `task-commands` and is denied
  (`TopicAuthorizationException`) publishing to `task-outcomes` —
  `StandardAuthorizer` deny-by-default is in effect, not just configured.
- **End-to-end submission.** `POST /api/v1/workflows` → Orchestrator
  submission → PostgreSQL outbox (`ACKNOWLEDGED`) → Kafka `task-commands` →
  Test Agent consumer → deterministic `text.word-count` execution → Agent
  PostgreSQL receipt/outcome → Kafka `task-outcomes` → Orchestrator consumer
  → PostgreSQL terminal state → `GET /api/v1/workflows/{id}` returned
  `COMPLETED` with the correct `word_count`.
- **Agent-independent queries.** Workflow reads succeed independent of
  Agent readiness (the read path never touches the candidate selector).
- **Crash recovery — Test Agent.** Killed (`SIGKILL`) mid-flight before it
  could commit a Kafka offset; on restart, uncommitted work was correctly
  redelivered and completed, with exactly one receipt/outcome row — no
  duplicate side effect from redelivery.
- **Crash recovery — Platform.** Killed immediately after dispatch; the
  Agent kept working and published its outcome independently. Recovery took
  long enough that `task_result_deadline` expired first, so
  `DeadlineReconciler` correctly failed the workflow
  (`TASK_RESULT_DEADLINE_EXCEEDED`); the outcome consumer then correctly
  recognized the workflow was already terminal and recorded
  `late_after_terminal` in `orchestrator.inbox` rather than overwriting the
  `FAILED` state. This is a real demonstration of the deadline-vs-late-outcome
  race from ADR-0002/ADR-0006 being handled safely, not just described.
- **Assignment fencing.** With two Test Agent instances sharing the
  `ai-platform-agent-commands` consumer group, Kafka split the topic's 3
  partitions exclusively between them (no overlap); workflows completed
  correctly with both active. Killing one replica correctly rebalanced its
  partitions onto the survivor after the session timeout, and a
  subsequently submitted workflow completed normally via the survivor.
- **Quarantine.** Malformed and schema-invalid messages were correctly
  quarantined (`orchestrator.transport_rejections` /
  `agent.transport_rejections` show `CONFIRMED` disposition) during ACL and
  recovery testing.

Full detail, including exact commands and raw output, is in
[progress.md](progress.md).

## Quality gates

All four local acceptance gates from [plan.md](plan.md) pass:

- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run basedpyright` (strict)
- `uv run pytest -q` — 339 passed, offline (no live PostgreSQL/Kafka
  required for the unit/component suite; adapters are exercised through
  mocks and in-memory fakes at this level, matching
  [docs/testing/README.md](../testing/README.md))

## What needed manual setup

- `infrastructure/compose/scripts/generate-secrets.sh` and
  `generate-app-secrets.sh` must be run once to create local credentials
  before bringing the topology up (see
  [infrastructure/README.md](../../infrastructure/README.md)).
- The application image must be built manually
  (`podman build -f infrastructure/Dockerfile -t ai-platform:sprint6 .`) —
  it is not published anywhere.
- `test-agent` shares `platform`'s network namespace
  (`network_mode: "service:platform"`), which is required because
  `AI_PLATFORM_API_HOST` and the Agent readiness host/URL are validated as
  loopback literals. Restarting `platform` breaks this and requires
  recreating `test-agent` — documented as an operational note in
  `infrastructure/README.md`, not fixed away, since it is a direct
  consequence of the intentional loopback-only local-development posture.

## What's not done / explicitly out of scope

Per [plan.md](plan.md)'s declared "Out of scope":

- Phase 7 integration/recovery/security/end-to-end suites beyond this
  sprint's real-service smoke and recovery checks.
- Phase 8 operational documentation.
- Production authentication, high availability, Kubernetes, managed
  services, AI Router integration, or model execution.

Also not done, and explicitly named as open in [progress.md](progress.md):

- How runtime/deployment readiness proves the required Kafka producer,
  consumer-group, and quarantine *authorization* (not just broker
  reachability) — flagged as needing a future architectural decision
  (canary resource vs. ACL introspection), not resolved here.
- Deliberate, operator-initiated quarantine replay (quarantine itself was
  exercised; replay was not).
- Production readiness is not claimed anywhere in this sprint's
  documentation. `infrastructure/compose/` remains explicitly local-only:
  single broker, single database node, no TLS, and application ports are
  not reachable from the host by design (loopback-only).

## Files changed / created

See the pull request diff for the complete list. The largest new areas are
`src/ai_platform/adapters/persistence/` and `src/ai_platform/adapters/event_bus/`
(concrete adapters), `src/ai_platform/runtime/` (process composition),
`infrastructure/` (migrations, roles, Dockerfile, and the full
`compose/` local topology), and
`docs/architecture/decisions/ADR-0013-initial-broker-selection-apache-kafka.md`.
