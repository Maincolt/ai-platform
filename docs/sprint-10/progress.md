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

## Workstream 2: ADR-0016 operator runbook (done)

Added `docs/operations/README.md` Section 5 ("Provider-call outcome
reconciliation (ADR-0016)"), closing the gap ADR-0016's own "Negative"
consequences flagged: no operator runbook existed for correlating a
quarantined `text.summarize` command against an expired workflow by
`task_attempt_id`. Every command and query in it was run against real,
live-produced evidence during this session, not written from the code
alone:

- The Step 1 correlation query (`orchestrator.task_attempts` JOIN
  `orchestrator.workflows` JOIN `agent.provider_call_claims` LEFT JOIN
  `agent.completed_receipts`) was verified against a real case: a
  directly-inserted `DISPATCHED` workflow/task/attempt with an
  already-past `task_result_deadline` plus a matching unresolved
  `agent.provider_call_claims` row, expired for real by the *actual*
  `DeadlineReconciler` running inside `platform-1` (not a test-only code
  path) -- the query returned exactly that attempt, `workflow_state =
  FAILED`, `failure_code = TASK_RESULT_DEADLINE_EXCEEDED`.
- The Step 2 quarantine-envelope inspection (`kafka-console-consumer.sh`
  against the `.quarantine` topic, decoding `original.bytes_base64`) was
  verified against a real quarantined message: a deliberately malformed
  command produced directly to `summarize-agent`'s command topic, which
  the real running `summarize-agent` container actually quarantined
  (`agent.transport_rejections` gained a real `MALFORMED_JSON` row); the
  envelope's `rejection_id` matched that row exactly and the decoded bytes
  matched what was sent.
- Synthetic rows inserted for verification were deleted afterward; the one
  real quarantine event was left in place as genuine historical evidence,
  consistent with how the rest of this dev topology already accumulates
  real data.

Not reproduced live: the exact crash race ADR-0016 describes (a redelivery
finding its *own* unresolved claim, via `ProviderCallReconciliationPendingError`).
That specific timing window is the same class of fragile, host-dependent
race `test_recovery.py` already struggles with on this host (see
workstream 1's findings above); the runbook's correlation procedure is
verified against realistic real evidence instead, which is what an
operator actually needs regardless of how the evidence was produced. Also
added a Section 8 troubleshooting note explaining that `text.summarize`'s
`503` is not the same transient-cache-lag issue `test-agent` has -- it is
the structural readiness-URL gap from workstream 1, which waiting does not
fix.

## Workstream 3: ADR-0014 follow-up decisions (ADR drafted and Accepted)

The four remaining ADR-0014 Section 8 open questions split into
engineering-scoped and repository-owner decisions, as the sprint plan
anticipated. The repository owner was asked directly rather than any of
them being resolved unilaterally:

- **Orchestrator-level AI Router invocation**: stays out of scope
  (Agent-only, as today) -- closed for now, reopenable given a real use
  case.
- **Fallback ordering**: cross-provider immediately on failure, ratifying
  `FallbackAIRouter`'s existing behavior (no code change needed -- it
  already never retries the same provider).
- **Model allowlist**: formalized (`claude-haiku-4-5`,
  `gpt-5-mini`), to be enforced at startup by `_build_ai_router`. Not yet
  implemented -- follow-up PR.
- **Retry-budget numbers**: Compose `retry_delay_seconds` raised 0.5->2
  (attempts stay at 5), giving `text.summarize` a ~10-second bounded
  window before a genuinely in-flight provider call gets quarantined,
  instead of ~2.5 seconds. The shared-config architecture limitation
  ADR-0016 already flagged (one value across every consumer, not
  per-capability) remains open -- raising the default is a compromise,
  not a fix.

Also resolved, though not one of ADR-0014's original five: the
multi-agent readiness-routing gap this workstream's own finding above
surfaced. Decision: move `readiness_url` from a single
`PlatformRuntimeConfig` value to a per-binding field on
`CapabilityBinding`, validated at Registry-load time. Not yet implemented
-- follow-up PR, same as the model allowlist.

Recorded in [ADR-0017](../architecture/decisions/ADR-0017-ai-router-follow-up-decisions.md),
marked directly Accepted (not Proposed) per this repository's own ADR
process note ("Proposed unless the decision has already been explicitly
accepted") -- the repository owner's answers were the acceptance.
`PROJECT_BRIEF.md`'s "What's next" section was updated to match.

## Workstream 4: second Phase 7 slice -- submission idempotency against the real database

Added `tests/integration/test_submission_idempotency.py` (2 tests):
Section 19's "One workflow per complete key" row, specifically the
persistence-level arbitration mechanism itself
(`PsycopgOrchestratorPersistence.commit_submission` relying on a real
PostgreSQL `PRIMARY KEY`/`UNIQUE` constraint on
`orchestrator.accepted_requests`), which was proven at the component/API
level with in-memory ports but never against the real constraint that
actually does the arbitration. `test_concurrency.py` covers duplicate
command/duplicate result/deadline race, not this first-acceptance row.

- Sequential resubmission of the same `AcceptedRequestKey`: second commit
  resolves to the first's already-durable workflow (`created=False`,
  same `workflow_id`), and real row counts confirm exactly one
  `orchestrator.workflows`/`accepted_requests` row exists between the two
  candidate identifiers -- the second workflow was never persisted.
- Concurrent first acceptance (`asyncio.gather`, two separate connection
  pools): exactly one of the two real, independent commits wins, both
  results agree on the same winner, and again exactly one workflow row
  exists -- decided by the real constraint under real transaction
  serialization, not by coroutine scheduling order in this process.

Both run against the live topology (`67 passed, 2 skipped`, up from `65`).

## ADR-0017 implementation: multi-agent readiness routing (Decision 5)

Implements the fix for the readiness gap workstream 1 found:
`text.summarize` submissions got `AGENT_TEMPORARILY_UNAVAILABLE` forever
because the platform could only ever reach one Agent process.

- `CapabilityBinding` gains a `readiness_url: str` field, validated as a
  well-formed `http(s)` URL with a hostname at Registry-load time
  (`runtime/loading.py`) -- deliberately *not* loopback-only, since
  `summarize-agent`'s real address is its own Compose service DNS name.
- `AI_PLATFORM_AGENT_READINESS_URL` removed from `PlatformRuntimeConfig`
  entirely; `runtime/composition.py`'s `refresh_agent_availability()` now
  builds one `AgentReadinessClient` per distinct `readiness_url` across
  the Registry's bindings instead of one shared client, and looks up each
  binding's own client when refreshing it.
- `infrastructure/compose/runtime/registry.json` gains a `readiness_url`
  per binding (`test-agent`: `http://127.0.0.1:8100/health/ready`,
  unchanged reachability; `summarize-agent`:
  `http://summarize-agent:8100/health/ready`, its real Compose DNS name).

**A second, deeper bug found while implementing** (not anticipated by the
ADR text as originally accepted): routing to `summarize-agent:8100` only
works if something is listening there. `summarize-agent`'s readiness
server was still bound to `AI_PLATFORM_AGENT_READINESS_HOST=127.0.0.1`
like every other Agent -- but unlike `test-agent`, it does not share
platform's network namespace, so a loopback bind is only reachable from
*inside its own container*. Verified directly: a one-off container on the
Compose network got `Connection refused` (not a DNS failure) connecting
to `summarize-agent:8100` before this was fixed. `AgentRuntimeConfig`'s
loopback-only validation was relaxed to also accept `0.0.0.0` (bind every
interface), and `summarize-agent`'s Compose service now binds it. Still
not a public exposure: the Compose network itself is not reachable from
the host, and every readiness request still requires the shared bearer
credential. ADR-0017 and `docs/operations/README.md`'s security-limitations
section were both corrected to describe this accurately (the ADR
originally said `readiness_url` would be loopback-validated, which turns
out to be impossible for `summarize-agent`'s real address -- corrected in
place per this repository's "correct minor errors without changing the
decision's meaning" ADR-immutability rule).

**Live-verified**, not just unit/component-tested:
- A one-off `podman run` (not part of the persistent compose lifecycle)
  confirmed `load_registry_artifact` parses both bindings' distinct
  `readiness_url` values, and that composition's per-URL client-building
  logic produces exactly 2 distinct clients from them.
- The running platform process's own logs show
  `GET http://127.0.0.1:8100/health/ready` **and**
  `GET http://summarize-agent:8100/health/ready` both returning `200 OK`
  in the same refresh cycle.
- A real `POST /api/v1/workflows` submission for `text.summarize` got
  `202 DISPATCHED` (workflow/task/attempt/outbox committed) -- previously
  always `503 AGENT_TEMPORARILY_UNAVAILABLE` regardless of wait time. This
  is the fix's actual functional proof: the readiness gate that was
  wrongly blocking every `text.summarize` submission no longer does.
- `text.word-count` (the capability using the *unchanged* loopback/shared-netns
  path) continued working throughout, confirming no regression to the
  already-working case.
- The full `external_service` suite: `67 passed, 2 skipped` (unchanged).
- Full local suite: `449 passed`; `ruff check .` and `basedpyright` both
  clean.

**Not cleanly demonstrated**: the submitted workflow's own completion
(reaching a real provider-call failure, as originally anticipated) --
this environment's `platform` container hit the same pre-existing,
already-documented Windows/Podman restart-latency flakiness repeatedly
during this session (`PLATFORM_SHUTDOWN_INCOMPLETE`, no application
exception, consistent with the unexplained host issue
`PROJECT_BRIEF.md`/`docs/operations/README.md` already describe), which
interrupted the outbox publisher before the command could reach
`summarize-agent`, and the workflow reached `FAILED`/
`TASK_RESULT_DEADLINE_EXCEEDED` instead. This is host instability
unrelated to the readiness fix, not a flaw in it -- the fix's own claim
(readiness observed, submission dispatched) is independently verified
above by direct evidence, not inferred from this workflow's fate.

## ADR-0017 implementation: model allowlist (Decision 3)

Implements the last unimplemented piece of ADR-0017: `text.summarize` is
approved for exactly `claude-haiku-4-5` (Anthropic) and `gpt-5-mini`
(OpenAI); any other configured model now fails startup closed rather than
silently reaching a real provider call.

- `runtime/composition.py` gains `_APPROVED_ANTHROPIC_MODELS`/
  `_APPROVED_OPENAI_MODELS` frozensets and a
  `_require_approved_ai_router_model` helper used in `_build_ai_router`
  in place of the previous unchecked `_require_ai_router_str` calls for
  the two model fields specifically -- other `str` config fields are
  unaffected.
- `infrastructure/compose/docker-compose.yml`'s `summarize-agent` service
  updated from the placeholder `claude-3-5-haiku-20241022`/`gpt-4o-mini`
  values to the approved `claude-haiku-4-5`/`gpt-5-mini`.

**Live-verified**:
- A one-off container confirmed the exact approved-model frozensets are
  what's actually compiled into the image.
- A direct `_build_ai_router` call with `claude-3-5-haiku-20241022`
  (the *old* placeholder value) raised `UNAPPROVED_AI_ROUTER_MODEL`
  as expected; the same call with `claude-haiku-4-5` succeeded.
- `summarize-agent` restarted cleanly with the corrected Compose model
  values (no `RuntimeConfigurationError` at startup).
- A real `text.summarize` submission against the corrected deployment
  again got `202 DISPATCHED` (both this fix and the readiness fix working
  together); the same pre-existing host restart flakiness described above
  again prevented observing the workflow's own later completion -- not
  a flaw in either fix, same caveat as before.
- Full local suite: `450 passed` (one new test,
  `test_build_ai_router_fails_closed_on_an_unapproved_model`); `ruff
  check`/`ruff format --check`/`basedpyright` all clean.

This closes out ADR-0017 -- all five decisions are now both Accepted and
implemented.

## Phase 7 continuation: Idempotency/Ownership-disclosure + State machine against the real database

Two more Section 19 slices picked up, both real-database extensions of
already-thoroughly-tested application-layer logic
(`tests/component/`, `tests/unit/orchestrator/domain/`):

**`tests/integration/test_accepted_request_ownership_and_replay.py`** (6
tests): `AcceptedRequestQueryPort.resolve()` read-after-write and clean
miss; `AcceptedRequestAccessAuditPort.record_request_access()` durably
persisting each of the three `AcceptedRequestAccessDisposition` values
with correct evidence, without mutating the original accepted
request/workflow; `AuthorizedWorkflowQueryPort.get_authorized()`'s real
safe-not-found guarantee (a workflow that genuinely exists, invisible to
a caller resolved to the wrong owner, proven against the real query, not
an in-memory `==`); and Section 19's "Same ID in two scopes" row (the
same `request_id` under two different `idempotency_scope_id` values
produces two fully independent workflows).

**`tests/integration/test_workflow_state_machine_persistence.py`** (3
tests): `orchestrator.workflow_history` round-trips every transition in
the correct order (not just the latest state); a terminal transition via
`apply_terminal_outcome` appends to that history rather than replacing
it; and `orchestrator.workflows`' own `workflows_terminal_payload_check`
CHECK constraint genuinely rejects a direct SQL write that claims a
terminal state without its required payload -- proving the schema itself
defends this invariant, not just application code. (One authoring bug
caught and fixed in the second test: `causation_message_id` must match
the original command's real outbox `message_id`, not a fresh random ID
-- `apply_terminal_outcome`'s `_matches_attempt` check correctly rejected
the mismatch with `PERMANENT_CONFLICT` until fixed, which is itself a
small confirmation that check is doing its job.)

Both files run against the live topology: `76 passed, 2 skipped` (up
from `73`, up from `67` before this sprint's re-validation started). Full
local suite unaffected: `450 passed`; `ruff`/`ruff format`/`basedpyright`
all clean.

## Phase 7 continuation: Inbox/outbox claim fencing against the real database

`tests/integration/test_outbox_claim_fencing.py` (2 tests): the two
Inbox/outbox rows `test_recovery.py`/`test_concurrency.py` do not
directly exercise.

- **Claim fencing**: two publisher processes racing `claim_next` for the
  same eligible outbox row must have exactly one winner. A real
  reliability bug was caught and fixed while writing this test, not just
  in the implementation being tested: `claim_next` orders by
  `created_at`/`message_id` with `FOR UPDATE SKIP LOCKED` (no blocking)
  across the *whole* shared `logical_channel` -- on this shared dev
  database, which had accumulated `NOT_ATTEMPTED` rows from every other
  `commit_submission` call across this sprint's other test files (none of
  which run a real `OutboxPublisherWorker` to drain them), two racers
  could each cleanly claim a *different* pre-existing row without ever
  contending for this test's own row, making the assertion pass without
  actually testing the race. Fixed by giving each test invocation a
  dedicated, UUID-suffixed `logical_channel`, so this test's single row
  is the only eligible candidate and the race is real. Verified reliable
  by running the file twice in a row (not a one-off pass).
- **Duplicate/changed payload identity**: `orchestrator.outbox.message_id`
  is a real `PRIMARY KEY` -- confirmed a second insert claiming the same
  identity with different payload bytes is rejected by the database
  itself (`UniqueViolation`), not merely discouraged by convention.

Runs against the live topology: `78 passed, 2 skipped` (up from `76`).

## Phase 7 continuation: Contract category audit against Section 19

Reviewed `tests/contract/` (5 files, 24 tests: JSON Schema validity,
OpenAPI validity, AsyncAPI validity, examples-conform-to-schemas,
`task_completed` result discrimination) plus
`tests/component/api/test_workflow_api.py::test_submit_invalid_body_returns_400_problem_details`
against Section 19's Contract category bullet list. Conclusion: this
category is substantially covered, with one genuine gap found --
`src/ai_platform/runtime/ids.py`'s `Uuid7IdentifierFactory` (the concrete
implementation satisfying both the Orchestrator and Agent ID ports) had
zero test coverage anywhere in the repo (`grep -rln
"Uuid7IdentifierFactory" tests/` returned nothing).

