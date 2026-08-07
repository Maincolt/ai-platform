# Operations — Local Deployment

> Scope: the local `infrastructure/compose/` deployment only (Podman-managed
> PostgreSQL 17 + Apache Kafka 3.9 + the `platform`/`test-agent`
> application containers). **This document makes no production-readiness
> claim.** Every command below has been independently re-run against a
> real local environment during Sprint 8 (see
> [docs/sprint-8/done.md](../sprint-8/done.md)) — nothing here is
> aspirational or copied without re-verification.
>
> For the full topology design (roles, ACLs, secrets, why each piece is
> shaped the way it is), see [infrastructure/README.md](../../infrastructure/README.md).
> This document is the operator-facing "how do I actually run and check on
> this thing" companion to that design document.

## 1. Setup

From a clean checkout, on a host with Podman installed:

```bash
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
podman compose up -d postgres kafka
podman compose up postgres-init kafka-init

# 3. Build the application image (from the repository root)
cd ../..
podman build -f infrastructure/Dockerfile -t ai-platform:sprint6 .

# 4. Start the platform and Test Agent
cd infrastructure/compose
podman compose --profile app up -d platform test-agent
```

`postgres-init`/`kafka-init` are one-shot jobs (`restart: "no"`) — they
exit after running; that is expected, not a failure. Re-running step 2 is
safe (migrations and topic/ACL creation are idempotent).

