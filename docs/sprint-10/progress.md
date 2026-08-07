# Sprint 10 — Progress

> Workstream 1 (topology re-validation) and the start of workstream 4
> (Phase 7 continuation) as of 2026-08-07.

## What was done

1. Regenerated/confirmed local Compose secrets (already present, including
   the `summarize-agent-producer`/`summarize-agent-consumer` Kafka pair
   from Sprint 9).
2. Brought PostgreSQL/Kafka up, applied migrations `0001`-`0007` and topic/
   ACL bootstrap against a genuinely clean volume (previous topology
   predated Sprint 9 and only had `0001`/`0002` applied).
3. Rebuilt the application image (`ai-platform:sprint6`) from current
   `main`.
4. Started `platform`, `test-agent`, and `summarize-agent` (the last never
   brought up in this environment before) together for the first time.
5. Ran the full `external_service` suite via
   `tests/integration/run-in-network.sh`: **65 passed, 2 skipped**
   (`test_recovery.py`'s two tests, which require the `podman` CLI directly
   and cannot run inside the network-sandbox container).
6. Ran `test_recovery.py` directly on the host per its own documented
   fallback path.

## Bugs found and fixed (all merged into this branch's changes)

### 1. `init-postgres.sh` was not actually idempotent

`docs/operations/README.md` Section 1 claims "Re-running step 2 is safe
(migrations and topic/ACL creation are idempotent)." True for `0001`/`0002`
(CREATE-style, `IF NOT EXISTS` guarded) but false for `0003`-`0007`, which
do plain `ALTER TABLE ... RENAME`/type-change/`ADD COLUMN` with no
existence guard. Any `podman compose up` that has `platform`/`test-agent`/
`summarize-agent` as a dependency re-triggers the one-shot `postgres-init`
job regardless of a prior successful run in an earlier invocation, so this
broke on the very first attempt to bring the app services up after the
database was already migrated once.