Added `tests/unit/runtime/test_ids.py` (4 tests, pure/local -- no real
service needed for this one): `new_id()` returns a well-formed UUID
string; it is genuinely version 7 (`uuid.UUID(value).version == 7`,
correct RFC 4122 variant); 1000 successive calls are all distinct; and
1000 successive calls sort in the same order they were generated --
UUIDv7's defining time-ordered property, and Python 3.14's `uuid.uuid7()`
holds it in practice, not just in principle.

Full local suite: `454 passed` (4 new, up from `450`); `ruff check`/`ruff
format --check`/`basedpyright` all clean.

## Phase 7 continuation: Audit/observability -- scope conclusion

Assessed Section 19's Audit/observability category against a real
telemetry backend, the same treatment given to the other categories this
sprint. Conclusion: **not extendable with a real `external_service`
test in this codebase, because no real telemetry backend exists to
integrate against.**

`src/ai_platform/shared/observability.py` defines `OperationalSignalsPort`
with exactly two implementations: `NoOpOperationalSignals` (the default,
discards everything) and `RecordingOperationalSignals` (an in-process
list-based recorder used only by tests to verify signal semantics). There
is no Prometheus/OTel/StatsD exporter, no `src/`-side wiring of either
implementation into `runtime/composition.py`, and only
`runtime/publisher.py` calls the port at all. There is nothing running in
this topology -- Compose, `docker-compose.yml`, or otherwise -- that a
real-backend test could assert against; writing one would mean either (a)
standing up a telemetry backend that doesn't exist anywhere else in this
project's infrastructure, which is out of scope for a test-coverage audit,
or (b) re-testing `RecordingOperationalSignals` against itself, which
adds no real-service confidence beyond what `tests/unit/shared/test_operational_signals.py`
already provides.

