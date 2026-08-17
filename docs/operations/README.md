# Operations — Local Deployment

> Scope: the `infrastructure/compose/` deployment only (Docker-managed
> PostgreSQL 17 + Apache Kafka 3.9 + the `platform`/`test-agent`
> application containers). **This document makes no production-readiness
> claim.** Every command below has been independently re-run against a
> real environment (Sprint 8, see [docs/sprint-8/done.md](../sprint-8/done.md);
> re-verified 2026-08-12 on the current Docker host, see Section 1) —
> nothing here is aspirational or copied without re-verification.
>
> For the full topology design (roles, ACLs, secrets, why each piece is
> shaped the way it is), see [infrastructure/README.md](../../infrastructure/README.md).
> This document is the operator-facing "how do I actually run and check on
> this thing" companion to that design document.

## 1. Setup

**The topology runs on a dedicated Docker host, not the developer's own
machine**: a Mac (Docker Desktop) on the LAN at `192.168.1.123`, macOS
user `gebruiker`, reached over SSH with a dedicated key. This replaced an
earlier local Windows/Podman/WSL2 setup whose container-port forwarding
(`gvproxy`) was unreliable — see [Section 7](#7-troubleshooting) for what
that looked like and why it's no longer the operating model.

```bash
# 0. Connect to the Docker host; run everything below from this session
ssh -i ~/.ssh/mac_docker gebruiker@192.168.1.123
cd ~/ai-platform

# Non-interactive SSH sessions on macOS don't source .zprofile, so `docker`
# isn't on PATH by default -- export it once per session (or prefix every
# command):
export PATH="/Applications/Docker.app/Contents/Resources/bin:/usr/local/bin:$PATH"

# 1. Generate local secrets (once; both are safe to re-run.
#    generate-secrets.sh skips any file that already exists.
#    generate-app-secrets.sh always rewrites the derived DSN files, but
#    deterministically from the already-generated passwords, so the content
#    is unchanged on a re-run; it skips only the readiness credential if
#    that file already exists)
cd infrastructure/compose
bash scripts/generate-secrets.sh
bash scripts/generate-app-secrets.sh

# 2. Bring up PostgreSQL and Kafka, apply migrations/roles/topics/ACLs
# KAFKA_EXTERNAL_ADVERTISED_HOST must be the Docker host's own reachable
# address, or Kafka clients running elsewhere will bootstrap successfully
# and then time out on every real request (see infrastructure/README.md).
export KAFKA_EXTERNAL_ADVERTISED_HOST=192.168.1.123
docker compose up -d postgres kafka
docker compose up postgres-init kafka-init

# 3. Build the application image (from the repository root)
cd ../..
docker build -f infrastructure/Dockerfile -t ai-platform:sprint6 .

# 4. Start the platform and Test Agent
cd infrastructure/compose
docker compose --profile app up -d platform test-agent
```

`postgres-init`/`kafka-init` are one-shot jobs (`restart: "no"`) — they
exit after running; that is expected, not a failure. Re-running step 2 is
safe (migrations and topic/ACL creation are idempotent).

The repo must exist on the Docker host itself (bind mounts resolve against
the daemon's filesystem, not the client's) — sync it with
`git archive HEAD | ssh -i ~/.ssh/mac_docker gebruiker@192.168.1.123 "tar -x -C ~/ai-platform"`
from the developer machine after any commit, until the Mac has Xcode
Command Line Tools installed for native `git pull`.

## 2. Health

The platform and Test Agent expose readiness endpoints, but — by design
(loopback-only exposure, see [Section 8](#8-security-limitations)) — they
are not reachable from the host. Check them via `docker exec`:

```bash
# Platform readiness (aggregates database, event bus, registry, runtime checks)
docker exec ai-platform-local-platform-1 python3 -c "
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=5) as r:
    print(r.status, r.read().decode())
"
# Expect: 200 {"status":"ready"}

# Platform liveness (always succeeds once the process is up)
docker exec ai-platform-local-platform-1 python3 -c "
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=5) as r:
    print(r.status, r.read().decode())
"
# Expect: 200 {"status":"alive"}
```

Container-level health for PostgreSQL and Kafka:

```bash
docker ps --format "{{.Names}} {{.Status}}"
# postgres and kafka should show "(healthy)"; platform/test-agent show
# "Up ..." only -- they have no docker-level HEALTHCHECK, so readiness
# must be checked via the endpoints above.
```

Kafka consumer group health (useful for confirming the Test Agent is
actually attached and not lagging):

```bash
docker exec ai-platform-local-kafka-1 bash -c '
admin_pw=$(cat /run/secrets/kafka_admin_password)
cat > /tmp/admin-client.properties <<EOF
security.protocol=SASL_PLAINTEXT
sasl.mechanism=SCRAM-SHA-256
sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="admin" password="$admin_pw";
EOF
/opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
  --command-config /tmp/admin-client.properties --describe \
  --group ai-platform-agent-commands
'
```

## 3. Query — submitting and reading a workflow

The platform's only built-in capability is `text.word-count` — a
deterministic word counter, not an AI/LLM capability (see
[README.md](../../README.md) for what "Agent" means architecturally; the
AI Router and additional Agent types are not built yet). Because the API
binds to loopback only inside its own container, submit and read requests
via `docker exec`, exactly as validation did in Sprints 6–7:

```bash
docker exec ai-platform-local-platform-1 python3 -c "
import urllib.request, json, uuid

def uuid7():
    b = bytearray(uuid.uuid4().bytes)
    b[6] = (b[6] & 0x0F) | 0x70
    b[8] = (b[8] & 0x3F) | 0x80
    return str(uuid.UUID(bytes=bytes(b)))

body = json.dumps({
    'request_id': uuid7(),
    'text': 'the quick brown fox jumps over the lazy dog',
    'capability': 'text.word-count',
    'capability_version': '1.0',
}).encode()
req = urllib.request.Request(
    'http://127.0.0.1:8000/api/v1/workflows', data=body, method='POST',
    headers={'Content-Type': 'application/json'},
)
with urllib.request.urlopen(req, timeout=10) as resp:
    print(resp.status)
    print(resp.read().decode())
"
```

Expect `202` with a JSON body containing `workflow_id` and
`state: "DISPATCHED"`. Then read it back (substitute the `workflow_id`
from the response above):

```bash
docker exec ai-platform-local-platform-1 python3 -c "
import urllib.request
wf_id = 'PASTE-WORKFLOW-ID-HERE'
with urllib.request.urlopen(
    f'http://127.0.0.1:8000/api/v1/workflows/{wf_id}', timeout=10
) as resp:
    print(resp.status)
    print(resp.read().decode())
"
```

Expect it to reach `state: "COMPLETED"` within a second or two, with
`result.word_count` matching the submitted text (9, for the example
above). Workflow reads succeed regardless of Test Agent readiness — only
*new submissions* are gated on Agent readiness (see
`src/ai_platform/orchestrator/application/submission.py`).

### Team-based assignment routing (ADR-0023)

`assignment.route` reads a free-text assignment and recommends which of
the team's six real content-review capabilities should look at it — but
it never dispatches anything itself (see ADR-0023 Decision 1/5: it is an
ordinary bounded-advisory capability with no access to the Orchestrator
or Workflow API). `infrastructure/compose/scripts/submit-assignment.py`
is the caller-side script that does the actual fan-out: it submits the
assignment to `assignment.route`, reads the recommendation list, submits
the same text to every recommended capability, polls each to a terminal
state, and prints a combined report. Every step it performs is an
ordinary Workflow API call an operator could make by hand — the script
only automates the sequence, matching this document's other manual
verification scripts:

```bash
docker cp infrastructure/compose/scripts/submit-assignment.py \
    ai-platform-local-platform-1:/tmp/submit-assignment.py
docker exec ai-platform-local-platform-1 python3 /tmp/submit-assignment.py \
    "Proposed schema: CREATE TABLE notifications (...); new endpoint POST \
    /api/v1/notifications sends synchronously, no retry. Also want a \
    weekly usage report: notification count, latency, AI provider cost."
```

Expect a `Routing decision: COMPLETED` line, then one `=== <capability>
===` section per recommended capability with its own rationale and
result — verified live to correctly split a mixed schema-design-and-
reporting assignment into `technical.review` (schema/API concerns) and
`data.analysis` (usage-report concerns), each returning genuine,
distinct findings.

## 4. Recovery — demonstrated crash scenarios

Both scenarios below were proven in Sprints 6–7, including running the
platform-crash scenario multiple times to confirm both sides of a genuine
timing race resolve safely (see
[docs/sprint-7/done.md](../sprint-7/done.md)). The automated versions are
`tests/integration/test_recovery.py`; the commands below are the manual
equivalent for an operator.

### Test Agent crash

```bash
docker kill ai-platform-local-test-agent-1
# A workflow submitted just before this point stays DISPATCHED while the
# Agent is down -- it is not lost.
docker start ai-platform-local-test-agent-1
# Uncommitted Kafka work is redelivered once the Agent reconnects; the
# workflow reaches COMPLETED with no duplicate receipt/outcome.
```

### Platform crash

```bash
docker kill ai-platform-local-platform-1
# The Agent keeps working independently and publishes its outcome even
# while the platform is down.
docker start ai-platform-local-platform-1
```

**Then you must recreate `test-agent`, not just leave it running** — this
is the single most important operational gotcha in this whole document.
`test-agent` uses `network_mode: "service:platform"`, which binds it to
the *specific platform container instance* it started next to. Restarting
`platform` — even `docker start` on the same, un-removed container —
breaks `test-agent`'s network namespace reference; `librdkafka` inside it
then fails DNS resolution for `kafka:9092` until it is recreated:

```bash
docker rm -f ai-platform-local-test-agent-1
cd infrastructure/compose
docker compose --profile app up -d test-agent
```

After a platform crash, whether the recovering platform consumes the
Agent's backlogged outcome before the workflow's 60-second result deadline
is a genuine race, not a bug — either a normal `COMPLETED` result, or a
`FAILED`/`TASK_RESULT_DEADLINE_EXCEEDED` result with the late outcome
safely recorded rather than corrupting the terminal state, is a correct
outcome. See `docs/sprint-6/progress.md` and
`docs/sprint-7/progress.md` for the full account.

### A new capability's Registry binding leaves every *other* Agent `UNAVAILABLE`

**Symptom**: after adding a new capability (a new `registry.json` binding
plus its revision bump) and recreating only the new Agent's container
(plus `test-agent`/`dashboard` for the netns gotcha above), `GET
/api/v1/agents` shows the *new* capability and `text.word-count` (backed
by the freshly recreated `test-agent`) as `READY`, but every
already-running Agent from a previous deployment (e.g.
`summarize-agent`/`review-agent`/`ui-review-agent`) as `UNAVAILABLE` —
found live during `architecture.review`'s deployment (ADR-0020), which
added a fifth binding and bumped the revision from `local-compose-5` to
`local-compose-6`.

**Cause**: each Agent snapshots `registry.json`'s `revision` once, at its
own process startup (`runtime/composition.py`'s
`load_agent_deployment_declaration`), and reports it in its
`/health/ready` payload's `declaration_revision` field.
`AgentReadinessClient.refresh` (`runtime/readiness.py`) requires that
field to equal `platform`'s *own* current `registry.revision` exactly, or
it classifies the observation `UNAVAILABLE` regardless of the Agent's
actual health. `platform` picks up the new revision on every restart, but
an Agent container left running from before the bump has no reason to
reload `registry.json` — restarting `platform` alone is what surfaces the
mismatch, since it starts comparing against the new revision immediately.

**Fix**: after any commit that bumps `registry.json`'s `revision`,
restart (not just recreate the new one) *every* already-running Agent
container so each re-reads the file at its own startup:

```bash
docker compose restart summarize-agent review-agent ui-review-agent
# ...and any other previously deployed Agent container; a plain restart
# is sufficient here (no netns to repair, unlike test-agent/dashboard).
```

### Adding a new Kafka principal to an already-provisioned broker

`kafka/entrypoint.sh` seeds every principal's SCRAM credentials via
`kafka-storage.sh format --add-scram`, but that command only runs against
an *unformatted* KRaft log directory — `--ignore-formatted` makes it a
no-op on every subsequent container start, which is exactly what you want
for the principals that already existed when the volume was first
formatted. It is **not** what you want the first time you add a brand new
principal (e.g. a new capability's `-producer`/`-consumer` pair) to a host
whose `kafka-data` volume already exists: adding the new `--add-scram`
line to `entrypoint.sh` and restarting the `kafka` container has no
effect, and the new Agent fails to start with a `SASL authentication
error: ... invalid credentials`, easy to misread as a wrong-password bug
in the new secret file rather than a broker-side gap (found live during
ADR-0019's `ui-review-agent` deployment).

Fix it by adding the credential dynamically instead, against the live
broker, using the existing `admin` principal:

```bash
docker exec ai-platform-local-kafka-1 /opt/kafka/bin/kafka-configs.sh \
  --bootstrap-server kafka:9092 --command-config /tmp/admin-client.properties \
  --alter --add-config 'SCRAM-SHA-256=[password=<the new principal's password>]' \
  --entity-type users --entity-name <the new principal's username>
```

(`/tmp/admin-client.properties` already exists inside the `kafka` container
from `entrypoint.sh`'s own setup — regenerate it first if the container was
recreated since.) This only matters for a host with pre-existing data; a
genuinely fresh `kafka-data` volume seeds every principal, including brand
new ones, correctly on its first format.

## 5. Provider-call outcome reconciliation (ADR-0016)

[ADR-0016](../architecture/decisions/ADR-0016-provider-call-claim-reconciliation.md)
resolved *when* a redelivered `text.summarize` command is quarantined
instead of retried forever (once its own `agent.provider_call_claims` row
is still unresolved after `maximum_processing_attempts`), and *how* the
workflow itself reaches a terminal state (the Orchestrator's ordinary
`DeadlineReconciler`, not a new mechanism). It deliberately left the
*operator procedure* for the resulting evidence as follow-up work — this
section is that follow-up, and every command and query below was run
against a real, live-produced case during Sprint 10, not written from the
code alone (see `docs/sprint-10/progress.md`).

### What you're looking for

A `task_attempt_id` where:

- `agent.provider_call_claims` has a row (a provider call was claimed), but
- `agent.completed_receipts` has **no** matching row (the claim was never
  resolved to a completed/failed outcome), and
- the Orchestrator's `orchestrator.workflows` row for that attempt reached
  a terminal state anyway (almost always `FAILED` /
  `TASK_RESULT_DEADLINE_EXCEEDED`, since nothing ever resolved the claim).

This is ADR-0014 Section 5's "unknown outcome" case: the provider call may
have completed and billed on the provider's side, or it may genuinely have
never happened — the Agent's own database cannot tell you which. This
procedure gets you the evidence to check the provider's own dashboard;
resolving *that* ambiguity is still a manual, out-of-band step (ADR-0016's
"Negative" consequences say this plainly — no automated reconciliation
exists or is planned).

### Step 1 — find candidate attempts

Run as the `postgres` administrator (read-only; this query touches both
the `orchestrator` and `agent` schemas in the same database, so it does
not need cross-service correlation):

```bash
docker exec ai-platform-local-postgres-1 psql -U postgres -d ai_platform -c "
SELECT
    ta.task_attempt_id,
    ta.capability_name,
    ta.state           AS attempt_state,
    w.workflow_id,
    w.state             AS workflow_state,
    w.failure_code,
    pcc.command_message_id,
    pcc.claimed_at
FROM orchestrator.task_attempts ta
JOIN orchestrator.tasks t      ON t.task_id = ta.task_id
JOIN orchestrator.workflows w  ON w.workflow_id = t.workflow_id
JOIN agent.provider_call_claims pcc ON pcc.task_attempt_id = ta.task_attempt_id
LEFT JOIN agent.completed_receipts cr ON cr.task_attempt_id = ta.task_attempt_id
WHERE cr.task_attempt_id IS NULL
  AND w.state = 'FAILED';
"
```

Each row is one attempt to investigate. Verified during Sprint 10 by
directly inserting a real `DISPATCHED` workflow/task/attempt with an
already-past `task_result_deadline` plus a matching unresolved
`agent.provider_call_claims` row, then waiting for the *real*
`DeadlineReconciler` (running inside `platform-1` on its normal periodic
interval, no test-only code path) to expire it — this query returned
exactly that attempt, with `workflow_state = FAILED` and
`failure_code = TASK_RESULT_DEADLINE_EXCEEDED`, confirming both the query
and the real expiry path it depends on.

### Step 2 — confirm whether the command was quarantined

A `task_attempt_id` from Step 1 may or may not also have a quarantined
command (retries can still be in flight, or the process could have been
killed before `maximum_processing_attempts` was reached). Check the
`summarize-agent`'s transport rejections:

```bash
docker exec ai-platform-local-postgres-1 psql -U postgres -d ai_platform -c "
SELECT rejection_id, safe_failure_code, quarantine_state, recorded_at
FROM agent.transport_rejections
ORDER BY recorded_at DESC
LIMIT 20;
"
```

`agent.transport_rejections` has no `task_attempt_id` column — quarantine
happens at the transport layer, which does not always have a parsed
command available (a malformed message may never even become one). To
confirm a specific `rejection_id` corresponds to the `task_attempt_id`
from Step 1, read the actual quarantined message from the
`.quarantine` topic (`ai-platform.development.task-commands.text-summarize.v1.quarantine`)
and decode its envelope:

```bash
docker exec ai-platform-local-kafka-1 bash -c '
admin_pw=$(cat /run/secrets/kafka_admin_password)
cat > /tmp/admin-client.properties <<EOF
security.protocol=SASL_PLAINTEXT
sasl.mechanism=SCRAM-SHA-256
sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="admin" password="$admin_pw";
EOF
/opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 \
  --consumer.config /tmp/admin-client.properties \
  --topic ai-platform.development.task-commands.text-summarize.v1.quarantine \
  --from-beginning --max-messages 20 --timeout-ms 8000
'
```

(`--timeout-ms` makes the consumer exit on its own once it has drained
whatever is currently on the topic, rather than hanging forever waiting
for a 20th message that may not exist; a `TimeoutException` logged after
the messages print is expected, not a failure.)

Each line is one quarantine envelope (`record_type: "transport-quarantine"`,
`src/ai_platform/adapters/event_bus/quarantine.py`'s `_quarantine_envelope`).
Match `rejection_id` against Step 2's query output, then base64-decode
`original.bytes_base64` (present when the original message was small
enough to retain) and parse it as the `ExecuteTask` command JSON to read
its `task_attempt_id` and confirm it matches Step 1's candidate. Verified
during Sprint 10 against a real quarantined message (a deliberately
malformed command produced directly to the topic): the envelope's
`rejection_id` matched the corresponding `agent.transport_rejections` row
from Step 2 exactly, and `original.bytes_base64` decoded to the exact
bytes produced.

### Step 3 — check the provider's own record

Once you have a confirmed `task_attempt_id`, its idempotency key with the
provider is the value itself (`AICompletionRequest`'s per-call idempotency
binding — see ADR-0014 Section 5). Check the Anthropic/OpenAI dashboard or
billing export for a request carrying that key to determine whether the
call actually completed. This is the manual step ADR-0016 does not
automate; there is no platform-side tooling for it.

## 6. Shutdown and cleanup

Graceful stop (containers can be restarted later, data persists in named
volumes):

```bash
cd infrastructure/compose
docker compose --profile app stop platform test-agent
docker compose stop postgres kafka
```

Full teardown (removes containers **and data volumes** — irreversible for
anything not durably needed):

```bash
cd infrastructure/compose
docker compose --profile app down
docker compose down -v
```

Remove the generated local secrets (they regenerate on the next
`generate-secrets.sh`/`generate-app-secrets.sh` run, with new random
values — anything relying on the old values, like an already-issued DSN,
would need to be reissued):

```bash
rm -rf infrastructure/compose/secrets
```

## 7. Troubleshooting

### Historical: Windows/WSL2/Podman host-forwarding unreliability (resolved by migration)

Through Sprint 10, this topology ran on the developer's own Windows machine
via Podman Desktop's WSL2 integration. `docker ps`-equivalent (`podman ps`)
would show `postgres`/`kafka` as `(healthy)`, but any tool connecting to
`localhost:5433`/`localhost:19093` from the host would time out or hang.
Diagnosed in detail during Sprint 7 (`docs/sprint-7/progress.md`) as
layered: stale `nftables` NAT rules inside the Podman machine, the Windows
WSL2 Hyper-V Firewall silently dropping forwarded container ports, and —
even after both fixes — inconsistent protocol-handshake-level failures on
direct connections that were never fully root-caused. A deeper investigation
on 2026-08-09 (while containerizing the dashboard) traced the remaining
failures to Podman Desktop's `gvproxy` vsock tunnel itself being broken —
every published port (`8000`, `8080`, `8100`, not just the dashboard) was
affected, with no manual `netsh portproxy` workaround possible once
`gvproxy` was down.

**Resolution**: rather than continue chasing this, the topology was moved
2026-08-12 to a dedicated Docker host — a Mac running Docker Desktop at
`192.168.1.123` (see Section 1). Docker Desktop for Mac binds published
ports to real host network interfaces; this class of failure has not
recurred. `run-in-network.sh` (running tests from inside a throwaway
container on the compose network, sidestepping host-forwarding entirely)
and this document's use of `docker exec` for the loopback-only endpoints
predate the migration but remain correct on the new host too — see
[tests/integration/README.md](../../tests/integration/README.md).

### `test-agent` can't reach Kafka after a platform restart

**Symptom**: `test-agent`'s logs show `Failed to resolve 'kafka:9092':
Temporary failure in name resolution` after `platform` was restarted.

This is the `network_mode: "service:platform"` gotcha described in
[Section 4](#4-recovery--demonstrated-crash-scenarios). Recreate
`test-agent` (`docker rm -f` + `docker compose --profile app up -d
test-agent`); a plain restart will not fix it.

### New workflow submissions return `503`

**Symptom**: `POST /api/v1/workflows` returns
`503 AGENT_TEMPORARILY_UNAVAILABLE`.

New submissions check current Agent readiness before creating a workflow
(existing workflow reads and replay remain available regardless). This is
expected if `test-agent` was just (re)started — the platform's readiness
cache refreshes on a bounded interval
(`AI_PLATFORM_AGENT_READINESS_REFRESH_INTERVAL_SECONDS`, 5 seconds in this
deployment); wait a few seconds and retry.

**If it's `text.summarize` and waiting does not help**, this is a
different, structural gap found during Sprint 10, not a transient cache
lag: `AI_PLATFORM_AGENT_READINESS_URL` is one fixed URL per platform
process, and it only ever actually reaches `test-agent` (via the
`network_mode: "service:platform"` trick described above).
`summarize-agent` runs in its own separate container/network namespace and
is never reachable at that URL, so its readiness is never observed and
every `text.summarize` submission gets `AGENT_TEMPORARILY_UNAVAILABLE`
regardless of how long you wait — see `docs/sprint-10/progress.md` for the
full root-cause account. Not fixed as of this writing; it needs a design
decision (per-binding readiness URLs? routing through the Registry's own
binding data?), tracked as Sprint 10 workstream 3.

## 8. Security limitations

Everything below is a known, accepted, and documented limitation of this
**local development deployment** — not a defect list, and none of it is a
production-readiness claim:

- **`LocalDevelopmentAuthorizationPolicy`** resolves every caller to one
  synthetic principal. There is no per-developer attribution, no real
  authentication, and no isolation between callers. Never treat this as
  production-ready (see `PROJECT_BRIEF.md` Section 9,
  `docs/architecture/decisions/ADR-0010-security-identity-authorization-and-trust-boundaries.md`).
- **Loopback-only application exposure** is intentional for `platform` and
  any Agent sharing its network namespace: `AI_PLATFORM_API_HOST` and
  `test-agent`'s readiness host are validated as loopback literals
  (`src/ai_platform/runtime/configuration.py`), and `platform`/`test-agent`
  share one network namespace for exactly this reason. The host-published
  `8000`/`8100` ports in `infrastructure/compose/docker-compose.yml` are
  not reachable from outside the container by design on this host's
  network backend — see [infrastructure/README.md](../../infrastructure/README.md).
  An Agent in its own network namespace (`summarize-agent`) cannot use
  this pattern at all — a loopback bind there is only reachable from
  inside that Agent's own container, never from `platform`'s, which needs
  to query its readiness (ADR-0017 Decision 5) — so it instead binds every
  interface (`AI_PLATFORM_AGENT_READINESS_HOST=0.0.0.0`) and is reached at
  its Compose service DNS name (`summarize-agent:8100`, see
  `infrastructure/compose/runtime/registry.json`). This is still not a
  public exposure: the isolated Compose network itself is not reachable
  from the host, and every readiness request still requires the shared
  bearer credential — "internal-network-only, credential-gated" rather
  than "loopback-only" for this specific case.
- **No TLS** anywhere in this local topology — PostgreSQL and Kafka
  traffic is unencrypted `SASL_PLAINTEXT`/plain TCP within the isolated
  compose network.
- **Single-node, single-broker** — no replication, no high availability,
  no tolerance for a single machine failure.
- **Locally generated, file-based secrets** (`infrastructure/compose/secrets/`,
  git-ignored) — there is no secrets-management platform integration.
- **Multi-principal authorization and owner-mismatch disclosure paths are
  structurally unreachable** under the current single-principal policy and
  are not implemented — this cannot be exercised in this deployment at
  all, not just untested.
- **The Kafka producer/consumer-group/quarantine *authorization* proof**
  for deployment readiness remains an open architectural question (flagged
  in Sprint 6, unchanged): metadata reachability is checked at startup,
  but not that the configured principal actually holds the required
  produce/consume/quarantine permissions.

## 9. Contract generation

**Not implemented.** No contract code-generation tooling exists in this
repository (explicitly deferred since Phase 2 and still open — see
`PROJECT_BRIEF.md` Section 8). Canonical contracts under `contracts/`
(JSON Schema, OpenAPI, AsyncAPI) are hand-maintained; there is no
generator, validator-generator, or client-generation command to document
here.

## 10. Validation commands

Local quality gates (no live services required):

```bash
uv run ruff format --check .
uv run ruff check .
uv run basedpyright
uv run pytest -q
```

Real-service validation (requires the topology from Section 1 up and
reachable; see [tests/integration/README.md](../../tests/integration/README.md)).
Run directly, from an SSH session on the Docker host or from a developer
machine with `infrastructure/compose/secrets/` copied down — a single
command now covers the full suite, including `test_recovery.py` (this used
to require a two-command split to work around Windows/WSL2/Podman
host-forwarding flakiness; see Section 7's historical note):

```bash
uv run pytest -m external_service tests/integration/ -v
```

`test_recovery.py` kills and restarts the real `platform`/`test-agent`
containers as part of the test itself; its two tests race narrow, genuinely
timing-dependent windows (the same races described in
[Section 4](#4-recovery--demonstrated-crash-scenarios)), so an occasional
failure from a too-fast or too-slow crash window on a given run is a known,
accepted flake in this suite, not a sign the environment is broken — rerun
once if either test fails.

## 11. Autonomous Agent Operations (ADR-0026/ADR-0028/ADR-0030/ADR-0031/ADR-0032/ADR-0033)

`scrum-master-agent` was the first Agent deployable that takes real,
autonomous write actions with no per-action human approval;
`product-owner-agent` (ADR-0030) is the second; `principal-developer-agent`
(ADR-0031, real PR merge rights) is the third and highest-blast-radius;
`frontend-specialist-agent`/`postgres-specialist-agent` (ADR-0033,
review-only, no merge, path-filtered to their own domain) are the fourth
and fifth. All five share the exact same `agent.autonomous_*` tables
(migration 0009) via their own `role='...'` rows, and the same
independent, DB-backed safety mechanisms. All commands below run against
those tables via `docker exec` into the running `postgres` container,
the same pattern Section 3/5 already use.

**Most of this is now also visible in the dashboard's "Autonomous Agents"
tab (ADR-0032)** — kill switch state, each role's today-budget usage, and
recent audit-log entries, via `GET /api/v1/autonomous-agents`. The `psql`
commands below remain the only way to see a full audit row (`inputs`/
`result_detail` are deliberately not exposed by that endpoint) or to
engage/disengage the kill switch — the dashboard is read-only.

**`principal-developer-agent` is deployed with a placeholder credential
only (ADR-0031 Decision 5)** — it cannot merge anything real until the
repository owner replaces `github_token_principal_developer.txt` with a
real PAT, a deliberate, separate decision from every other role's
credential rollout.

### Checking whether the kill switch is engaged

```bash
docker exec ai-platform-local-postgres-1 psql -U postgres -d ai_platform \
  -c "SELECT engaged, updated_at FROM agent.autonomous_kill_switch;"
```

### Engaging the kill switch (halts all autonomous action-taking immediately)

No redeploy needed — every autonomous role's `PeriodicService` checks
this platform-wide flag at the start of every cycle, before any GitHub
call. Engaging it halts all five roles (`scrum-master-agent`,
`product-owner-agent`, `principal-developer-agent`,
`frontend-specialist-agent`, `postgres-specialist-agent`) together, not
one at a time — this is the fastest way to stop a real merge from
happening if `principal-developer-agent` is ever running with a real
credential:

```bash
docker exec ai-platform-local-postgres-1 psql -U postgres -d ai_platform \
  -c "UPDATE agent.autonomous_kill_switch SET engaged = TRUE, updated_at = now();"
```

Disengage the same way with `engaged = FALSE`.

### Checking today's budget usage

```bash
docker exec ai-platform-local-postgres-1 psql -U postgres -d ai_platform \
  -c "SELECT role, day, actions_used, spend_cents_used FROM agent.autonomous_role_budget ORDER BY day DESC LIMIT 7;"
```

Filter with `WHERE role = 'scrum-master'` or `WHERE role = 'product-owner'`
to check one role in isolation — each role's daily cap is tracked and
enforced independently, not shared. `spend_cents_used` is an estimate
from a hardcoded per-model rate table
(`src/ai_platform/agents/_autonomous_shared.py`), not exact provider
billing (ADR-0028 Decision 2) — treat `actions_used` against
`AI_PLATFORM_AGENT_AUTONOMOUS_MAX_ACTIONS_PER_DAY` as the primary signal.

### Reading "what did it actually do" — the audit log

```bash
docker exec ai-platform-local-postgres-1 psql -U postgres -d ai_platform \
  -c "SELECT occurred_at, action_type, target, result_status, result_detail FROM agent.autonomous_actions ORDER BY occurred_at DESC LIMIT 20;"
```

One row per attempted action, win or lose, append-only — this is the
after-the-fact record ADR-0026 Decision 7 relies on since there is no
per-action human checkpoint. `inputs` (jsonb) holds the full proposed
action fields including the model's own stated `rationale`. Add
`WHERE role = '...'` to see one role's actions only.