**Fix**: `infrastructure/compose/scripts/init-postgres.sh` now gates every
migration behind a `schema_version` check (`apply_migration` skips a file
once the component's recorded version already meets its target). Verified
by running `podman compose up postgres-init kafka-init` twice in a row
against the same database: first run applies all seven migrations, second
run skips all seven ("schema already at version N >= target").

### 2. `tests/integration/` itself was stale against Sprint 9's changes

Three files constructed `AsyncPsycopgPool` without `expected_schema_version`
(defaulting to `1`), which is now `3`/`4`. Two files (`test_kafka_acl_matrix.py`,
`test_smoke.py`) referenced the pre-ADR-0014 non-capability-scoped
`task-commands.v1` topic, which `init-kafka.sh` no longer provisions.
`test_event_bus_delivery.py`'s two direct-publish/consume tests used
`default_topic_mapping()` for `TASK_COMMANDS`, which still computes the
old bare topic name — real submissions never hit this because
`KafkaEventPublisher._resolve_topic` overrides it with capability-scoped
routing whenever `capability_name`+`environment` are set, but these two
tests did neither.

**Fix**: added `EXPECTED_ORCHESTRATOR_SCHEMA_VERSION`/`EXPECTED_AGENT_SCHEMA_VERSION`
constants (conftest.py, plus local copies in the three affected test files
-- a cross-file import turned out to need `tests/__init__.py`, which
doesn't exist and wasn't worth adding just for this); updated the ACL
matrix and smoke test to the real capability-scoped topics and added the
`summarize-agent-producer`/`summarize-agent-consumer` principals and their
isolation cases (agent-consumer denied on the summarize topic and vice
versa -- this is the actual ACL-level proof of ADR-0014 Section 6's
isolation guarantee, which the suite never exercised before); gave the two
raw publish/consume tests a dedicated capability-scoped topic mapping and
set `capability_name` on their messages.

All fixes are `tests/integration/`- and `infrastructure/compose/scripts/`-only;
no `src/` changes were needed for either bug.

## A real `text.summarize` submission: what actually happened

Per the sprint plan, one real submission was attempted against the live
topology:

```
POST /api/v1/workflows {"capability": "text.summarize", ...}
-> 503 AGENT_TEMPORARILY_UNAVAILABLE
   "No eligible Agent is currently ready for this capability."
```

This is **not** the anticipated outcome (a provider-call failure from the
placeholder Anthropic/OpenAI credentials). The submission never reached
Agent selection at all. Root cause, confirmed by reading the code and the
platform's own readiness-refresh logs:

- `PlatformRuntimeConfig` has exactly one `readiness_url`
  (`AI_PLATFORM_AGENT_READINESS_URL`), and `AgentReadinessClient` is
  constructed once with that single fixed URL.
- `refresh_agent_availability()` (`runtime/composition.py`) loops over
  *every* Registry binding and calls `readiness_client.refresh(...)` for
  each -- but every call hits the same URL regardless of which
  agent/capability it's nominally checking.
- For `test-agent`, this URL (`http://127.0.0.1:8100/health/ready`) works
  by a container-networking trick: `test-agent`'s Compose service sets
  `network_mode: "service:platform"`, so it shares platform's network
  namespace and is genuinely reachable at `127.0.0.1:8100` from inside the
  platform container.
- `summarize-agent`, added in Sprint 9, is a normal separate container
  (its own network namespace, reachable at `summarize-agent:8100` on the
  Compose network) -- it does **not** use the `network_mode: "service:platform"`
  trick (the docker-compose.yml comment at the `test-agent` block even
  notes "that trick is test-agent-specific"). So every readiness refresh
  for the `text.summarize` binding queries `test-agent`'s endpoint, not
  `summarize-agent`'s, and `summarize-agent`'s availability is never
  observed as `READY` -- `CachedAgentAvailability` has no entry for it,
  and `RegistryCandidateSelector` correctly reports
  `AGENT_TEMPORARILY_UNAVAILABLE`.

This is a real, previously-unexercised architecture gap from Sprint 9: the
Compose topology and the single-readiness-URL platform config were never
actually validated together with a second Agent process reachable at a
real submission. **Not fixed in this pass** -- it needs a design decision
(per-binding readiness URLs? a URL template keyed by
`agent_id`/`implementation_identity`? routing through the Registry's own
binding data instead of one config value?) rather than a quick patch, and
belongs with the ADR-0014 follow-up workstream, not silently patched here.

## What's still open in Sprint 10

- Workstream 1's acceptance criterion ("submission attempted, outcome
  recorded") is satisfied -- but the outcome recorded is this readiness
  gap, not a provider-call failure. Whether to treat *that* as Sprint 10
  scope (fix the readiness wiring) or hand it to workstream 3 (ADR-level,
  since it's a genuine multi-agent config design question) needs a call.
- `test_recovery.py` remains flaky on this host in a way consistent with
  the already-documented, not-fully-understood Windows/WSL2/Podman
  restart-latency gap (`podman compose up -d test-agent` alone timed out
  at 30s during one restart attempt). Not investigated further -- explicitly
  out of scope per PROJECT_BRIEF.md's existing acknowledgment of this gap.
- Workstreams 2 (operator runbook) and 3 (ADR-0014 follow-ups) not yet
  started. Workstream 4 (Phase 7 continuation) has started; see below.

## Workstream 4: Phase 7 continuation (started)

Added `tests/component/runtime/test_agent_readiness_wire_contract.py` (7
tests, local/component -- no external service, no Docker): the Section 19
"Agent selection/readiness" category's `AgentReadinessClient` and
`create_agent_readiness_app` each already had thorough *unit* coverage
(`tests/unit/runtime/test_runtime_readiness.py`), but only in isolation --
the client's tests feed it hand-built fake JSON via `httpx.MockTransport`,
never the server's real response bytes, and the server's tests never
involve the client at all. The two halves had never been proven to agree on
the wire contract between them. This closes that gap using
`httpx.ASGITransport` (same mechanism `TestClient` uses) to pair the real
client against the real app without a real socket: ready/fresh, draining,
not-yet-ready, the real 404 identity-hiding disguise resolving to
UNAVAILABLE (not a crash or UNKNOWN), a redeployed agent's changed
declaration digest correctly failing closed, TTL expiry against a real
refreshed-then-aged observation, and the never-refreshed-capability UNKNOWN
default.

This directly relates to the workstream 1 finding above: it proves the
readiness *plumbing itself* is correct in isolation, which is exactly why
that finding is a wiring/config gap (one fixed URL can't reach two Agent
processes) rather than a correctness bug in either component.

**Still open in Section 19** (not attempted this pass; each is its own
scoped slice, not a single remaining task):

- **Contract**: substantially covered already by `tests/contract/`
  (JSON Schema/OpenAPI/AsyncAPI validity, examples, result discrimination)
  -- worth an explicit audit against the Section 19 bullet list rather than
  assuming full coverage, but not re-done here.
- **Persistence/transaction** beyond what Concurrency/Recovery/Audit-rollback
  already exercise (composite uniqueness, history/snapshot parity against
  the real database specifically).
- **Idempotency**: the fingerprint/replay matrix is covered at the
  API/component level with in-memory ports (`tests/component/api/`); the
  same guarantees have never been proven against the real Postgres adapter.
- **Ownership/disclosure**: owner-mismatch/safe-404 is covered at component
  level; not against the real database.
- **Inbox/outbox**: claim fencing, unknown publication, duplicate/changed
  payload identities, retention/replay boundaries beyond what Recovery/
  Concurrency already touch.
- **State machine**: every legal edge, illegal/late/conflicting events,
  terminal immutability, history revisions -- against the real database
  specifically (thoroughly covered already at the domain/component level
  with in-memory fakes).
- **Audit/observability** beyond the one audit-failure-rollback scenario
  Sprint 7 automated: signal correlation, bounded labels, trace links,
  telemetry-failure isolation.
- **Correlation Normalization Scenarios** (Section 19's second table, 12
  rows): only a handful covered at the component level via `TestClient`;
  the rows about propagation "through supported logs, traces, audit,
  command, and events" need real message-level proof, not just the API
  response.
- A true End-to-End pytest-automated full-container harness (Sprint 6/7
  both proved the underlying behavior by hand; automating the full
  container lifecycle under pytest remains unstarted).