This category is therefore already adequately covered at the unit level
and is marked closed for Section 19 purposes without new test files.

## Phase 7 continuation: Correlation Normalization -- real Kafka-message-level propagation

`tests/unit/api/test_correlation.py` and
`tests/component/api/test_workflow_api.py` already thoroughly prove the
Correlation Normalization Scenarios table's validation/discard/generate
rules and the HTTP response header (missing/valid/malformed/oversized/
control-character header, replay, uniqueness); neither proves the
"Propagation" column's claim that a valid correlation_id genuinely
reaches a real downstream `ExecuteTask` command message, since both stop
at the HTTP boundary or an in-memory/real-database commit.

Added `tests/integration/test_correlation_propagation.py` (1 test): builds
one real submission carrying a known correlation_id, commits it via
`PsycopgOrchestratorPersistence.commit_submission` against the real
database, reads back the *durable* outbox row's `payload_bytes` (not the
in-memory dict the test already trusts), publishes exactly those bytes
through the real `KafkaEventPublisher` to the real capability-scoped
`text.word-count` command topic, consumes the message back with a raw
Kafka consumer, and asserts the correlation_id (and workflow_id) in the
bytes that actually reached the broker match, and that the message
validates against the canonical `ExecuteTask` JSON Schema.

One reliability bug found while writing this test, the same shape as the
one already documented in the Inbox/outbox claim-fencing test above:
initially the test drove a real `OutboxPublisherWorker.run_once()` call
against the shared `task-commands` logical_channel, but `claim_next`
correctly claimed and published an unrelated *older* backlog row left
over from other tests instead of this test's own row, so the assertion
correctly failed (no matching message ever appeared on the topic within
the poll budget). Fixed by bypassing the shared claim scoping for this
test -- it publishes the durable row it just committed directly, since
claim/publish correctness itself is already proven by
`tests/integration/test_outbox_claim_fencing.py`; this test's job is only
the correlation_id's propagation into the real message bytes.