**Known gotcha on Windows/WSL2 + Podman**: bringing the topology up and
verifying it are two different things on some hosts — see [Section
7](#7-troubleshooting).

## 2. Health

The platform and Test Agent expose readiness endpoints, but — by design
(loopback-only exposure, see [Section 8](#8-security-limitations)) — they
are not reachable from the host. Check them via `podman exec`:

```bash
# Platform readiness (aggregates database, event bus, registry, runtime checks)
podman exec ai-platform-local-platform-1 python3 -c "
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=5) as r:
    print(r.status, r.read().decode())
"
# Expect: 200 {"status":"ready"}

# Platform liveness (always succeeds once the process is up)
podman exec ai-platform-local-platform-1 python3 -c "
import urllib.request
with urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=5) as r:
    print(r.status, r.read().decode())
"
# Expect: 200 {"status":"alive"}
```

Container-level health for PostgreSQL and Kafka:

```bash
podman ps --format "{{.Names}} {{.Status}}"
# postgres and kafka should show "(healthy)"; platform/test-agent show
# "Up ..." only -- they have no podman-level HEALTHCHECK, so readiness
# must be checked via the endpoints above.
```

Kafka consumer group health (useful for confirming the Test Agent is
actually attached and not lagging):

```bash
podman exec ai-platform-local-kafka-1 bash -c '
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
via `podman exec`, exactly as validation did in Sprints 6–7:

```bash
podman exec ai-platform-local-platform-1 python3 -c "
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
podman exec ai-platform-local-platform-1 python3 -c "
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

## 4. Recovery — demonstrated crash scenarios

Both scenarios below were proven in Sprints 6–7, including running the
platform-crash scenario multiple times to confirm both sides of a genuine
timing race resolve safely (see
[docs/sprint-7/done.md](../sprint-7/done.md)). The automated versions are
`tests/integration/test_recovery.py`; the commands below are the manual
equivalent for an operator.

### Test Agent crash

```bash
podman kill ai-platform-local-test-agent-1
# A workflow submitted just before this point stays DISPATCHED while the
# Agent is down -- it is not lost.
podman start ai-platform-local-test-agent-1
# Uncommitted Kafka work is redelivered once the Agent reconnects; the
# workflow reaches COMPLETED with no duplicate receipt/outcome.
```

### Platform crash

```bash
podman kill ai-platform-local-platform-1
# The Agent keeps working independently and publishes its outcome even
# while the platform is down.
podman start ai-platform-local-platform-1
```

**Then you must recreate `test-agent`, not just leave it running** — this
is the single most important operational gotcha in this whole document.
`test-agent` uses `network_mode: "service:platform"`, which binds it to
the *specific platform container instance* it started next to. Restarting
`platform` — even `podman start` on the same, un-removed container —
breaks `test-agent`'s network namespace reference; `librdkafka` inside it
then fails DNS resolution for `kafka:9092` until it is recreated:

```bash
podman rm -f ai-platform-local-test-agent-1
cd infrastructure/compose
podman compose --profile app up -d test-agent
```

After a platform crash, whether the recovering platform consumes the
Agent's backlogged outcome before the workflow's 60-second result deadline
is a genuine race, not a bug — either a normal `COMPLETED` result, or a
`FAILED`/`TASK_RESULT_DEADLINE_EXCEEDED` result with the late outcome
safely recorded rather than corrupting the terminal state, is a correct
outcome. See `docs/sprint-6/progress.md` and
`docs/sprint-7/progress.md` for the full account.

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
podman exec ai-platform-local-postgres-1 psql -U postgres -d ai_platform -c "
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
podman exec ai-platform-local-postgres-1 psql -U postgres -d ai_platform -c "
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
podman exec ai-platform-local-kafka-1 bash -c '
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
podman compose --profile app stop platform test-agent
podman compose stop postgres kafka
```

Full teardown (removes containers **and data volumes** — irreversible for
anything not durably needed):

```bash
cd infrastructure/compose
podman compose --profile app down
podman compose down -v
```

Remove the generated local secrets (they regenerate on the next
`generate-secrets.sh`/`generate-app-secrets.sh` run, with new random
values — anything relying on the old values, like an already-issued DSN,
would need to be reissued):

```bash
rm -rf infrastructure/compose/secrets
```

## 7. Troubleshooting

### Windows/WSL2/Podman: containers healthy but unreachable from the host

**Symptom**: `podman ps` shows `postgres`/`kafka` as `(healthy)`, but any
tool connecting to `localhost:5433`/`localhost:19093` from the host times
out or hangs.

This was diagnosed in detail during Sprint 7 (`docs/sprint-7/progress.md`)
as layered:

1. Stale/duplicate `nftables` NAT rules inside the Podman machine from
   earlier container recreations, sometimes routing to a defunct
   container IP. Fixed by fully removing and recreating the containers
   and network (`podman compose down` then `up` again) so netavark
   regenerates clean rules.
2. The Windows WSL2 Hyper-V Firewall silently dropping forwarded container
   ports even when everything inside the WSL VM is correct. Fixed on this
   host with `netsh interface portproxy` plus an explicit
   `netsh advfirewall firewall add rule` allow rule for the affected
   ports.
3. Even after both fixes, direct connections from Windows-native
   processes can still be **inconsistent**: a bare TCP connect can
   succeed while the actual protocol handshake hangs. This is not fully
   understood and does not have a further fix documented here.

**Working around it**: for automated tests,
`tests/integration/run-in-network.sh` runs the test process from inside a
throwaway container on the compose network instead of through the host,
sidestepping the host-forwarding path entirely — see
[tests/integration/README.md](../../tests/integration/README.md). For
manual operator commands, this document uses `podman exec` throughout
instead of connecting to host-published ports, for the same reason.

### `test-agent` can't reach Kafka after a platform restart

**Symptom**: `test-agent`'s logs show `Failed to resolve 'kafka:9092':
Temporary failure in name resolution` after `platform` was restarted.

This is the `network_mode: "service:platform"` gotcha described in
[Section 4](#4-recovery--demonstrated-crash-scenarios). Recreate
`test-agent` (`podman rm -f` + `podman compose --profile app up -d
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

Real-service validation (requires the topology from Section 1; see
[tests/integration/README.md](../../tests/integration/README.md) for the
two-command split this host's networking requires). On Git Bash on
Windows, `run-in-network.sh`'s `podman run -v` volume mount is silently
mangled by MSYS path conversion unless `MSYS_NO_PATHCONV=1` is set first:

```bash
export MSYS_NO_PATHCONV=1  # Git Bash on Windows only; harmless elsewhere
bash tests/integration/run-in-network.sh -v
uv run pytest -m external_service tests/integration/test_recovery.py -v
```

Expect `65 passed, 2 skipped` from the first command (the 2 skips are
`test_recovery.py`, which cannot run inside that throwaway container — see
below) and `2 passed` from the second. `test_recovery.py` kills and
restarts the real `platform`/`test-agent` containers as part of the test
itself; the two tests race narrow, genuinely timing-dependent windows (the
same races described in [Section 4](#4-recovery--demonstrated-crash-scenarios)),
so an occasional failure from a too-fast or too-slow crash window on a
given run is a known, accepted flake in this suite, not a sign the
environment is broken — rerun once if either test fails.
