# Vertical Slice 01: Deterministic Single-Agent Workflow

- **Status:** Architecture-aligned implementation plan
- **Implementation status:** Not started
- **Architecture review date:** 2026-07-28
- **Implementation readiness:** Blocked only by the Accepted-ADR conflict in
  [Section 24](#24-unresolved-architectural-blocker)

## 1. Purpose and Authority

Vertical Slice 01 is the smallest complete execution path that proves the
platform can accept, persist, dispatch, execute, recover, and disclose one
workflow without calling an AI model or performing an external side effect.

All Accepted ADRs are authoritative. Later explicit amendments take precedence
over the clauses they supersede. In particular, ADR-0011 replaces only the
global `request_id` assumptions in ADR-0004 and ADR-0006; their other decisions
remain binding.

This document is subordinate to:

- [ADR-0001 through ADR-0011](../architecture/decisions/README.md);
- the [platform architecture](../architecture/README.md);
- the [platform test strategy](../testing/README.md);
- the repository [security policy](../../SECURITY.md); and
- the repository [Agent guidance](../../AGENTS.md).

### What the Slice Proves

The slice proves this exact path:

1. a client submits one workflow request;
2. the API applies the accepted, constrained local-development security
   boundary and resolves trusted request context;
3. the Orchestrator arbitrates the scoped accepted-request identity;
4. accepted-request evidence, selection evidence, initial workflow state,
   immutable history, business audit, and an `ExecuteTask` outbox record commit
   atomically;
5. the command is published through the transactional outbox to the Event Bus;
6. one declared, compatible, ready Test Agent receives it;
7. the Agent validates and deduplicates the command;
8. the Agent executes deterministic `text.word-count` version `1.0`;
9. the Agent atomically stores its completed receipt, outcome, terminal event,
   and event outbox;
10. the terminal event is published through the Agent's durable boundary;
11. the Orchestrator validates and deduplicates the event;
12. workflow state, immutable transition history, result, and required audit
    commit atomically;
13. the client retrieves the durable outcome under current authorization; and
14. durable audit plus correlated logs, metrics, and traces explain the path.

It specifically proves:

- one workflow per complete accepted-request key;
- actor, owner, scope, and request identity separation;
- PostgreSQL-enforced concurrency and transactional integrity;
- at-least-once transport with exactly-once logical effects where defined;
- inbox, outbox, deadline, and restart recovery;
- deterministic capability selection and execution;
- authorization before acceptance, replay disclosure, and retrieval; and
- observability that does not become a source of business truth.

## 2. Bounded Scope

The slice contains:

- one HTTP Workflow API;
- one Orchestrator;
- one configuration-backed Capability Registry;
- one logical Test Agent deployment;
- one deterministic capability, `text.word-count` `1.0`;
- one workflow, one task, and one task attempt per accepted submission;
- the `ExecuteTask`, `TaskCompleted`, and `TaskFailed` message contracts;
- PostgreSQL with Orchestrator-owned and Agent-owned persistence boundaries;
- a Kafka-protocol Event Bus adapter and a local Redpanda broker;
- transactional outbox publishers in the owning component processes;
- local-development authorization and readiness verification;
- structured logs, OpenTelemetry-compatible metrics and traces, and durable
  business/security audit; and
- local, test-owned validation across the documented test levels.

The Workflow API, Orchestrator, Registry, outcome consumer, deadline
reconciler, and Orchestrator outbox publisher may share one platform process
while remaining separate modules. The Test Agent is a separate process and
logical deployment. The Agent event-outbox publisher may share the Agent
process.

The slice has exactly one `task_id`, one `task_attempt_id`, and
`attempt_number = 1` per workflow. It does not implement an Orchestrator
application retry.

## 3. Architecture and Boundaries

```text
host-loopback HTTP
        |
        v
+---------------- Platform process ----------------+
| Workflow API -> Orchestrator -> Capability Registry|
|                       |                             |
|              workflow/outbox ports                 |
|                       |                             |
|       outcome consumer / outbox / recovery         |
+-----------------------+-----------------------------+
                        |
          +-------------+-------------+
          |                           |
          v                           v
 +----------------+            +----------------+
 | PostgreSQL     |            | Redpanda       |
 | orchestrator   |            | task-commands  |
 | owned schema   |            | task-outcomes  |
 +--------+-------+            +--------+-------+
          ^                             |
          | Agent-owned schema          v
          |                    +------------------+
          +--------------------| Test Agent       |
                               | receipt/outcome  |
                               | event outbox     |
                               +------------------+
```

Boundary rules:

- only the Orchestrator owns workflow state and transitions;
- the API owns HTTP concerns and trusted context construction, not workflow
  persistence or command publication;
- the Registry answers compatibility and eligibility; the Orchestrator's
  selection policy chooses the single candidate;
- the Agent owns capability execution and its accepted outcome, not workflow
  state, application retry, or selection;
- domain modules depend on platform ports, not PostgreSQL, Redpanda, Kafka, or
  framework types;
- the Event Bus is not the workflow system of record;
- Orchestrator and Agent data share one PostgreSQL service only through
  separate schemas, roles, migrations, and least-privilege credentials;
- the Orchestrator cannot read Agent business data and the Agent cannot read
  workflow data;
- consumer groups are transport mechanics, never Agent, producer, or logical
  consumer identity; and
- no database/Event Bus distributed transaction exists.

## 4. Security and Trusted Request Context

### Local-Development API Boundary

The first slice uses `LocalDevelopmentAuthorizationPolicy`. It has no client
credential and does not identify an individual human. The trusted security
adapter resolves every API call to:

- environment `development`;
- one synthetic, nonportable `local-development` principal;
- one synthetic `idempotency_scope_id`;
- `current_actor_id` for the synthetic principal;
- resolved owner intent for the same synthetic owner subject;
- policy identity and immutable policy revision; and
- the semantic operation configured for the endpoint.

The synthetic scope is internal, cannot be supplied or learned by a client, and
can never become a production scope. All callers within this boundary are
indistinguishable and share replay and ownership authority. The slice provides
no per-developer attribution or isolation.

The API's effective host exposure must be loopback-only. A container may listen
internally on a wildcard address only when host publication is restricted to
loopback, the container network is inaccessible to untrusted containers and
processes, and no proxy, forward, LAN, public, shared-host, production route, or
production credential exists. Startup fails closed when these conditions are
not provable.

### Identity Separation

The following values never collapse into one field:

| Identity | First acceptance | Replay or retrieval |
| --- | --- | --- |
| `idempotency_scope_id` | Trusted internal replay partition | Resolved from current trusted policy; never client supplied |
| `acceptance_actor_id` | Immutable copy of first call's `current_actor_id` | Never overwritten |
| `current_actor_id` | Actor of the accepting call | Resolved independently for every call |
| `accepted_owner_subject_id` | Immutable authorized owner intent | Compared with newly resolved owner intent |
| `current_owner_subject_id` | Initially the accepted owner | Controls current disclosure; stored separately |
| policy revision | Acceptance decision evidence | Current policy independently controls disclosure |
| `fingerprint_policy_version` | Immutable historical comparison profile reference | Used to evaluate replay under the exact historical semantic, canonicalization, and digest rules |

This slice has no ownership-transfer or scope-migration API. Its persistence
model nevertheless keeps accepted and current ownership separate so later
features do not require reinterpretation.

### Credential Boundaries

API, readiness, PostgreSQL, Event Bus, migration, and future telemetry
credentials are separate. Runtime processes never use owner, superuser,
broker-admin, migration, backup, or restore credentials.

The Agent readiness endpoint accepts only a generated, environment-scoped,
file-mounted development credential granting `readiness.query`. The Agent
authenticates the Orchestrator. The Orchestrator verifies the configured
loopback route, safe response contract, environment, `agent_id`, declaration
digest, freshness, and timeout. This is bounded development-only endpoint
verification; it does not cryptographically authenticate the Agent responder.

Secrets never appear in source, images, URLs, command lines, contracts,
Registry declarations, events, logs, traces, examples, or committed
configuration.

## 5. Workflow API Contract

The canonical JSON Schemas, OpenAPI 3.1.1 description, examples, and runtime
models must remain in parity. JSON uses UTF-8, the ADR-0004 naming and timestamp
rules, and RFC 9457 Problem Details.

| Semantic operation | Method and path | Behavior |
| --- | --- | --- |
| `workflow.submit` | `POST /api/v1/workflows` | `202` for first acceptance; `200` for authorized equivalent replay |
| `workflow.read` | `GET /api/v1/workflows/{workflow_id}` | Return currently authorized durable state/result |
| `health.live` | `GET /health/live` | Process liveness only |
| `health.ready` | `GET /health/ready` | Core/API readiness without treating Agent availability as global readiness |

The semantic operation is trusted configuration, not client input, URL text,
handler name, media type, or API version. Compatible routes or schema versions
must continue resolving to `workflow.submit`; they do not create a new
idempotency identity.

### Submit Request and Response

The submit body contains:

- optional client-created lowercase UUIDv7 `request_id`; the API creates and
  returns one when omitted;
- `text`, bounded by the canonical schema;
- capability name `text.word-count`; and
- capability version `1.0`.

The public success response contains only these public identifiers:

- `request_id`;
- `correlation_id`; and
- `workflow_id`.

It also contains the current workflow state and the safe public result or
failure fields that apply. It does not expose `task_id`, `task_attempt_id`,
`idempotency_scope_id`, actor or owner persistence references, policy or
fingerprint internals, Registry revisions, readiness evidence, audit evidence,
transport metadata, or credentials.

`GET` returns the same public identifiers, durable state, revision, permitted
timestamps, and either the deterministic result or safe terminal failure. It
authorizes before disclosure. Unauthorized and nonexistent workflows both use
the policy-selected safe `404 WORKFLOW_NOT_FOUND` response for this slice.

### Stable Errors

| Condition | Public result |
| --- | --- |
| Invalid JSON or schema/domain input | `400 INVALID_REQUEST` |
| Unsupported contract version | `400 UNSUPPORTED_CONTRACT_VERSION` |
| Authorized fingerprint conflict | `409 REQUEST_ID_CONFLICT` |
| Unauthorized replay disclosure | `404 WORKFLOW_NOT_FOUND` |
| Owner-intent mismatch | `404 WORKFLOW_NOT_FOUND`; internal classification remains hidden |
| Missing or unauthorized workflow | `404 WORKFLOW_NOT_FOUND` |
| No eligible Agent for a new request | `503 AGENT_TEMPORARILY_UNAVAILABLE`; no records created |
| Safe unexpected internal failure | `500 INTERNAL_PROCESSING_FAILURE`; caller reuses `request_id` |

Errors contain only the accepted Problem Details fields and safe bounded
details. The unresolved invalid `Correlation-Id` behavior is isolated in
Section 24 and must not be implemented until the ADR conflict is resolved.

## 6. Accepted-Request Arbitration and Replay

The database-enforced key is:

`(environment, operation, idempotency_scope_id, request_id)`.

Global lookup or global uniqueness by `request_id` is prohibited. A normal API
lookup starts with trusted environment, operation, and scope; it never searches
all scopes and filters afterward.

Before arbitration, the API security/application boundary:

1. resolves `current_actor_id`;
2. resolves environment and semantic operation;
3. resolves or atomically creates the durable synthetic scope mapping;
4. resolves owner intent;
5. authorizes the actor to submit for that owner under the current policy;
6. validates/defaults the semantic request;
7. resolves the stored `fingerprint_policy_version` and its complete historical
   profile for comparison; and
8. computes the SHA-256 digest of RFC 8785 canonical UTF-8 bytes.

The fingerprint includes exact decoded text, capability name/version, API
contract major, and future execution-semantic fields. It excludes property
order, JSON whitespace, headers, correlation, trace, and other transport data.

| Situation | Required behavior |
| --- | --- |
| First acceptance | Check a current eligible Agent, freeze selection intent, then atomically create one accepted request and workflow |
| Equivalent authorized replay | `200`; return existing public identifiers and current authorized state; do not check Agent readiness or create records |
| Equivalent unauthorized replay | Safe `404`; disclose nothing and create nothing |
| Fingerprint conflict | Safe `409` only when classification disclosure is authorized; otherwise safe `404`; create nothing |
| Owner-intent mismatch | Internal `OWNER_INTENT_MISMATCH`; safe `404`; return no workflow and create no duplicate |
| Same `request_id` in another scope | Independent request identity; it may create another workflow without discovering the first |
| Lost original response | Replay in the same resolved key returns the committed workflow after equivalence and authorization checks |
| Concurrent duplicate submission | Composite database uniqueness selects one winner; losers read that mapping and apply the same replay rules |
| Historical fingerprint profile unavailable | Fail closed with safe internal failure; never create another workflow |
| Required security audit unavailable | Deny protected disclosure; preserve the mapping and never create a duplicate |
| Optional replay telemetry unavailable | Return an otherwise authorized equivalent replay |

Credential rotation must preserve principal, scope, and owner resolution.
`current_actor_id` changes per call only when the authenticated actor actually
changes. Replay never changes immutable acceptance actor or accepted owner.

## 7. Capability Registry, Selection, and Readiness

### Declaration and Registry Snapshot

The Agent deployment owns a versioned declaration containing:

- manifest contract version;
- stable environment-scoped `agent_id`;
- Agent implementation identity and version;
- capability `text.word-count` `1.0`;
- exact accepted `ExecuteTask` versions; and
- exact produced `TaskCompleted` and `TaskFailed` versions.

Deployment configuration binds the declaration to the environment, creates its
declaration revision/digest, and supplies a separate readiness-routing binding.
The Orchestrator loads one complete trusted Registry artifact, validates
provenance and all bindings, rejects the entire revision on ambiguity or
conflict, and activates one immutable in-process snapshot. Restart is required
to change it.

### Distinct Readiness Signals

| Signal | Meaning |
| --- | --- |
| Process liveness | Process/event loop can make progress |
| Registry readiness | Complete trusted Registry revision is valid and active |
| Core/API readiness | Configuration, PostgreSQL, Event Bus adapters, Registry, and recovery workers are usable |
| Agent process readiness | Agent configuration, persistence, consumption, event publication recovery, declaration, and capability dependencies are usable; not draining |
| Deployment availability | Bounded readiness observation for the configured Agent |
| Capability eligibility | Declaration, compatibility, policy, and fresh availability all pass |
| Routing availability | Event Bus adapter can route the selected logical target |

Agent process readiness does not gate platform startup or workflow retrieval.
`/health/ready` does not fail merely because the Agent is unavailable.
Registry failure may make full readiness false while persistence-backed query
and authorized replay remain available.

For every new request, the availability adapter performs or reuses a fresh
bounded observation keyed by environment, `agent_id`, deployment declaration
digest, readiness-routing identity, and capability/contract set. `stale`,
`unknown`, `unavailable`, `draining`, mismatch, or timeout is ineligible.
Readiness caching has a short configured TTL and never extends a failed refresh.

Exactly one eligible candidate is required. Zero produces
`AGENT_TEMPORARILY_UNAVAILABLE` before workflow creation. More than one is a
configuration error in this slice. Selection is therefore deterministic; its
tie-break rule is “the only eligible candidate.”

Before the submission transaction, the Orchestrator freezes one immutable
selection intent containing:

- selected `agent_id`;
- capability name/version;
- implementation identity/version;
- selected command and event contract versions;
- complete Registry revision;
- deployment declaration revision/digest;
- selection-policy identity/version;
- availability classification and observation time/evidence reference; and
- semantic selection timestamp.

This exact evidence commits atomically with the workflow. Transaction retries
preserve it. Reselection occurs only after definitive noncommit and resolution
of any unknown commit outcome. Consumer-group membership is never selection or
readiness evidence.

## 8. Startup and End-to-End Sequence

### Platform Startup

1. validate typed nonsecret configuration and secret references;
2. initialize PostgreSQL and verify schema compatibility;
3. initialize Event Bus producer and outcome-consumer adapters;
4. load and atomically validate the complete Registry revision;
5. start Orchestrator outbox recovery, outcome consumption, deadline
   reconciliation, and recovery queries;
6. expose liveness;
7. expose core/API readiness when those dependencies are usable; and
8. serve workflow queries independently of Agent startup or availability.

No startup step waits for the Test Agent. Optional readiness prewarming is
nonblocking and cannot turn stale evidence into eligibility.

### Agent Startup

1. validate typed configuration and secret references;
2. initialize the Agent-owned PostgreSQL boundary and schema;
3. load and validate the deployment declaration against built-in capability
   metadata;
4. initialize required credentials and adapters;
5. start Agent event-outbox recovery before or alongside command intake;
6. initialize Event Bus consumption and assignment-fenced partition lanes;
7. start the bounded execution supervisor and authenticated readiness endpoint;
8. expose readiness only when the Agent can durably handle admitted work.

### Accepted Execution

1. the API validates the HTTP request and resolves trusted context;
2. the Orchestrator performs scoped replay arbitration;
3. only a new key performs Registry lookup and bounded Agent availability;
4. the Orchestrator freezes identifiers, timestamps, fingerprint intent,
   selection intent, and immutable command bytes;
5. the submission transaction commits the full integrity unit in Section 11;
6. the Orchestrator outbox publisher claims and publishes `ExecuteTask`;
7. Redpanda delivers the command at least once on `task-commands`;
8. the Agent validates transport, contract, producer context, target,
   capability, declaration, deadline, and command identity;
9. the Agent resolves any completed receipt, then admits work within bounded
   capacity;
10. it computes the deterministic result outside a database transaction;
11. the Agent outcome transaction commits receipt, outcome, event, outbox, and
    coupled audit;
12. the Agent acknowledges the command after that commit; event publication
    proceeds independently from the durable event outbox;
13. the Agent publisher publishes the stored terminal event on `task-outcomes`;
14. the Orchestrator validates the event and commits the result-consumption
    transaction;
15. the Orchestrator acknowledges the outcome after that commit; and
16. a currently authorized API read returns the durable terminal outcome.

## 9. Workflow State and Transition Model

The only workflow states are:

`RECEIVED -> PENDING -> DISPATCHED -> COMPLETED | FAILED`.

`COMPLETED` and `FAILED` are terminal. `DISPATCHED` means the immutable command
is durably in the Orchestrator outbox, not that the broker acknowledged it.
`task_result_deadline` is the maximum time for the Orchestrator to durably
accept `TaskCompleted` or `TaskFailed`; it is not a publish deadline.

The first three logical transitions commit in the one submission transaction.
They retain separate history entries and revisions even though no crash boundary
exists between them.

| Transition | Trigger and precondition | Atomic writes | Duplicate/invalid behavior | Recovery |
| --- | --- | --- | --- | --- |
| none -> `RECEIVED` | New authorized composite key, valid request, one eligible selected Agent | Accepted request, immutable identity/owner/actor/fingerprint evidence, workflow revision 1, history, selection/audit evidence | Composite conflict resolves as replay; no last-write-wins | Failure before commit leaves no records |
| `RECEIVED` -> `PENDING` | Same stable submission intent; task and attempt prepared | Task, attempt, snapshot revision 2, history | Cannot occur independently or be repeated | Same submission transaction |
| `PENDING` -> `DISPATCHED` | Immutable command prepared for selected target | Snapshot revision 3, history, command outbox, acceptance audit completion | Duplicate acceptance returns existing; illegal edge rejected | Outbox recovery publishes after commit |
| `DISPATCHED` -> `COMPLETED` | Valid, expected, first accepted `TaskCompleted` | Orchestrator inbox, task/attempt result, snapshot revision, history, mutation audit | Duplicate returns inbox disposition; late/conflict cannot mutate terminal state | Redelivery repeats no effect |
| `DISPATCHED` -> `FAILED` | Valid, expected, first accepted `TaskFailed` | Same result transaction with safe failure | Same as completion | Same as completion |
| `DISPATCHED` -> `FAILED` | Deadline reconciler wins workflow lock after `task_result_deadline` | Safe deadline failure, snapshot revision, history, coupled audit; outbox certainty retained | Concurrent event is serialized; loser is late | Restart scans expired nonterminal work |

Every transition checks expected state and revision, increments the revision,
uses a fixed semantic UTC timestamp, appends immutable history, and updates the
snapshot in one transaction. Illegal edges fail closed and create an observable
processing disposition. Duplicate and late events do not append duplicate
transition history.

The workflow aggregate lock determines a result/deadline race. In-memory receive
time cannot override committed state. A late Agent outcome remains diagnosable
and cannot reopen a terminal workflow.

## 10. Commands, Events, and Producer Identity

### Portable Contracts

Only these messages exist:

| Logical channel | Contract | Kind | Logical producer | Intended consumer |
| --- | --- | --- | --- | --- |
| `task-commands` | `ExecuteTask` | `command` | Orchestrator | selected Test Agent deployment |
| `task-outcomes` | `TaskCompleted` | `event` | Test Agent | Orchestrator |
| `task-outcomes` | `TaskFailed` | `event` | Test Agent | Orchestrator |

The ADR-0004 envelope contains `message_id`, `message_kind`, `contract_name`,
`contract_version`, `created_at`, `correlation_id`, nullable `causation_id`,
`workflow_id`, `task_id`, `task_attempt_id`, `producer`, and `payload`.
`request_id`, capability, selected Agent, `attempt_number`, input, and
`task_result_deadline` belong in the `ExecuteTask` payload.

`ExecuteTask` carries the exact text and selected capability/deployment
identity. `TaskCompleted` carries unchanged text, `word_count`, and the first
accepted `completed_at`. `TaskFailed` carries only a stable safe failure code,
bounded sanitized summary, and `failed_at`. Terminal events retain capability
and Agent implementation evidence required by their canonical payload schema.

The root command has `causation_id = null`. A terminal event uses the command
`message_id` as causation. The producer creates a lowercase UUIDv7
`message_id`; republication preserves identical bytes, IDs, timestamps, key,
and payload.

`workflow_id` is the UTF-8 Kafka record key. Ordering exists only within
`(logical_channel, workflow_id)`. There is no cross-channel or global order.

### Identity and Trust

These identities remain distinct:

- broker-authenticated transport principal, when the broker exposes it;
- environment-scoped deployment/component principal;
- logical envelope `producer.component` and process `instance_id`;
- target `agent_id`;
- message headers, including sanitized W3C trace context; and
- consumer-group membership.

Payload producer fields and headers are claims, never proof of transport origin.
The local broker deployment uses distinct credentials and ACLs so only the
Orchestrator can produce commands and only the Agent can produce outcomes.
When the broker does not expose a trustworthy producer principal to the
consumer adapter, the reduced guarantee is explicit: pre-delivery ACLs and a
trusted configured channel constrain origin, while consumers still validate
logical producer, target, environment, declaration, contract, and domain
relationships. The consumer must not claim per-message cryptographic producer
authentication.

## 11. Persistence and Transaction Boundaries

PostgreSQL is the source of truth. The initial topology uses one service with
separate Orchestrator and Agent schemas, roles, credentials, migrations, and
ports. Psycopg 3 is the selected client behind those ports. `READ COMMITTED` is
the default isolation level; constraints, short aggregate locks, revision
predicates, and retry of classified transaction failures enforce invariants.

### Scope-Mapping Boundary

The trusted security adapter atomically creates or resolves the synthetic
scope mapping before submission arbitration. It is a separate persistence
boundary. An unused mapping is harmless, grants no authority, and remains
reserved. It is not part of the workflow transaction.

### Submission Transaction

After validation, authorization, readiness, selection, and stable intent
construction, one transaction atomically:

1. creates or resolves the composite accepted-request key;
2. stores the immutable fingerprint and `fingerprint_policy_version` that
   resolves the complete historical profile;
3. stores `acceptance_actor_id`, immutable accepted owner, separate current
   owner, environment, policy decision/revision, scope-mapping revision, and
   safe authorization evidence;
4. creates workflow, task, and first attempt;
5. stores complete immutable selection evidence;
6. appends none -> `RECEIVED`, `RECEIVED` -> `PENDING`, and
   `PENDING` -> `DISPATCHED` history;
7. stores the current snapshot as `DISPATCHED`;
8. stores immutable `ExecuteTask` bytes in the Orchestrator outbox; and
9. stores mandatory coupled first-acceptance audit.

All commit or none commit. Database uniqueness, not process locking or an
existence precheck, arbitrates concurrent acceptance. Stable IDs, timestamps,
fingerprint input, selection intent, and bytes are fixed before transaction
retry. Unknown commit outcome is resolved by the complete key before generating
anything new.

### Agent Outcome Transaction

There is no durable pre-execution claim or `RUNNING` state. Execution occurs
outside a database transaction. After deterministic work, one Agent-owned
transaction:

1. creates or resolves the completed command receipt;
2. enforces one accepted outcome per `task_attempt_id`;
3. stores the outcome and first terminal timestamp;
4. stores one immutable `TaskCompleted` or `TaskFailed` event;
5. creates the Agent event-outbox row; and
6. stores required coupled Agent outcome audit.

Competing computations may occur before commit. Database uniqueness chooses one
durable outcome; losers load and reuse it or fail closed on content conflict.
This is one logical effect, not exactly-once computation.

### Result-Consumption Transaction

After complete contract and security validation establishes a trusted
`message_id`, one Orchestrator transaction:

1. locks or conditionally selects the workflow aggregate;
2. inserts or resolves
   `(logical_consumer_id, validated_message_id)`;
3. validates expected attempt, immutable identity, current revision, and legal
   transition;
4. records task and attempt result or safe failure;
5. updates the workflow snapshot;
6. appends immutable transition history;
7. stores any follow-up outbox row—none exists in this slice; and
8. stores mandatory coupled mutation audit.

Inbox disposition and all domain effects commit together. Broker
acknowledgement follows commit.

### Publication-State Transactions

Outbox claim, broker publication, and acknowledgment recording are separate:

1. a short transaction claims the earliest eligible record in
   `(logical_channel, workflow_id)` using an expiring fenced token;
2. broker publication occurs outside the database;
3. another short token-guarded transaction stores acknowledged, definitively
   not accepted, attempted/unknown, or classified failure state.

No network call occurs while holding a business transaction or long database
lock.

## 12. Transactional Outbox and Delivery

Both component outboxes:

- create immutable bytes, `message_id`, logical channel, `workflow_id` key, and
  creation sequence in the owning domain transaction;
- publish asynchronously with Kafka idempotent-producer support and `acks=all`
  under the local durability policy;
- retain mutable publication diagnostics separately from immutable content;
- use short `SKIP LOCKED` claims, expirations, and fencing tokens;
- preserve ordering within `(logical_channel, workflow_id)`;
- use bounded publication attempts and backoff per operating cycle;
- retain failed/poisoned rows visibly after exhaustion;
- block only the affected workflow/channel ordering scope; and
- require an authorized, audited terminal disposition before an unsafe record
  can be skipped or abandoned.

A row is delivered only when broker acknowledgment is durably recorded. A
publish-before-mark crash leaves publication outcome unknown. Recovery may
republish the exact bytes and create duplicate broker records; it never resets
unknown to “not attempted.” Consumer deduplication supplies one logical effect.

For an Orchestrator command whose deadline expires:

- definitive nonpublication permits atomic workflow failure and visible
  suppression while retaining the outbox;
- confirmed or unknown publication retains uncertainty and may republish the
  same command; any resulting Agent event is late after workflow failure.

Startup scans not-attempted, definitively-not-accepted, unknown, expired-claim,
and retryable-failed records. Shutdown stops new claims, finishes or relinquishes
in-flight claims within a bound, preserves unknown outcomes, and leaves all
unconfirmed records recoverable.

## 13. Inbox, Rejection, Retry, and Quarantine

### Agent Completed-Command Inbox

The Agent's durable logical inbox is its completed command receipt. Its identity
and conflict guards are:

- environment and logical Agent handler/deployment identity;
- `task_attempt_id`;
- command `message_id`; and
- SHA-256 digest of immutable command bytes.

Before execution, a lookup can resolve a completed receipt. It is not a durable
execution claim. The receipt commits only with outcome and event outbox.

| Condition | Behavior |
| --- | --- |
| Same attempt, message, and bytes | Return stored outcome and republish stored event if needed |
| Same attempt, different message | Permanent command conflict; never replace outcome |
| Same message, different bytes | Integrity failure and quarantine |
| No completed receipt | Deterministic execution may proceed |

Concurrent duplicates are arbitrated by PostgreSQL uniqueness. A crash before
the outcome transaction leaves no completed receipt and permits recomputation.
A crash after commit resolves the stored receipt and does not repeat the
logical effect.

### Orchestrator Outcome Inbox

The Orchestrator inbox key is:

`(environment, logical_consumer_id, validated_message_id)`.

`logical_consumer_id` is the stable outcome handler/subscription identity, not
a process, consumer-group member, partition assignment, or host. The inbox
disposition commits with the workflow effect. Concurrent duplicates resolve one
row. Redelivery after commit returns that disposition and acknowledges without
another transition.

A reused `message_id` with different immutable bytes is an integrity conflict,
not a duplicate. Late, conflict, permanent rejection, and success dispositions
are stable.

### Retention and Replay

Inbox and receipt retention must cover broker retention and every authorized
redrive horizon. Cleanup after that horizon weakens durable deduplication and
requires explicit policy. Workflow terminal-state and Agent outcome uniqueness
remain secondary defenses.

Replay is operator-authorized and never automatic. It preserves original
message identity and is safe only through inbox/receipt uniqueness, legal
transition checks, and deterministic side-effect-free execution.

### Retry and Quarantine

Consumer processing uses a small configured number of immediate retries with
bounded backoff. There is no delayed-retry topic and no application retry.
Retry exhaustion publishes a restricted quarantine record and advances the
source offset only after quarantine acknowledgment and durable confirmation.

Malformed input without a trusted `message_id` uses a separate transport
rejection identity:

`(logical_subscription, physical_source, partition, offset)`.

It receives one stable `rejection_id`; quarantine republication preserves that
identity. Transport coordinates never enter the portable envelope.

Quarantine records contain protected original bytes or a reference, safe
classification, source metadata, bounded diagnostics, and safely extractable
IDs. They contain no secrets or unsanitized exceptions. Redrive requires an
authorized audited operator action. No generic dead-letter domain event exists.

## 14. Test Agent Execution

### Capability Contract

Capability: `text.word-count` version `1.0`.

Validated input:

```text
{ "text": <bounded JSON string> }
```

Deterministic semantic output:

```text
{ "text": <the exact input string>, "word_count": <nonnegative integer> }
```

`word_count` is the number of maximal nonempty text segments separated by
Unicode whitespace. The Agent performs no trimming, Unicode normalization, or
text mutation. `completed_at` is terminal-event evidence fixed once for the
accepted outcome; it is not part of the deterministic calculation.

The capability:

- is built into the trusted Agent process;
- uses no model, AI Router, network, filesystem, subprocess, provider, tool, or
  external side effect;
- executes outside a database transaction;
- receives only the technology-neutral execution context;
- uses a bounded execution timeout no greater than the remaining
  `task_result_deadline`;
- uses no capability-operation retry because the calculation has no external
  dependency; and
- supports controlled deterministic failure injection only in isolated tests.

### Admission and Concurrency

The Agent uses one asyncio loop, bounded global concurrency, and at most one
in-flight command per assigned partition. The broker is the durable waiting
area; there is no unbounded in-memory queue. Partition lanes pause/resume for
backpressure and use assignment fencing for offset commits.

An already-expired valid command is validated first, then skips execution and
durably emits a safe non-execution `TaskFailed`. Expiry while waiting for
capacity does the same. Expiry during execution requests cooperative
execution-policy cancellation; `TaskFailed` is created only after safe stop is
confirmed. Lifecycle cancellation from shutdown, restart, or rebalance creates
no business failure before outcome commit and leaves the command unacknowledged
for redelivery.

There is no explicit cancellation command, durable execution lease, public
`RUNNING` state, or claim that computation occurs exactly once.

## 15. Failure-Window Recovery

No correctness rule depends on volatile process memory.

| Failure window | Durable state before failure | Recovery and duplicate behavior | Expected final state / operator action |
| --- | --- | --- | --- |
| API crash before submission commit | No accepted mapping/workflow | Retry same request; composite arbitration runs again | One acceptance or safe rejection |
| API crash after commit before response | Complete accepted workflow at `DISPATCHED` plus outbox | Same-key replay returns stored workflow; no readiness reselection | Existing workflow |
| Concurrent first submission | At most one transaction can own composite key | Losers read winner and compare owner/fingerprint | One canonical workflow |
| Publisher crash before publish | Durable unconfirmed outbox | Claim expires; publisher sends same bytes | One logical command |
| Publisher crash after publish before marking | Outbox outcome unknown; broker may hold record | Republish same ID/bytes; Agent deduplicates | Duplicate delivery, one logical effect |
| Duplicate command delivery | No receipt or one completed receipt | Before commit, recomputation may occur; after commit, stored outcome reused | One accepted Agent outcome/event |
| Agent crash before outcome/receipt commit | No completed receipt | Offset uncommitted; redelivery recomputes | One later accepted outcome |
| Agent crash after transient admission but before execution | No durable claim | Redelivery executes | One later accepted outcome |
| Agent crash after execution before result commit | No durable outcome | Redelivery may recompute deterministic function | One accepted outcome |
| Agent crash after result commit before event publish | Receipt/outcome/event/outbox committed | Agent publisher sends stored event | Same immutable event |
| Agent crash after publish before publication marking | Event outbox unknown; broker may hold event | Republish same ID/bytes | Duplicate event, one transition |
| Duplicate result delivery | Orchestrator inbox may already be complete | Duplicate resolves stored disposition | One terminal transition |
| Orchestrator crash before result commit | No completed inbox/effect | Offset uncommitted; redelivery repeats transaction | One terminal transition |
| Orchestrator crash after result commit before offset commit | Inbox and terminal state committed | Redelivery resolves inbox, then acknowledges | Existing terminal state |
| Agent unavailable or readiness stale | No new workflow for new key | Refresh bounded observation; fail closed | `503`, no accepted records |
| Agent becomes unavailable after acceptance | `DISPATCHED` workflow/outbox exists | Publication/recovery continues until terminal result or deadline | `COMPLETED`/`FAILED`; no reselection |
| Declaration digest mismatch | Candidate ineligible | Invalidate observation; operator fixes deployment/config | No new workflow |
| Invalid/impossible transition | Existing aggregate unchanged | Record safe inbox/rejection disposition; quarantine where required | No state mutation; operator diagnosis if systemic |
| Fingerprint profile unavailable | Existing accepted mapping | Fail closed; never create another workflow | Safe error; restore profile/operator reconcile |
| Authorization or required replay-audit failure | Existing mapping/workflow unchanged | Deny disclosure; no duplicate | Safe response; restore policy/audit |
| Partial graceful shutdown | Only committed state survives | Stop intake/claims, bounded drain, abandon uncommitted work | Restart scans outboxes/inboxes/deadlines |
| Forced restart with deadline elapsed | `DISPATCHED` workflow | Reconciler locks aggregate; deadline or result transaction wins | Deterministic terminal state |

## 16. Audit, Logs, Metrics, and Traces

### Authoritative Evidence

Business audit commits transactionally with:

- first acceptance and complete accepted-request identity;
- selection evidence;
- every workflow-state mutation;
- Agent accepted outcome;
- permanent processing dispositions;
- manual outbox disposition, quarantine redrive, or repair; and
- any future ownership/scope mutation, although none is exposed in this slice.

Required audit failure rolls back the associated business mutation. Ordinary
authorized equivalent replay need not create another business-coupled audit
record unless policy requires access/security audit. Optional telemetry failure
never changes workflow correctness.

Administrative/security audit is separate and durable for privileged
configuration activation, migration, credential lifecycle, redrive, or repair.
Corrections are additive.

### Operational Signals

Structured operational logs use Python logging through the platform logging
boundary. Containers emit JSON-compatible standard output; local interactive
rendering may be human-readable without changing fields, classification, or
redaction.

Logs and traces correlate, when applicable:

- `request_id`, `correlation_id`, and `workflow_id`;
- `task_id` and `task_attempt_id`;
- command/event `message_id` and `causation_id`;
- contract and capability identity;
- safe component/deployment/process identity; and
- safe operation, outcome, retry, and error classification.

W3C trace context is sanitized at API and Event Bus adapters. It is never a
domain identity, authorization input, or correctness dependency. Redelivery and
republication may create new linked spans around the same logical message.

The minimum metric/trace semantics cover:

- accepted workflow, replay, authorized conflict, hidden conflict, and
  owner-intent mismatch counts;
- API/acceptance and terminal latency;
- workflow count/age by bounded state;
- outbox backlog count and oldest age;
- publish attempts, unknown outcomes, and retries;
- inbox/receipt duplicates and conflicts;
- Event Bus delivery, redelivery, lag, quarantine, and acknowledgment;
- Agent admission, capacity, execution duration, outcome, and timeout;
- failed/late/invalid transitions;
- Registry lookup, availability age, mismatch, and no-candidate outcomes;
- transaction retries/exhaustion; and
- liveness, Registry readiness, core/API readiness, deployment availability,
  capability eligibility, and draining.

OpenTelemetry-compatible metrics and traces exist behind no-op-capable ports.
No Collector, exporter, dashboard, alert backend, SaaS, or telemetry Event Bus
is required. Tests inspect the platform-owned signal model directly.

Secrets, raw credentials/tokens, full workflow text, complete payloads,
fingerprint source material, internal scope/owner mappings, SQL/binds, private
routes, and raw health bodies are excluded from logs and traces. High-cardinality
IDs are never ordinary metric labels.

## 17. Minimum Configuration

Environment variables are the authoritative runtime override mechanism. An
explicit ignored local `.env` may supply development convenience values.
Registry/deployment artifacts remain their own trusted authority. This document
does not create another precedence model.

| Item | Class and authority | Scope / startup validation | Reload and failure | Log policy / safe default |
| --- | --- | --- | --- | --- |
| environment | Nonsecret environment variable | Component/environment; must be exactly development for synthetic policy | Restart; fail closed | Bounded value; no production default |
| API listener and host publication assertion | Nonsecret deployment config | Effective route must be host loopback only | Restart; refuse startup | Safe classification only; no wildcard host default |
| local policy enablement | Nonsecret environment config | Platform; explicit opt-in | Restart; refuse if boundary invalid | May log warning; disabled by default |
| semantic operation mapping | Nonsecret application config | API route maps to `workflow.submit` | Restart; fail compatibility validation | Stable operation may log |
| input and response bounds | Nonsecret contract/deployment config | API and Agent; must fit broker limits | Restart; fail startup/schema validation | Bounds may log; payload may not |
| Registry artifact/revision | Deployment declaration from reviewed Git/release artifact | Environment; validate provenance, schema, completeness | Restart only; invalid revision blocks new acceptance | Revision may log |
| Agent declaration/digest | Deployment declaration | Platform and Agent must agree | Restart; mismatch makes Agent ineligible | Digest may log safely |
| readiness route | Nonsecret restricted deployment config | Platform; loopback and environment binding | Restart; missing/invalid means unavailable | Do not log address |
| readiness credential reference | Secret reference in deployment config | Platform and Agent; file exists with protected access | Restart/rotation by bounded procedure; fail closed | Reference classification only |
| readiness credential value | Secret value from protected file mount | Development only; `readiness.query` | Replace/remove at teardown | Never log |
| Orchestrator PostgreSQL endpoint and credential refs | Nonsecret endpoint plus secret references | Orchestrator schema/role/environment | Restart; readiness false | No credential/DSN logging |
| Agent PostgreSQL endpoint and credential refs | Nonsecret endpoint plus separate secret references | Agent schema/role/environment | Restart; Agent unready | No credential/DSN logging |
| migration credential reference | Secret reference owned by migration action | Separate principal, never runtime | Per operation; fail closed | Never log value |
| Event Bus bootstrap/channel mapping | Nonsecret adapter/deployment config | Environment and allowed Kafka subset | Restart; readiness false | Safe logical names only |
| producer/consumer credential references | Separate secret references | Per component/channel/environment ACL | Rotation with bounded overlap | Never log values |
| consumer-group and logical handler identities | Nonsecret adapter config | Stable deployment/subscription mapping | Restart; ambiguous mapping fails | Logical identity may log |
| `task_result_deadline` duration | Nonsecret policy config | Orchestrator/Agent; positive bounded duration | Restart; invalid fails startup | Duration may log |
| execution/admission/shutdown bounds | Nonsecret Agent policy | Positive and mutually consistent | Restart; Agent unready if invalid | Bounded values may log |
| immediate retry/backoff/quarantine policy | Nonsecret adapter config | Component/channel; bounded, no delayed retry | Restart; invalid fails readiness | Safe classifications may log |
| outbox claim/retry bounds | Nonsecret persistence/publisher config | Per component; claim expiry exceeds bounded operation assumptions | Restart; invalid fails readiness | Counts/durations may log |
| readiness TTL/timeout | Nonsecret availability policy | Short, positive, timeout below request budget | Restart; invalid blocks acceptance | Duration/class may log |
| retention categories | Nonsecret data/transport policy | Requests, workflows, history, inboxes, outboxes, outcomes, broker, quarantine | Restart/admin action; invalid fails safe | Durations may log |
| logging/trace/metric mode | Nonsecret observability config | Component; allowlisted renderer/export mode | Restart; exporter failure nonblocking | Safe mode may log |
| process/instance identity | Runtime-derived identity | Created per process; not authority | Recreated on restart | Logs/traces only |

Exact numeric limits, pinned component releases, physical topic names, and
retention durations are bounded implementation/deployment choices listed in
Section 23. They do not change the architecture above.

## 18. Minimum Local Deployment Shape

The supported isolated local topology is:

| Component | Responsibility and persistence | Network/credential boundary | Startup, health, shutdown, recovery |
| --- | --- | --- | --- |
| Platform process | API, Orchestrator, Registry, workflow/outbox/inbox, deadline reconciler | API effectively host-loopback; Orchestrator DB role; command producer/outcome consumer credentials; readiness credential | Starts after PostgreSQL/Event Bus; liveness independent; core readiness excludes Agent availability; drains API intake/consumer/publisher and recovers durable state |
| Test Agent process | readiness endpoint, command consumer, deterministic capability, receipt/outcome/event outbox | Readiness on application loopback; Agent DB role; command consumer/outcome producer credentials | Starts independently; readiness requires durable handling; drains admission and recovers receipt/outbox |
| PostgreSQL | Authoritative Orchestrator and Agent state in owned schemas | Private local deployment network; separate roles and secret mounts; host publication only when test tooling requires loopback | Health includes connection/schema checks; graceful stop after applications; durable volume supports restart tests |
| Redpanda | Kafka-protocol transport for two logical channels and quarantine resources | Private local deployment network; component ACLs/credentials; no public/LAN exposure | Durability-preserving configuration for recovery tests; health before clients; retained records/offsets recover after restart |

To satisfy the accepted one-way readiness boundary without adding mutual
authentication, the platform and Agent processes share one trusted local
loopback namespace for development readiness. That may be the isolated
developer host namespace or an isolated application container namespace. This
plan does not select the process supervisor or a complete container topology.
The processes remain distinct modules, persistence identities, and Event Bus
principals, with independent liveness, readiness, graceful shutdown, and
credentials. A later topology that places readiness on a non-loopback network
requires the stronger component authentication required by ADR-0010.

No untrusted container joins the deployment network. Only the Workflow API is
published to the host, and only on `127.0.0.1` or `::1`. PostgreSQL and
Redpanda are not publicly exposed. Test-only host loopback publication is
permitted when an isolated test requires direct adapter access.

This topology is a development proof, not production high availability. A
production topology requires mutually authenticated component identities and a
later deployment decision.

## 19. Testable Acceptance Criteria

All tests are local when every dependency is created and owned by the test run.
No shared service, external identity provider, or AI provider is required.
Unit/component tests may use controlled ports; PostgreSQL, Redpanda, network,
process, ACL, and crash guarantees require isolated real-service tests.

### Test Categories

- **Contract:** canonical JSON Schema, OpenAPI, AsyncAPI, examples, exact
  versions, UUIDv7, timestamps, Problem Details, producer/consumer parity.
- **Persistence and transaction:** composite uniqueness, atomic integrity
  units, history/snapshot parity, coupled audit, unknown commit recovery.
- **Idempotency:** historical fingerprints, equivalent/conflicting replay,
  lost response, two scopes, credential rotation.
- **Ownership/disclosure:** actor/owner/scope separation, unauthorized replay,
  owner mismatch, safe not-found.
- **Concurrency:** concurrent first acceptance, duplicate Agent computation,
  result/deadline race, competing publishers and consumers.
- **Event Bus delivery:** keyed ordering, manual acknowledgment, at-least-once
  redelivery, broker restart, producer uncertainty, bounded retry/quarantine.
- **Inbox/outbox:** claim fencing, unknown publication, duplicate and changed
  payload identities, retention/replay boundaries.
- **State machine:** every legal edge, illegal/late/conflicting events,
  terminal immutability, history revisions.
- **Agent selection/readiness:** revision/digest, bounded verification, TTL,
  stale/unknown/draining, exactly-one policy, no readiness on replay/query.
- **Security boundary:** loopback effective exposure, separate credentials and
  grants, ACLs, secret/redaction, synthetic shared identity limitation.
- **Recovery/crash window:** every row in Section 15 with deterministic fault
  injection and process/container restart.
- **Audit/observability:** coupled audit rollback, signal correlation, bounded
  labels, trace links, telemetry failure isolation.
- **Startup/shutdown:** independent startup, recovery workers, drain, forced
  termination, no volatile correctness.

### Critical Executable Scenarios

| Guarantee | Setup and action/fault | Expected public result | Expected durable/message/audit evidence | Prohibited outcome |
| --- | --- | --- | --- | --- |
| One workflow per complete key | Submit same request concurrently in one trusted key | One `202`, remaining authorized responses resolve same workflow | One mapping/workflow/task/attempt; three initial transitions; one command outbox; one acceptance audit | Two workflows or commands |
| Same ID in two scopes | Controlled security adapter resolves two scopes; submit same `request_id` | Two independent `202` responses with different workflows | Two composite keys and integrity units | Cross-scope lookup/disclosure or global uniqueness failure |
| Owner isolation in shared scope | Owner A accepts; owner B reuses key with same fingerprint | Safe `404` for B | Original mapping unchanged; policy-required safe mismatch audit | A's identifiers returned or B workflow created |
| Equivalent replay | Accept then repeat same key/fingerprint/owner while Agent unavailable | `200` with same identifiers/current state | No new domain records or message; optional replay telemetry only | Readiness check or duplicate workflow |
| Fingerprint conflict | Reuse occupied key with changed text as authorized actor | Safe `409` | Mapping unchanged; authorized conflict evidence | New workflow or existing protected data in error |
| Lost response | Crash API after submission commit | Retry returns `200` existing workflow | Original integrity unit only | Reselection or new identifiers |
| Publish-before-mark crash | Kill publisher after broker acceptance | Workflow remains queryable; eventually terminal | Unknown outbox then republication with same bytes/ID; Agent receipt one outcome | New message ID or duplicate logical result |
| Duplicate command | Deliver identical command concurrently/repeatedly | No direct API change; eventual one outcome | One completed receipt/outcome/event identity; recomputation allowed only before commit | Two accepted outcomes/events |
| Duplicate result | Redeliver identical terminal event | One terminal API state | One Orchestrator inbox disposition and terminal transition | Duplicate history or state reopening |
| Stale/mismatched Agent | Return stale observation or wrong declaration digest for a new key | `503 AGENT_TEMPORARILY_UNAVAILABLE` | No accepted mapping/workflow/outbox; safe readiness evidence | `PENDING` workflow or dispatch |
| Deadline race | Hold event and deadline transactions concurrently | Exactly one terminal state | Serialized aggregate, one terminal history entry; loser recorded late | Nondeterministic overwrite |
| No volatile correctness | Kill each process at every Section 15 boundary and restart | Existing accepted requests remain replayable/queryable | Recovery from database, broker, inbox/outbox/receipt only | Manual memory reconstruction or duplicate canonical state |
| Security exposure | Attempt host wildcard, LAN/proxy, untrusted-container network, or shared-host mode | Startup/readiness refusal | Safe configuration/security evidence; no secret output | Synthetic policy serving the route |
| Audit failure | Fail required acceptance or transition audit write | Safe failure/no disclosed mutation | Transaction rollback | Business mutation without required audit |
| Telemetry failure | Disable metric/trace/log exporter during valid work | Workflow completes normally | Durable business/audit evidence remains authoritative; drop/failure signal where possible | Workflow failure caused solely by optional telemetry |

The invalid `Correlation-Id` contract test remains blocked by Section 24.

## 20. Implementation Phases

The existing eight-phase sequence is preserved.

### Phase 1: Tooling and Canonical Contracts

Create the ADR-0003 root tooling metadata and canonical JSON Schema,
OpenAPI, AsyncAPI, examples, configuration, and declaration contracts.
Implement no domain behavior before the Section 24 correlation conflict is
resolved for the API contract.

### Phase 2: Workflow Domain and Persistence Ports

Define the five-state aggregate, composite accepted-request arbitration,
actor/owner/scope evidence, task/attempt, transition history, audit, inbox,
outbox, Agent receipt/outcome, and capability-oriented persistence ports.

### Phase 3: Orchestrator and Capability Registry

Implement configuration-backed Registry loading, bounded readiness, immutable
selection intent, submission transaction orchestration, terminal processing,
deadline reconciliation, and recovery through ports.

### Phase 4: Test Agent

Implement the built-in word-count capability, bounded lifecycle, validation,
completed-receipt deduplication, outcome transaction, Agent event outbox, and
development readiness boundary.

### Phase 5: Workflow API

Implement submit/read/health operations, trusted synthetic context, composite
replay/disclosure behavior, stable Problem Details, effective-exposure
validation, and correlation behavior after the blocker is resolved.

### Phase 6: Concrete Adapters and Local Deployment

Implement Psycopg 3 persistence adapters, the `confluent-kafka` adapter for the
allowed Kafka subset, Redpanda/PostgreSQL local resources, isolated credentials
and ACLs, Docker artifacts, publishers, consumers, health, and shutdown.

### Phase 7: Integration, Recovery, Security, and End-to-End Tests

Implement the Section 19 suites against isolated real PostgreSQL and Redpanda,
including crash windows, rebalance, unknown publication, concurrency, network
exposure, grants, and the complete public success/failure paths.

### Phase 8: Verified Operational Documentation

Document only demonstrated setup, health, query, recovery, troubleshooting,
shutdown, cleanup, contract generation, security limitations, and validation
commands. Do not claim production readiness.

## 21. Explicit Deferrals

| Deferred capability | Why deferral does not invalidate this slice |
| --- | --- |
| Production OAuth/OIDC or enterprise identity | Synthetic identity is explicitly confined to one isolated developer boundary; production identity is not claimed |
| Production mutual Agent authentication and PKI | Co-located loopback readiness accepts a documented residual risk and cannot be externally exposed |
| Secret-management platform | Protected file injection and separate development credentials prove secret boundaries without selecting a provider |
| Multiple Agent implementations/deployments | Exactly-one candidate proves declaration, compatibility, readiness, and durable selection without inventing scheduling |
| Dynamic registration, heartbeat, or service discovery | Trusted configuration plus bounded readiness realizes the Accepted first-slice Registry model |
| Horizontal application scaling | Database constraints and consumer-group semantics are tested with controlled concurrent instances; supported deployment remains single local application boundary |
| Multi-node PostgreSQL/Redpanda and disaster recovery | Restart durability proves local recovery, not machine-loss or HA guarantees |
| Multi-region or production orchestration | Logical contracts remain portable; topology needs later failure-domain decisions |
| Production rate limiting and dynamic policy administration | Bounded local input/concurrency and fixed versioned policy suffice for the isolated proof |
| Real AI/model execution and AI Router | Deterministic work proves orchestration without provider nondeterminism or credentials |
| Irreversible external side effects | Their idempotency, fencing, approval, and reconciliation require a future ADR |
| Skills and dynamic plugins | Built-in capability is enough to exercise the Agent boundary |
| Application retry/additional attempts | One attempt proves transport retry and idempotency without defining retry policy |
| Explicit cancellation, progress, `RUNNING`, leases | Short deterministic work uses accepted deadline/lifecycle behavior |
| Ownership transfer and scope split/merge APIs | Data is modeled correctly; administration and migration are unnecessary for the first execution path |
| Advanced scheduling, load selection, autoscaling | Exactly-one candidate makes selection deterministic |
| Full operator UI, dashboards, alert backend | Durable evidence and backend-neutral signals are testable without a product |
| Production backup/PITR, retention values, performance optimization | They require measured deployment objectives; first-slice integrity and cleanup boundaries remain explicit |

## 22. Accepted-ADR Alignment Matrix

| ADR | First-slice realization | Deferred/non-applicable parts | Acceptance evidence |
| --- | --- | --- | --- |
| ADR-0001 Core Design Principles | Modular ports, explicit contracts, Git-owned schemas/config, Docker artifacts, vendor boundaries | Production Unraid topology and IaC details | Boundary tests, package/import tests, local deployment validation |
| ADR-0002 Communication and State | Event Bus for commands/events, Orchestrator-owned durable state, at-least-once, keyed ordering, bounded retry, Registry | AI Router and dynamic discovery | Workflow, duplicate, ordering, replay, deadline tests |
| ADR-0003 Runtime and Tooling | CPython 3.14, uv, Hatchling, `pyproject.toml`, `uv.lock`, Ruff, BasedPyright strict, pytest, `src/ai_platform/` | Additional languages/distributions | Locked install/build/format/lint/type/test validation |
| ADR-0004 API and Contracts | HTTP/JSON, JSON Schema Draft 2020-12, OpenAPI 3.1.1, AsyncAPI 3.0.0, UUIDv7, envelope, Problem Details | New contract categories/versions | Canonical schema and artifact parity tests; correlation conflict noted in Section 24 |
| ADR-0005 Event Bus | Allowed Kafka subset, Redpanda, `confluent-kafka`, two channels, workflow key, manual commits, immediate retry, quarantine | Delayed retry, extra channels, managed brokers | Real-broker acknowledgment, redelivery, order, quarantine, restart tests |
| ADR-0006 Persistence | PostgreSQL, owned schemas, composite integrity unit as amended, current state plus history, inbox/outbox, claims, recovery | HA, DR, alternative database, long-term values | Atomicity, uniqueness, crash, isolation, history/snapshot tests |
| ADR-0007 Agent Execution | Plain Python/asyncio, bounded lanes, deterministic built-in capability, no lease, truthful outcome, lifecycle cancellation | Side effects, long-running/interactive work, frameworks | Capability, concurrency, cancellation, duplicate, recovery tests |
| ADR-0008 Registry | Trusted static revision, deployment digest, bounded readiness route/TTL, exactly-one selection, atomic evidence | Dynamic registration, load policy, database Registry | Revision/digest/readiness/selection transaction tests |
| ADR-0009 Observability | Structured logs, durable audit, W3C trace context, OTel-compatible metrics/traces, redaction | Backend, Collector, dashboards, alerts/SLO targets | Coupled-audit, correlation, signal, cardinality, failure-isolation tests |
| ADR-0010 Security | Synthetic loopback-only policy, separate credentials/roles/ACLs, one-way readiness credential, bounded endpoint verification | Production identity, mutual auth, break-glass, delegation | Exposure, authentication boundary, grants/ACL, disclosure, secret tests |
| ADR-0011 Scoped Idempotency and Ownership | Composite key, five distinct identities, historical fingerprint, owner equivalence, current disclosure, no global lookup | Transfer and scope-migration APIs | Two-scope, shared-scope owner, rotation, concurrency, lost-response tests |

## 23. Unresolved Implementation Choices

These choices are bounded by Accepted ADRs and do not require new architecture:

- exact supported patch releases and locked dependency versions;
- canonical schema file organization and generation tooling;
- exact safe `TaskFailed` code vocabulary within the accepted failure classes;
- numeric request/payload limits;
- `task_result_deadline`, execution reserve, readiness timeout/TTL, shutdown
  grace, transaction retry, immediate transport retry, claim expiry, and
  publication retry values;
- physical topic prefix, small partition count, replication and retention
  values for the isolated local broker;
- PostgreSQL major/patch version, migration tool, pool sizes, schema/table/index
  names, and retention durations;
- concrete local process supervision inside the isolated application network
  namespace;
- structured JSON encoder and optional local human renderer;
- optional local metric/trace exporter choice, if any; and
- exact test failure-injection hooks and deterministic clock/ID fixtures.

Each choice must be documented with a safe default, validated at startup where
applicable, pinned or versioned where applicable, and tested against the
guarantees in this plan.

## 24. Unresolved Architectural Blocker

Two Accepted ADRs conflict on invalid client correlation context:

- ADR-0004 Section 8 states that an invalid supplied `Correlation-Id` is
  rejected.
- ADR-0009 Sections 4, 6, 8, and 35 state that malformed or disallowed client
  correlation context is discarded or replaced and never makes an otherwise
  valid business request fail.

Neither ADR declares that it supersedes the other on this behavior. This
document therefore does not choose a response. The invalid-header branch of
the Workflow API contract, its OpenAPI examples, and its acceptance test remain
blocked until an Accepted ADR explicitly resolves the conflict. Valid and
absent `Correlation-Id` behavior remains unambiguous: a valid UUIDv7 may
initialize correlation; when absent, the Orchestrator creates a UUIDv7 and the
API returns it.

No other conflict among ADR-0001 through ADR-0011 was found. ADR-0011's explicit
amendments resolve the earlier global `request_id` clauses.

## 25. Alignment Change Summary

This review:

- expanded authority from ADR-0001/ADR-0002 to every Accepted ADR;
- replaced global `request_id` uniqueness and lookup with the ADR-0011
  composite key;
- separated current/acceptance actors, accepted/current owners, scope, policy,
  operation, and fingerprint profile;
- removed public task and attempt identifiers from API responses;
- added authorization-safe replay, conflict, owner mismatch, and disclosure
  behavior;
- replaced unresolved technology language with Accepted CPython, tooling,
  PostgreSQL, Redpanda/Kafka-subset, and client decisions;
- made all three initial workflow transitions and the command outbox one
  atomic submission transaction;
- added mandatory selection and business-audit evidence to that transaction;
- replaced the informal Agent receipt model with ADR-0006/ADR-0007 completed
  receipt, outcome, event, and outbox semantics;
- documented outbox claim fencing, publication uncertainty, ordering barriers,
  quarantine, and recovery;
- separated logical inbox identities from consumer groups and process
  instances;
- aligned Registry identity, declaration digest, revision, bounded readiness,
  and atomic selection evidence with ADR-0008;
- replaced generic local authorization with ADR-0010's exact effective
  exposure, synthetic identity, credential, and one-way readiness boundaries;
- distinguished authoritative audit from lossy logs, metrics, and traces;
- added exact transaction, state, failure-window, configuration, topology, and
  executable acceptance-test descriptions;
- retained the deterministic word-count path and the original eight
  implementation phases; and
- identified the unresolved ADR-0004/ADR-0009 correlation-header conflict
  without inventing a resolution.

## 26. Implementation-Readiness Checklist

- [x] The bounded end-to-end behavior is defined.
- [x] No global `request_id` uniqueness or lookup remains.
- [x] Actor, owner, scope, request, operation, and replay concepts are distinct.
- [x] Submission, outcome, result-consumption, publication, and rejection
      transaction boundaries are explicit.
- [x] Message, business-attempt, logical-consumer, receipt, and transport
      rejection identities are explicit.
- [x] Workflow states, transitions, duplicate behavior, and deadline races are
      explicit.
- [x] Every required crash/recovery window has a durable recovery path.
- [x] Registry revision, declaration digest, readiness, eligibility, routing,
      and selection evidence are explicit.
- [x] Minimum configuration and secret boundaries are known.
- [x] Public API and asynchronous contracts are known except for the one
      blocked invalid-correlation branch.
- [x] Executable acceptance-test categories and critical scenarios are
      specified.
- [x] Remaining nonblocked choices are implementation details.
- [ ] No unresolved Accepted-ADR conflict remains.

Vertical Slice 01 is internally coherent for every unblocked behavior and is
aligned with every unambiguous Accepted-ADR requirement. It is **not yet ready
for implementation** because the invalid `Correlation-Id` API behavior has two
conflicting Accepted definitions. Once that conflict is resolved by an
Accepted ADR and this document is updated accordingly, no other architectural
blocker remains.