Runs against the live topology: `79 passed, 2 skipped` (up from `78`).
Full local suite unaffected: `454 passed`; `ruff check`/`ruff format
--check`/`basedpyright` all clean.

## Workstream 4: Phase 7 Section 19 -- final status

> This section summarizes the whole workstream, including the Contract
> (`Uuid7IdentifierFactory`), Audit/observability (scope conclusion), and
> Correlation Normalization (`test_correlation_propagation.py`) slices,
> each of which landed as its own PR alongside this one -- see those PRs'
> own progress.md entries above for their individual details.

This closes out this sprint's pass through Sprint 7's deferred Section 19
categories (`docs/sprint-7/plan.md` "Out of scope"). Summary of the whole
workstream, this entry included:

**Closed this sprint** (real-`external_service` tests against the live
PostgreSQL/Kafka topology unless noted, each its own PR):

- **Agent selection/readiness**: wire-contract coverage
  (`tests/component/runtime/test_agent_readiness_wire_contract.py`, 7
  tests, component-level) plus the live multi-agent readiness-routing fix
  itself (per-binding `readiness_url`, corrected readiness-host bind),
  proven with a real `202 DISPATCHED` `text.summarize` submission.
- **Idempotency**: sequential/concurrent first-acceptance against the
  real `accepted_requests` UNIQUE constraint
  (`test_submission_idempotency.py`, 2 tests).
- **Ownership/disclosure**: `resolve()`/`record_request_access()`/
  `get_authorized()` safe-not-found/same-ID-two-scopes against the real
  database (`test_accepted_request_ownership_and_replay.py`, 6 tests).
- **State machine**: `workflow_history` round-trip/terminal-append/CHECK
  constraint rejection against the real database
  (`test_workflow_state_machine_persistence.py`, 3 tests).
- **Inbox/outbox**: claim fencing and duplicate-message-identity
  rejection against the real `FOR UPDATE SKIP LOCKED`/`PRIMARY KEY`
  mechanisms (`test_outbox_claim_fencing.py`, 2 tests).
- **Contract**: audited `tests/contract/` (24 tests) and the Problem
  Details component test against the checklist; found and closed one
  genuine gap, `Uuid7IdentifierFactory` (`tests/unit/runtime/test_ids.py`,
  4 tests, pure unit -- no real service needed for a deterministic ID
  generator).
- **Correlation Normalization**: the table's "Propagation" column's claim
  that a valid correlation_id reaches a real downstream command message,
  proven at the real Kafka byte level
  (`test_correlation_propagation.py`, 1 test).

**Assessed and closed without new tests** (real-backend testing is not
meaningful, not merely not-yet-done):

- **Audit/observability**: no telemetry backend exists anywhere in this
  codebase to test against -- only `NoOpOperationalSignals` and an
  in-process `RecordingOperationalSignals` recorder, already covered at
  the unit level. Writing an `external_service` test here would mean
  standing up infrastructure that doesn't otherwise exist in this
  project, or re-testing the recorder against itself.

**Still genuinely open, not attempted this sprint**:

- A dedicated pytest-automated full-container End-to-End harness
  (`docs/sprint-7/plan.md`'s other deferred item). This is a
  meaningfully different piece of work -- driving the actual `platform`/
  `test-agent`/`summarize-agent` Compose services as black boxes over
  HTTP, not exercising adapters/application services directly against
  real backing services the way every `tests/integration/` file above
  does -- and was not scoped into this sprint's workstream 4.
- Security boundary and Recovery/crash window are not re-listed above
  because Sprint 7 already automated them in full
  (`test_postgres_role_isolation.py`, the 24-case Kafka ACL matrix,
  `test_secret_redaction.py`, `test_audit_failure_rollback.py`,
  `test_recovery.py`); this sprint only re-ran them against the
  re-validated topology (workstream 1), it did not extend them.
- Event Bus delivery was already covered by Sprint 7
  (`test_event_bus_delivery.py`); not revisited beyond re-running it here.

**Net for this workstream**: the live `external_service` suite grew from
`65 passed, 2 skipped` (workstream 1's topology re-validation baseline,
before any of this workstream's own additions) to `79 passed, 2 skipped`
-- fourteen new tests across six categories (Idempotency 2, Ownership/
disclosure 6, State machine 3, Inbox/outbox 2, Correlation Normalization
1, matching this workstream's own idempotency-then-readiness-fix slice's
`65 -> 67` plus everything listed above's `67 -> 79`), all live-verified,
three with a genuine bug found and fixed along the way (a test-authoring
bug in the state-machine test, a claim-scoping reliability bug in both
the outbox-fencing and correlation-propagation tests). The full local suite
grew from `450` to `454` (the four `Uuid7IdentifierFactory` unit tests;
everything else in this workstream is `external_service`-only and does
not add to the local-suite count). Every addition landed as its own PR,
lint/type-check/test-verified before merge, per this sprint's established
pattern.
