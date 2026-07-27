# ADR-0006: Persistence, State, and Recovery

- **Status:** Accepted
- **Date:** 2026-07-27
- **Supersedes:** None
- **Superseded by:** None

## Context

ADR-0002 makes the Orchestrator the owner of durable workflow execution state.
ADR-0004 defines stable identifiers, API request idempotency, and immutable
message identity. ADR-0005 selects at-least-once messaging and requires
transactional outboxes, consumer deduplication, durable Agent outcomes, and
manual acknowledgment after durable processing.

Those decisions deliberately do not select a persistence technology or define
the transactions that make their guarantees true. Vertical Slice 01 now needs
one persistence model that can survive process, container, database-client, and
broker failures without claiming end-to-end exactly-once behavior.

Correctness is more important than theoretical throughput. The first deployment
is a local Docker environment and then Unraid, normally on one physical machine
and potentially two. The architecture must nevertheless permit multiple
Orchestrator and Test Agent instances and must not encode database products in
domain contracts.

### Existing Documentation Alignments and Ambiguities

The accepted ADRs do not conflict on persistence ownership or messaging
semantics. The following nonbinding Vertical Slice 01 text requires explicit
interpretation:

- its Agent transaction requires a completed command receipt, outcome, terminal
  event, and event outbox to commit atomically, while its recovery text also
  describes a crash after a receipt is stored but before an outcome is stored.
  Both cannot be durable failure windows in the first-slice transaction. This
  ADR chooses the atomic transaction: before that commit, deterministic work
  may be repeated; after it, the completed receipt, outcome, event, and event
  outbox all exist;
- its logical-record list includes a configured manifest even though the
  Capability Registry is configuration-backed. This ADR treats the manifest as
  configuration authority and any database copy as rebuildable diagnostic
  metadata, not authoritative workflow state;
- its technology table still calls Python and the Event Bus planned candidates,
  although ADR-0003 and ADR-0005 have since accepted those decisions; and
- its Required ADRs section uses earlier filenames for ADR-0005 and ADR-0006.
  The intended subjects are clear, but those references should be aligned in a
  later documentation-only change.

This ADR does not modify the Vertical Slice document or accepted ADRs.

## Decision Drivers

The decision is evaluated against:

- atomic state transitions and prevention of lost outgoing messages;
- deterministic crash recovery and auditability;
- API, message, and Agent execution idempotency;
- duplicate and concurrent delivery to multiple component instances;
- enforceable uniqueness, isolation, and concurrency control;
- operational simplicity for Docker, Unraid, and one or two machines;
- Python 3.14 client and migration support;
- local, integration, resilience, backup, and restore testing;
- observability, least privilege, privacy, and data minimization;
- future database replacement without database-specific domain contracts; and
- explicit limits on every exactly-once, atomicity, and recovery claim.

## Decision

### 1. Persistence Responsibilities

Persistence is divided by meaning rather than collapsed into a generic event
table.

| Durable responsibility | Owner | Classification | Purpose |
| --- | --- | --- | --- |
| Workflow current state | Orchestrator | Authoritative business state | One current state selected from the five accepted workflow states, result or safe failure, revision, and recovery timestamps |
| Workflow transition history | Orchestrator | Append-only audit history | Every accepted logical state transition and its cause |
| Accepted API request | Orchestrator | Authoritative idempotency state | `request_id`, canonical fingerprint, fingerprint-policy version, workflow identity, and initial acceptance result |
| Task and task attempt | Orchestrator | Authoritative business state | Selected Agent, attempt identity, command identity, deadline, and terminal outcome relationship |
| Orchestrator outbox | Orchestrator | Transport recovery state | One immutable `ExecuteTask` publication and recoverable publication disposition |
| Orchestrator domain inbox | Orchestrator | Transport recovery and deduplication state | Durable processing disposition after a validated event `message_id` is established |
| Transport rejection or quarantine recovery | Consuming component | Pre-domain transport recovery state | Stable disposition and quarantine progress for a broker delivery that lacks trusted domain identity |
| Agent completed command receipt | Agent deployment | Business-idempotency and transport-recovery state | Proof that a validated command identity is durably associated with its accepted outcome and terminal event |
| Agent outcome | Agent deployment | Authoritative Agent business state | The one accepted result for a `task_attempt_id` |
| Agent event outbox | Agent deployment | Transport recovery state | One immutable terminal event and recoverable publication disposition |
| Claim or lease metadata | Record owner | Disposable operational metadata | Short ownership of outbox publication work; not workflow or Agent execution state |
| Attempt counters and publication diagnostics | Record owner | Disposable operational metadata | Bounded retry, failure, and operational evidence |

The current workflow snapshot is authoritative for queries. Transition history
is a mandatory audit companion, not a projection built from the Event Bus.
Outbox, domain inbox, transport rejection, completed receipt, claim, and
publication records are not workflow state.
Derived state is limited to rebuildable query projections, aggregate
operational counters, and an optional diagnostic copy of the
configuration-backed capability manifest. Losing derived state must not change
workflow, idempotency, outcome, or recovery behavior.
Operational metadata may be compacted only after its recovery, replay,
retention, and audit obligations have ended.

### 2. Persistence Technology Evaluation

The following comparison groups the required evaluation dimensions. A product
is not considered suitable merely because it can store JSON.

| Option | Transactions, isolation, constraints, and outbox/inbox | Clients, migrations, portability, and operations | Scaling and fit for one or two machines | Decision |
| --- | --- | --- | --- | --- |
| PostgreSQL | Full ACID transactions, mature isolation, unique and foreign-key constraints, conditional updates, row locks, `SKIP LOCKED`, and relational plus JSON storage fit all required atomic units | Mature Python sync and async clients, broad migration tooling, official Windows and Linux support, small Docker deployments, established backup/PITR, strong observability, permissive license, and broad managed-service availability | One primary is operationally simple; replicas and larger topologies exist, although write scaling and HA still require deliberate design | Selected initial technology |
| Oracle Database | Full ACID transactions, mature isolation, constraints, conditional updates, row locking, skip-locked claiming, and strong relational/JSON capabilities also satisfy correctness | Excellent tooling and `python-oracledb`; Windows, Linux, containers, backups, and Autonomous Database are supported, but edition entitlements, licensing, patching, and local images require more governance | Highly capable at scale, but the supported production footprint is heavier than needed for the first self-hosted slice | Capable but not selected |
| SQLite | ACID for one file and useful constraints, JSON functions, and migrations; it lacks the selected server concurrency, independent runtime identities, and portable row-claim semantics | Excellent embedded Python and Windows/Linux portability with minimal operations and simple backups | Excellent for a single local process, but it cannot prove multi-instance locking, pool, failover, or skip-locked behavior | Rejected as the platform store |
| Document database class | Some products offer multi-document transactions, unique indexes, conditional writes, JSON-native data, and async drivers | Guarantees, query models, migration practices, backup, observability, and managed portability differ materially by product | Horizontal scaling may be strong, but it adds product-specific consistency choices without helping the relational invariants | Rejected as an unbounded class |
| Embedded key-value store class | Atomic batches and compare-and-swap may be available, but relational uniqueness, history relationships, indexed recovery queries, and multi-process isolation vary | Lightweight local operation, but migration, inspection, backup, async, and cross-platform behavior are product-specific | Good for embedded state or caches; poor fit for the complete first-slice source of truth | Rejected |
| Event Sourcing as primary persistence | Can make aggregate writes append-only, but requires expected-version appends, projections, event evolution, and separate outbox coordination | Adds projection migration, replay governance, debugging, and operating concepts before the slice benefits from them | Can scale by aggregate, but complexity is disproportionate to the five-state workflow | Rejected as primary model |
| Separate database per component | Preserves component ownership and failure isolation; each component can retain its own local atomic units | More credentials, migrations, backups, containers, health checks, and restore coordination | Useful at larger scale, but unnecessary for the first two components on one machine | Deferred topology |
| One shared database with owned schemas | Preserves each required component-local transaction while using one server, backup system, and local container | Separate roles and migrations retain ownership; future separation requires adapter and data migration rather than domain-contract changes | Simplest correct first-slice topology, with an acknowledged shared failure domain | Selected initial topology |

PostgreSQL is selected as the initial relational persistence technology. The
selected major and patch release must be supported and pinned when
implementation begins; this ADR does not freeze a database release before
deployment validation.

PostgreSQL-specific behavior remains inside persistence and migration adapters.
The platform does not choose a managed database service as a dependency.

### 3. Oracle Versus PostgreSQL

Oracle expertise materially reduces one owner's operational learning curve, so
Oracle is evaluated as a serious alternative.

| Concern | PostgreSQL | Oracle Database | Effect on decision |
| --- | --- | --- | --- |
| Transactional correctness | ACID transactions and explicit isolation meet every first-slice boundary | ACID transactions and mature recovery also meet every boundary | Equivalent for required correctness |
| Isolation semantics | Read Committed is statement-snapshot based; Repeatable Read uses snapshot isolation; Serializable detects serialization anomalies | Read Committed and Serializable use Oracle's multiversion consistency semantics | Both require anomaly-aware application design and retries |
| `SELECT FOR UPDATE` | Row locking with `NOWAIT` and `SKIP LOCKED` | Mature row locking and skip-locked work selection | Both support short work claiming |
| Unique constraints and conditional updates | Native constraints, conflict handling, and version predicates | Native constraints, merge/update predicates, and mature locking | Both satisfy identity enforcement |
| Generated identifiers | Identity/sequences exist, but platform UUIDv7 values are generated by domain owners | Identity/sequences exist, but platform UUIDv7 values are generated by domain owners | Database-generated public IDs are unnecessary |
| JSON | `json`/`jsonb` complement relational columns | Native JSON and SQL/JSON are comprehensive | Both exceed first-slice needs |
| Migration and schema tooling | Broad open-source ecosystem and plain SQL support | Mature commercial and open tooling plus plain SQL support | Both viable; exact tool remains bounded |
| Python drivers | Psycopg 3 and asyncpg are mature; SQLAlchemy supports PostgreSQL | `python-oracledb` supports thin, thick, sync, and async modes; SQLAlchemy supports Oracle | Both support Python 3.14 |
| Local container footprint | Straightforward small Linux container and test-owned instances | Free container images exist, but supported production editions and Autonomous images have different limits and terms; resource use and startup are generally higher | PostgreSQL better fits frequent local tests and Unraid |
| Windows and Linux | Native packages and containers are widely used | Native packages and Linux container options exist | Both viable |
| Licensing | Permissive PostgreSQL License without edition feature entitlements | Free images have limits/support qualifications; Standard Edition 2 and Enterprise features require entitlement review | PostgreSQL reduces ongoing governance |
| Autonomous Database compatibility | Not applicable; many managed PostgreSQL services exist | The logical model is compatible with Autonomous Database, but adopting it would add a cloud service decision | Neither managed service is required |
| Oracle Standard Edition constraints | Not applicable | The design would have to remain within licensed SE2 features and topology limits; optional Enterprise features cannot be assumed | Extra validation without a first-slice benefit |
| Backup, recovery, and observability | Mature physical/logical backup, WAL/PITR, catalog, and metrics ecosystem | Mature RMAN, recovery, diagnostics, and enterprise tooling | Both capable |
| Horizontal scaling | Read replicas are common; multi-writer or sharding requires more architecture | Rich scale and HA options, often edition or service dependent | Neither is needed for the first slice |
| Managed-service portability | Available from many providers with product differences to validate | On-premises and Oracle cloud options are strong but narrower as a managed product | PostgreSQL offers more hosting choices |
| Operational burden | Small self-hosted baseline; HA is still nontrivial | Owner expertise helps, but edition, image, patch, memory, and licensing operations remain heavier | PostgreSQL has the lower platform-wide burden |

Oracle is not rejected for technical weakness, and PostgreSQL is not selected
for popularity alone. PostgreSQL provides the required semantics with less
local resource use, licensing review, and production-edition divergence.
Choosing Oracle later remains possible behind the persistence ports, but it
would require a new ADR and database-semantic conformance tests.

### 4. Persistence Port Boundaries

Domain and application modules depend on capability-oriented ports equivalent
to:

- a workflow repository for current snapshots and conditional transitions;
- a workflow-transition repository for append-only history;
- an accepted-request repository for atomic request arbitration;
- task and task-attempt repositories;
- an Orchestrator outbox repository;
- an Orchestrator domain-inbox or consumer-deduplication repository;
- a transport rejection or quarantine-recovery repository owned by each
  consuming component;
- an Agent completed-receipt and outcome repository;
- an Agent event-outbox repository; and
- an outbox claim repository capability.

These are architectural responsibilities, not prescribed Python interfaces.
One application transaction may compose several repositories through an
adapter-owned unit-of-work boundary.

Domain modules must not receive SQL, connections, cursors, transaction objects,
ORM sessions, table or schema names, sequences, row-lock modes, or
database-specific exceptions and types. Persistence adapters translate
database failures into stable application classifications such as conflict,
retryable transaction failure, unavailable dependency, or permanent
persistence failure.

The following capabilities cannot be abstracted into generic create/read/update
methods without losing correctness:

- atomic commit of explicitly named record groups;
- database-enforced uniqueness and conflict classification;
- compare-and-set by aggregate revision;
- serialized access to a workflow transition where required;
- crash-safe, exclusive, expiring outbox claims;
- append-only transition recording in the same transaction as current state;
- isolation and durability adequate for each transaction; and
- deterministic recovery queries for not-attempted, unconfirmed,
  unknown-outcome, claimed, expired, and nonterminal work.

An alternative adapter must prove these capabilities even if it implements
them differently.

### 5. Transaction Boundaries

#### Workflow Submission Transaction

Request validation and canonicalization precede acceptance. The Orchestrator
first resolves any existing accepted mapping; an equivalent replay returns it
without evaluating current Agent readiness, as required by ADR-0004. Only a
request that is still new checks Agent readiness and constructs its stable
identifiers, transition timestamps, fingerprint intent, and immutable command
before the retryable database transaction. If readiness fails, the Orchestrator
may recheck for a concurrently accepted mapping before returning
`AGENT_TEMPORARILY_UNAVAILABLE`. No unavailable rejection creates a workflow.

One transaction then:

1. creates or resolves the unique accepted `request_id` and its fingerprint
   policy;
2. creates the workflow, task, and first task attempt;
3. appends the logical `none -> RECEIVED`, `RECEIVED -> PENDING`, and
   `PENDING -> DISPATCHED` transition records;
4. stores the workflow snapshot with current state `DISPATCHED`; and
5. stores the immutable `ExecuteTask` outbox message.

The three transitions remain logically visible even though they commit
together. `DISPATCHED` means the command is durably recorded, not published.

- On a first submission, all records commit or none do.
- An equivalent duplicate resolves to the accepted workflow and its current
  state without creating records.
- A conflicting duplicate returns `REQUEST_ID_CONFLICT`.
- Concurrent submissions arbitrate through the unique `request_id`; the loser
  reads the committed mapping and applies the same equivalence check.
- Failure before commit leaves no accepted mapping, workflow, or outbox.
- Failure after commit but before the API response is recovered by retrying
  with the same `request_id`, which returns the existing workflow.

#### Workflow Outcome-Processing Transaction

This transaction begins only after the consumer has validated the immutable
message identity required by ADR-0004.

One transaction:

1. locks or conditionally selects the current workflow aggregate;
2. inserts or resolves the domain-inbox key
   `(logical_consumer_id, validated_message_id)`;
3. validates the immutable message identity, expected `task_attempt_id`,
   current revision, and legal `DISPATCHED` terminal transition;
4. applies `COMPLETED` or `FAILED` to the workflow, task, and attempt;
5. appends transition history; and
6. creates any later required outbox message.

Vertical Slice 01 creates no follow-on domain message. The inbox completion
record and required domain effects commit together. A duplicate returns the
stored processing disposition. Late or conflicting outcomes cannot change a
terminal workflow and receive a stable recorded disposition.

#### Pre-Identity Transport-Rejection Transactions

A broker record that cannot establish a trusted ADR-0004 `message_id` never
enters the domain inbox. The consuming component instead identifies the
delivery by stable transport metadata: logical subscription, physical topic or
equivalent source, partition, and offset. A SHA-256 digest of the original
received bytes may supplement that identity for integrity and diagnosis.
Topic, partition, offset, and the digest are transport metadata and never
become fields in the portable domain-message envelope.

The quarantine failure window is:

1. receive the invalid broker record;
2. in a short transaction, create or resolve the unique transport-delivery
   locator and its stable opaque `rejection_id`, safe failure classification,
   and original-bytes digest when retained;
3. publish the quarantine record outside the database transaction using the
   stable `rejection_id`;
4. after broker acknowledgment, durably record quarantine confirmation in a
   short transaction; and
5. commit the source offset only after that durable confirmation.

Malformed JSON, a missing or invalid `message_id`, an unparseable envelope,
conflicting duplicate properties, and equivalent pre-identity damage follow
this path. A crash before Step 2 leaves no rejection record and redelivery
retries classification. A crash after Step 2 resumes the same rejection. A
crash or lost acknowledgment after Step 3 may cause duplicate quarantine
publication, but every copy preserves the same `rejection_id`. A crash after
Step 4 but before Step 5 resolves the confirmed rejection on redelivery and
commits the source offset without another required quarantine publication.

A permanently rejected message with an already validated `message_id` may use
the domain inbox for its stable processing disposition. Its quarantine
publication status remains transport recovery state and must still satisfy the
same acknowledge-before-source-offset rule.

#### Agent Outcome Transaction

Actual task execution occurs outside a database transaction. After deterministic
work completes, one transaction:

1. creates or resolves the completed command receipt;
2. enforces one outcome per `task_attempt_id`;
3. stores the outcome and first terminal timestamp;
4. stores the immutable `TaskCompleted` or `TaskFailed` bytes and
   `message_id`; and
5. creates the Agent event-outbox record.

If competing Test Agent instances both compute, uniqueness chooses one durable
outcome. The loser reads and republishes the winner's stored outcome. This is
one durable outcome, not exactly-once computation.

#### Publication-State Transactions

Claiming an eligible outbox record is a short database transaction. Broker
publication occurs outside it. Broker acknowledgment is recorded in another
short transaction guarded by the claim token. Publication attempt certainty is
also recorded durably as defined in Section 13. No database and Event Bus
distributed transaction exists, and the database cannot infer broker
acceptance when the transport outcome is unknown.

### 6. Workflow State Model

The persisted states remain exactly:

`RECEIVED -> PENDING -> DISPATCHED -> COMPLETED | FAILED`.

`COMPLETED` and `FAILED` are terminal. The Orchestrator owns every transition.
State is stored as a constrained value equivalent to this closed set; the
adapter must reject unknown values and the domain must reject illegal edges.

Every state change:

- validates the expected prior state and aggregate revision;
- increments the workflow revision;
- appends one immutable transition record with the same resulting revision;
- uses a pre-established semantic UTC transition timestamp; and
- updates terminal outcome or safe failure data when applicable.

A last-write-wins update is prohibited. Duplicate and late events are recorded
as processing dispositions but do not create duplicate transition history.
Conflicting outcomes fail closed and are observable.

`task_result_deadline` races are serialized on the workflow aggregate. A valid
outcome wins only when its durable outcome-processing transaction accepts the
`DISPATCHED` workflow before the deadline transaction commits. Otherwise the
deadline transition wins and the event is late. This defines a deterministic
durable-acceptance boundary; an in-memory receive timestamp cannot overrule
committed state after a crash.

The deadline transition does not establish whether an in-flight or
unacknowledged broker publication was accepted. A command that was confirmed
or may have been published can still reach the Agent after the workflow becomes
`FAILED`. Its terminal event is processed as late, remains diagnosable, and
cannot reopen or replace the terminal workflow state.

The workflow snapshot is rebuilt only for recovery testing or repair
verification. Normal queries read the snapshot. Verification can fold ordered
transition history and compare its terminal state and revision with the
snapshot; mismatch is an integrity incident, not an automatic overwrite.

### 7. Transition History

Transition history is mandatory and append-only to application runtime
identities. It is the audit companion to the authoritative current-state
record, not the primary event-sourced aggregate.

A transition records, in technology-neutral semantics:

- public `workflow_id`;
- prior state or no prior state;
- new state;
- semantic transition timestamp;
- causing `request_id` or `message_id`;
- `correlation_id`;
- `task_id` and `task_attempt_id` when applicable;
- resulting workflow revision;
- actor or component classification; and
- safe failure classification when relevant.

Internal storage keys never become public identifiers. The same transaction
updates the snapshot and appends history, so neither can commit alone.
Corrections are new explicit records or controlled migration repairs; runtime
code does not update or delete prior transitions.

### 8. Event Sourcing Evaluation

Full Event Sourcing would provide a natural append-only audit and expected
aggregate versions. It would also require:

- reconstruction and snapshot policy;
- domain-event schema evolution across every historical version;
- projection rebuild and migration operations;
- careful separation of internal state-change events from public Event Bus
  contracts;
- replay rules that cannot repeat side effects;
- projection lag and repair observability; and
- an outbox or equivalent bridge to the Event Bus anyway.

The Event Bus has bounded transport retention and is not an event store. Public
task events describe Agent outcomes, not every internal workflow transition.
Using them to reconstruct workflow state would omit request acceptance and
dispatch transitions and would couple persistence to transport history.

The platform therefore selects **current state plus append-only transition
history**, not full Event Sourcing and not current-state-only persistence. This
gives direct queries and recovery with a complete transition audit at lower
operational and migration cost.

### 9. Concurrency Control

The default is a hybrid of:

- unique constraints for correctness-critical identities;
- optimistic revision checks for stale workflow writes;
- short row locks while applying a transition or deadline reconciliation;
- short skip-locked claims plus expiring claim tokens for outbox work; and
- immutable command/outcome identity with unique Agent outcome constraints.

The required scenarios behave as follows:

| Scenario | Control |
| --- | --- |
| Two API requests with one `request_id` | Unique request identity; winner commits, loser reads and compares the stored policy/fingerprint |
| Two Orchestrators process one valid event | Unique domain-inbox key plus short workflow lock and revision check |
| Duplicate valid Event Bus delivery | Logical-consumer/message inbox uniqueness; domain state validation remains a second guard |
| Duplicate pre-identity invalid delivery | Unique transport-delivery locator resolves one stable rejection identity |
| Late task outcome | Terminal-state and expected-attempt validation |
| Conflicting outcomes | First valid terminal transition wins; later conflict is retained as a safe disposition and cannot overwrite |
| Concurrent outbox publishers | `SKIP LOCKED` eligibility, short claim, expiring token, and token-guarded completion |
| Multiple Agent instances receive one command | Broker group ownership reduces concurrency; Agent completed-receipt and one-outcome uniqueness remain authoritative |
| Crashed transaction owner | Database rollback removes uncommitted work; committed claim leases expire; broker redelivers unacknowledged work |

Pessimistic locks are kept short and never cover Agent work or broker calls.
Serializable isolation is not the global default. Advisory or distributed
locks and an actor-style single-writer assumption are rejected because database
constraints and local aggregate locking already provide the required
correctness and survive instance changes.

No durable Agent execution lease is used in Vertical Slice 01; Section 16
defines that boundary.

### 10. Transaction Isolation

PostgreSQL `READ COMMITTED` is the default. Under it, each statement receives a
new committed snapshot, so application code must not implement an invariant as
an unprotected read followed by a write.

The selected protections are tied to anomalies:

- request-id races are prevented by uniqueness, not by an earlier existence
  check;
- lost workflow updates are prevented by revision predicates and short row
  locks;
- two terminal outcomes are serialized on the workflow aggregate and checked
  against terminal state;
- duplicate Agent outcomes are prevented by uniqueness;
- two publishers cannot own the same current claim token; and
- cross-row write skew is avoided by representing first-slice workflow
  invariants under one locked aggregate plus constraints.

`REPEATABLE READ` provides a stable transaction snapshot but can still require
serialization retries and does not replace explicit aggregate invariants.
`SERIALIZABLE` is reserved for a future transaction whose multi-aggregate
invariant cannot be represented by constraints or one locked owner row.
PostgreSQL snapshot semantics must not be assumed to match another database
merely because isolation levels share a name.

Deadlock and serialization failures retry the complete transaction with the
stable intent defined in Section 19. Constraint conflicts are classified
instead of retried blindly.

### 11. Identity and Uniqueness Constraints

Database-enforced uniqueness applies to:

- `request_id` within the Orchestrator acceptance domain;
- `workflow_id`, `task_id`, and `task_attempt_id`;
- task attempt number within one task;
- command and event `message_id` within the producing outbox;
- `(logical_consumer_id, validated_message_id)` within each domain inbox;
- the pre-identity transport-delivery locator composed of logical subscription,
  physical source, partition, and offset;
- the platform-created `rejection_id` associated with one transport-delivery
  locator;
- one Agent completed-receipt identity relationship for a
  `task_attempt_id`;
- one Agent outcome and one terminal event identity per `task_attempt_id`; and
- outbox message identity and per-workflow/channel creation sequence.

Vertical Slice 01 has one accepted attempt numbered `1`. Future active-attempt
rules are application-retry policy and are not defined here.

The same `message_id` intentionally appears in its producer outbox, one or more
broker records after duplicate publication, and the inbox of every independent
consumer. Different consumers therefore record the same message independently;
`message_id` alone is not globally unique across all inbox rows.

Transport delivery coordinates and `rejection_id` are operational identities,
not domain-message fields. The optional original-bytes digest detects or
diagnoses inconsistent redelivery but does not replace the unique transport
delivery locator.

Application prechecks improve error reporting but never replace constraints.

### 12. API Request Idempotency

The persistent model follows ADR-0004 exactly.

- A `request_id` is reserved only when the complete submission transaction
  commits.
- Invalid, unauthorized, unsupported, or Agent-unavailable rejections do not
  reserve it.
- The canonical semantic request is compared through the stored SHA-256
  fingerprint and immutable `fingerprint_policy_version`, never raw JSON.
- A replay is evaluated under the historical policy or its explicit
  compatibility adapter.
- Concurrent first submissions are decided by database uniqueness.
- Equivalent replays return stored workflow identifiers and current durable
  state.
- Different content returns `REQUEST_ID_CONFLICT`.
- If the historical policy cannot be evaluated, the operation fails closed.

The accepted mapping and workflow are created and retained as one integrity
unit. There is no workflow without its mapping and no live mapping pointing to
a missing workflow. Accepted-request data may be deleted only through an
observable retention operation that removes or replaces the entire workflow
idempotency unit after both the API duplicate horizon and workflow retention
obligations end. A retained idempotency tombstone must still contain the
fingerprint policy, identifiers, acceptance result, and enough terminal state
to honor an equivalent replay.

### 13. Transactional Outbox

Both component outboxes follow these rules:

- message bytes, headers represented by the platform contract, logical
  channel, ordering key, and `message_id` are constructed before commit and
  immutable afterward;
- domain state and the new outbox message commit atomically;
- publication is asynchronous;
- broker acknowledgment and publication diagnostics are mutable transport
  state stored separately from immutable message content;
- lost acknowledgments may cause duplicate publication with identical bytes,
  key, and `message_id`;
- records without durably confirmed broker acknowledgment survive restart,
  including attempts whose outcome is unknown;
- publishers may run concurrently through short claims;
- claims expire after process failure and use a unique fencing token so a stale
  owner cannot finalize a newer claim;
- publication retry is bounded per operating cycle with bounded backoff;
- repeated failure becomes an observable failed or quarantined outbox
  disposition and never silently deletes the message; and
- a poison record blocks only later records for the same
  `(logical_channel, workflow_id)` when order requires it, not unrelated
  workflows or channels.

Publication certainty has three minimum semantic states:

- **not attempted or definitively not accepted:** no publication attempt has
  crossed the broker handoff, or the adapter has trustworthy evidence that the
  broker did not accept it;
- **broker acknowledgment durably confirmed:** the broker acknowledged
  acceptance and that acknowledgment was committed to persistence; and
- **attempted, outcome unknown:** an attempt crossed the broker handoff but no
  trustworthy acceptance or rejection was durably established.

Unknown is not equivalent to unpublished. The database retains the immutable
record, original `message_id`, attempt evidence, and unknown certainty. Recovery
may republish the same logical message, producing an allowed duplicate. It
must never reset the record to “not attempted” or claim that database state
proves the broker did not accept it.

Outbox order is not global. Each component assigns a durable creation sequence
within `(logical_channel, workflow_id)`. A publisher may claim only the earliest
nonterminal record for that pair. The broker then provides the accepted
ADR-0005 order within the keyed channel partition.

Vertical Slice 01 has only one outgoing message per component transaction, but
this rule prevents concurrent publishers from weakening the already accepted
workflow order.

A claim is owned by one logical publisher instance and expires according to
database-observed time. A publisher may renew it in a short, token-guarded
transaction before expiry; publication itself never runs inside that
transaction. After expiry, another publisher may take over with a new fencing
token. Every renewal, publication acknowledgment, failure update, or release
must match the current token, so a stale publisher may at worst cause a
duplicate broker publication and cannot overwrite the newer owner's durable
state.

Retry exhaustion does not automatically skip a poison record. The record and
its ordering scope remain blocked until an explicitly authorized operator
assigns a technology-neutral terminal disposition such as manually resolved,
abandoned, superseded, or unrecoverable. The action must preserve the immutable
original record and record the authorizer, timestamp, safe reason
classification, supporting audit evidence, and assessed impact on workflow
correctness.

Later records in the same `(logical_channel, workflow_id)` scope may proceed
only when that terminal disposition explicitly concludes that continuation is
safe. If skipping the record would violate an active workflow's domain
correctness, the workflow fails closed and later publication does not continue.
Retry exhaustion alone never authorizes continuation.

### 14. Inbox and Consumer Deduplication

#### Domain Inbox

The domain inbox is used only after the complete immutable message has been
parsed sufficiently to establish a trusted, contract-valid `message_id`. Its
key is `(logical_consumer_id, validated_message_id)`. Logical consumer identity
is a stable subscription or handler identity, not a process instance.

The processing disposition is inserted or finalized in the same transaction as
all required domain effects. It may retain a bounded safe result summary needed
to answer duplicates. It is never marked completed before those effects
commit.

- A crash before commit leaves no completed domain-inbox record and the broker
  message remains unacknowledged.
- A crash after commit but before broker acknowledgment causes redelivery; the
  consumer returns the stored disposition and acknowledges without repeating
  the transition.
- The same message delivered to another logical consumer has a different key
  and is processed independently.
- A duplicate whose original result was success, late, conflict, or permanent
  rejection returns the same safe disposition.

A message with a validated identity that later fails authorization, semantic,
or supported-contract checks is never labeled successfully processed. Its
stable rejection disposition may be recorded in the domain inbox, while
quarantine-publication progress remains transport recovery state.

#### Transport Rejection and Quarantine Recovery

When trusted domain identity cannot be extracted, no domain-inbox record is
created. A separate recovery record is unique by logical subscription,
physical topic or equivalent source, partition, and offset. It owns one stable
`rejection_id`, safe failure classification, optional SHA-256 digest of the
original received bytes, quarantine-publication certainty, and source-offset
completion status.

These broker coordinates are adapter-owned transport metadata. They remain
outside the ADR-0004 envelope and are not copied into the domain message.

The recovery sequence and crash behavior are the five-step boundary in Section
5. Redelivery resolves the existing transport locator. Lost quarantine
acknowledgment may cause duplicate quarantine publication, but every attempt
uses the same `rejection_id` and remains diagnosable. Durable quarantine
confirmation followed by a source-offset commit is the only successful
terminal path; no malformed message is treated as domain-processed.

Domain-inbox and transport-rejection cleanup are safe only after the related
broker retention and every authorized redrive horizon. Replay after that
horizon does not receive the same durable deduplication guarantee; workflow
transition checks and Agent outcome uniqueness remain defenses, but
side-effecting replay requires a separate policy.

### 15. Agent Completed Receipt and Execution Idempotency

The Agent model distinguishes:

- in-memory command observation, which is not durable acceptance or a work
  claim;
- a future optional execution claim or lease, which is absent from Vertical
  Slice 01;
- deterministic task execution outside a transaction;
- the completed durable command receipt, outcome, terminal event, and event
  outbox, which commit together;
- event publication state; and
- broker command acknowledgment.

The completed durable receipt retains `task_attempt_id`, command `message_id`,
a digest of the immutable command bytes, and the outcome relationship. It
proves that the command identity was durably associated with one accepted
outcome and that the outcome, terminal event, and event outbox committed.
Redelivery can therefore return the stored outcome or republish the stored
event.

It does not prove that execution was durably claimed before work, computation
started only once, computation occurred exactly once, or an external side
effect was fenced.

| Input condition | Behavior |
| --- | --- |
| Same attempt, same message, same bytes | Return or republish the stored outcome and event |
| Same attempt, different message ID | Permanent conflicting-command failure; do not replace the outcome |
| Same message ID, different bytes | Integrity violation; fail closed and quarantine |
| Different attempt ID | Independent future application attempt; not produced in this slice |

Failure windows are explicit:

- before work starts or while deterministic work runs, no command offset is
  acknowledged and redelivery may recompute;
- after work but before outcome commit, redelivery may recompute;
- after outcome commit but before event publication, the Agent publisher sends
  the stored event;
- after publication but before its acknowledgment is recorded, the Agent may
  republish the same event;
- after outcome/event durability but before command offset commit, redelivery
  returns the stored outcome without recomputation.

This provides one accepted durable outcome and one immutable logical terminal
event per attempt. It does not provide universal exactly-once execution or
at-most-once computation. Future side-effecting Agents require a separate
execution policy or ADR.

### 16. Agent Work Claiming and Leases

Vertical Slice 01 does not persist an Agent execution claim or lease.

The Kafka consumer group normally assigns one command partition to one active
Test Agent instance. Rebalance and crash can still duplicate uncommitted work,
so broker ownership is not called exactly-once. The Test Agent is deterministic
and has no external side effects; duplicate computation before durable outcome
commit is acceptable. Database uniqueness ensures that only one outcome and
event are accepted.

A lease would add expiry, renewal, clock assumptions, abandoned-work scanning,
and fencing without preventing an already running unfenced process from
continuing. It is therefore not the simplest correct model for this slice.

Before a side-effecting or materially long-running Agent is introduced, a new
decision must choose among an idempotent external operation, durable claim and
fencing token, side-effect ledger, compensation, or human approval. Broker
partition ownership and outcome uniqueness alone are insufficient for such
work.

### 17. Outbox Publisher Recovery

Orchestrator and Agent publishers use the same recovery contract.

| Failure | Recovery |
| --- | --- |
| Publisher restart | Scan not-attempted, definitively-not-accepted, unknown-outcome, expired-claim, and retryable-failed records |
| Database commit before first publication attempt | Publish the durable immutable record unless a workflow deadline safely suppresses the definitively unaccepted command |
| Broker acknowledgment durably confirmed | Retain the immutable record and confirmation; no recovery publication is required |
| Broker acceptance followed by lost acknowledgment | Preserve unknown certainty and republish the same bytes and `message_id` when recovery retries; consumers deduplicate |
| Crash during or after an in-flight attempt | Claim expires; because acceptance may have occurred, recovery preserves unknown certainty and may republish |
| Malformed stored message | Mark an integrity-failed disposition, retain bytes securely, alert, and continue unrelated workflows |
| Unsupported stored contract | Quarantine the outbox record for operator action; never rewrite it to a newer contract |
| Repeated publication failure | Retain failed state and attempts; block the ordering scope until retry resumes or an authorized terminal operator disposition resolves it |
| Broker outage | Pause publication, preserve backlog, fail readiness when policy requires, and resume after recovery |
| Deadline before first attempt or after definitive nonacceptance | Atomically fail the workflow and visibly suppress further publication while preserving the immutable outbox record |
| Deadline during an in-flight or unknown-outcome attempt | Atomically fail the workflow, retain uncertainty for reconciliation, and allow recovery to republish the same logical command; any Agent outcome is late |
| Concurrent publishers | Claim token and expiration ensure one current owner; stale owners cannot mark a newer claim published |
| Graceful shutdown | Stop claiming, finish or relinquish in-flight work within a bound, and leave unconfirmed records recoverable |

A relational database cannot decide whether the broker accepted an
unknown-outcome attempt. Suppression is permitted only for a command that was
never attempted or is known not to have been accepted. Confirmed or uncertain
commands can still arrive after `task_result_deadline`; their events are late
and cannot reopen the terminal workflow.

A failed record blocks only its workflow and logical channel when publishing a
later record would violate order. It cannot block unrelated workflow keys or
the other logical channel. After retry exhaustion, only the authorized,
audited terminal disposition in Section 13 can release that scope, and only
when continuing is safe. An active workflow fails closed when skipping would
break correctness. No outgoing message is silently discarded or automatically
skipped.

### 18. Ordering Across Persistence and Event Bus

There is no global order across databases, transactions, outboxes, publishers,
topics, or logical channels.

The actual guarantees are:

1. one component transaction orders its state changes, transition records, and
   new outbox records atomically;
2. each outbox assigns creation order within
   `(logical_channel, workflow_id)`;
3. publishers preserve that per-pair order and may publish unrelated pairs
   concurrently;
4. ADR-0005 preserves broker record order within one keyed physical partition
   of one channel;
5. each consumer transaction validates expected workflow revision and state;
   and
6. transition history records accepted Orchestrator order, not broker or wall
   clock total order.

No relationship is inferred between `task-commands` and `task-outcomes` topic
offsets. Database commit timestamps and broker timestamps are diagnostic only
and cannot establish cross-system causality; identifiers and explicit
causation do.

Retry exhaustion preserves the ordering barrier for the affected
`(logical_channel, workflow_id)`. Later records in that scope cannot be claimed
until an authorized terminal disposition records why continuation is safe.
When it is not safe, the workflow fails closed and the barrier remains until
the operator completes the documented terminal resolution. Other workflow keys
and channels continue independently.

### 19. Deadlocks, Serialization Failures, and Retries

Persistence retry is separate from API retry, Event Bus retry, publication
retry, and workflow application retry.

Retryable database classifications initially include transaction deadlock,
serialization failure, transient connection loss proven to occur before commit,
and explicitly classified temporary resource failures. Unique violations,
invalid transitions, schema mismatch, malformed data, permission denial, and
unknown commit outcomes are not blindly retried.

Each transaction has a small configurable maximum attempt count with capped
backoff and jitter. Exact counts and delays are implementation policy.
Transaction code reconstructs the complete unit of work on every attempt from
stable intent.

Before entering the loop, the application fixes:

- `request_id`, `workflow_id`, `task_id`, and `task_attempt_id`;
- every `message_id`;
- semantic transition and message timestamps; and
- immutable message bytes and request fingerprint policy input.

Retries do not change those values. When commit outcome is unknown, recovery
first queries by the stable unique identifiers instead of generating new ones.
After exhaustion:

- an API operation returns a safe failure and instructs reuse of `request_id`;
- a consumer leaves the broker record unacknowledged;
- an outbox record remains recoverable or visibly failed; and
- systemic failures make readiness unhealthy.

Metrics and safe logs record transaction classification, attempt count, delay,
and exhaustion without SQL parameter values.

### 20. Schema Ownership and Migrations

The initial PostgreSQL database contains separately owned component schemas:

- the Orchestrator schema owns accepted requests, workflows, tasks, attempts,
  transitions, its inbox, its outbox, and publisher metadata; and
- one Test Agent deployment schema owns completed command receipts, outcomes,
  its event outbox, and publisher metadata shared by that deployment's
  instances.

Runtime roles can use only their component schema. They cannot directly query
or mutate another component's records. Application cross-schema transactions
are prohibited. Infrastructure backup access does not grant application data
ownership.

Each component versions migrations with its source. A separate migration
identity owns DDL; runtime identities do not create or alter schemas.
Production startup verifies a supported schema version and fails readiness on
mismatch. It does not auto-create or auto-upgrade schemas.

Changes use expand-and-contract when old and new application versions must
overlap:

1. add backward-compatible storage structures;
2. deploy code able to operate during transition;
3. backfill through an observable restartable operation where needed;
4. move writers and readers; and
5. remove obsolete structures only after compatibility evidence.

Every migration has a tested forward path. A down migration is supplied only
when data-preserving rollback is demonstrably safe; otherwise recovery uses a
forward fix or restore under an approved procedure. Database restore is not a
substitute for application rollback planning.

The exact migration tool, names, and release-overlap window remain bounded open
questions.

### 21. Single Database Versus Separate Databases

The initial topology is **one shared physical PostgreSQL database with
component-owned schemas and roles**.

This preserves the two required local transaction boundaries:

- Orchestrator workflow state with its command outbox; and
- Agent completed receipt and outcome with its event outbox.

Those transactions never span components, so the schemas can later move to
separate physical databases without changing domain or message contracts.

Separate databases would improve failure and security isolation and independent
scaling, but would double local containers, backup jobs, connection
configuration, restore coordination, and migration operations before the slice
needs it. One undivided schema or shared tables would be locally simple but
would weaken ownership and least privilege.

The selected shared server is a shared failure domain. It is not a high
availability claim. A future Agent with different scaling, regulatory, or
failure-isolation requirements may receive its own database through a new
topology decision.

### 22. Persistence Availability and Failure Behavior

All durability-dependent operations fail closed.

| Component operation | Persistence unavailable or commit fails |
| --- | --- |
| Workflow submission | Create nothing durably; return a safe temporary/internal failure and require the same `request_id` on retry |
| Workflow retrieval | Return no stale in-memory state; report dependency failure |
| Orchestrator event processing | Do not acknowledge the Event Bus record |
| Orchestrator outbox publishing | Stop claiming or updating records; committed backlog and every publication-certainty state remain unchanged |
| Agent command handling | Do not acknowledge work that requires a completed-receipt/outcome commit |
| Agent event publication | Preserve committed event outbox; resume later |
| Health | Liveness may remain healthy; readiness becomes unhealthy when required persistence or schema compatibility is absent |
| Shutdown | Stop intake, bound in-flight completion, roll back incomplete transactions, and leave messages unacknowledged |

In-memory buffering cannot substitute for a required durable write. Recovery
resumes from database records and unacknowledged broker messages after
connectivity and schema compatibility return.

Loss of persistence during an in-flight broker publication cannot be converted
to definitive nonacceptance. Recovery reads the last durable certainty state;
if the attempt may have crossed the broker handoff, it is treated as unknown
and reconciled or republished with the same immutable identity.

Agent unavailability does not affect workflow queries, but persistence
unavailability necessarily does because the database is the workflow source of
truth.

### 23. Data Retention and Cleanup

Exact periods are deployment policy, but relationships are architectural:

- current workflow state, tasks, attempts, transitions, and accepted-request
  mappings remain an integrity unit for the supported workflow and API
  idempotency horizon;
- accepted-request policy data remains at least as long as duplicate
  submissions can be honored and cannot point to a deleted workflow;
- domain-inbox and transport-rejection records remain at least as long as
  broker retention plus every authorized quarantine/redrive window;
- Agent completed receipts and outcomes remain at least as long as a command
  can be replayed or an outcome must be queried or republished;
- completed outboxes and publication metadata remain until acknowledgment,
  recovery, audit, backup, and lost-acknowledgment windows are satisfied;
- failed, quarantined, and terminally disposed outbox records retain their
  immutable original content, authorization, reason, impact assessment, and
  audit evidence until all recovery and audit requirements complete; and
- transition history follows workflow audit and privacy policy and is not
  discarded merely because current state is terminal.

Cleanup is bounded, restartable, idempotent, observable, and ordered by
dependency. It never deletes deduplication, rejection identity, completed
receipts, outcomes, or poison-record disposition evidence while corresponding
messages remain replayable or an ordering decision remains auditable. It
records safe counts, oldest eligible age, last progress, and failures.
Storage-pressure cleanup cannot silently shorten a correctness window.

### 24. Backup, Restore, and Disaster Recovery

Infrastructure must provide consistent database backups and, where the selected
deployment supports it, point-in-time recovery. Backups include both component
schemas, migration state, outboxes, domain inboxes, transport-rejection
records, completed receipts, outcomes, and transition history. Restore
procedures and data integrity are tested, not inferred from a successful backup
command.

Database restore and Event Bus restore or replay are coordinated:

- restored outboxes without confirmed acknowledgment may republish with stable
  IDs according to their retained certainty;
- broker replay after database restore is deduplicated by restored domain
  inboxes, transport-rejection records, and authoritative state;
- consumer offsets are broker state, not database truth, and may be reset only
  under an explicit recovery plan;
- restored Agent outcomes permit stable event republication;
- a database restored to an earlier point than broker state may process later
  retained messages to catch up where contracts permit; and
- a broker restored earlier than the database receives republished outbox
  records as needed.

No architecture can preserve a committed accepted request that lies beyond the
database recovery point. Before reopening writes after data loss, operators
must establish the chosen database and broker recovery points, assess missing
accepted mappings and side effects, and authorize reconciliation. Otherwise an
API retry could create a second workflow for data lost by restore.

Backing up only the broker is insufficient. RPO, RTO, backup frequency,
off-machine copies, topology, and recovery authority remain future deployment
policy.

### 25. Security and Privacy

Persistence requires:

- encrypted connections and certificate verification outside explicitly
  isolated local development;
- encryption at rest and secure backup storage according to deployment data
  classification;
- distinct Orchestrator, Agent, migration, backup, and administration
  identities;
- deny-by-default privileges and no cross-component runtime access;
- runtime credential injection outside source control, with supported
  rotation;
- restricted database and backup administration with auditable use;
- parameterized SQL and runtime validation at every trust boundary;
- no secrets in workflow, outbox, domain-inbox, transport-rejection, completed
  receipt, transition, failure, or migration records;
- minimized workflow input and Agent outcome retention;
- protected access to full workflow input, outcomes, outbox bytes, and
  backups; and
- sanitized failure classification rather than credentials, stack traces,
  provider payloads, or unrestricted SQL errors.

Database logs and audit facilities must not be configured to capture sensitive
bind values by default. Destructive restore, purge, or repair operations require
the human approval defined by `SECURITY.md`. This ADR selects no identity
provider or secrets manager.

### 26. Observability

Without selecting a backend, components expose safe signals for:

- transaction success, failure, classification, attempt count, and latency;
- deadlocks, serialization failures, lock waits, and long transactions;
- connection-pool use, waiters, timeouts, and saturation;
- workflow revision and transition conflicts;
- equivalent and conflicting `request_id` reuse;
- duplicate valid-message detection, domain-inbox growth, and
  transport-rejection growth;
- outbox backlog count, oldest age, claims, publication attempts, and failed
  records, including not-attempted, confirmed, and unknown-outcome certainty;
- poison-blocked ordering scopes, terminal operator dispositions,
  authorizations, and reason classifications;
- Agent completed-receipt, command-digest, and outcome conflicts;
- expired deadlines, safely suppressed messages, uncertain publications, and
  late outcomes;
- cleanup eligibility, progress, and failure;
- migration version and compatibility;
- backup/restore status where infrastructure exposes it; and
- storage and transaction-history growth.

Safe log context includes `workflow_id`, `request_id`, `task_id`,
`task_attempt_id`, `message_id`, `correlation_id`, transition name, revision,
and transaction classification. Logs exclude complete workflow input, outcomes,
credentials, message bodies, database connection strings, and sensitive SQL
parameter values.

### 27. Local Development

The default persistence environment is a test- or developer-owned PostgreSQL
container with a persistent volume only when restart work requires one.

- Unit, contract, and most component tests use in-memory port fakes for domain
  behavior.
- SQLite is optional for isolated, database-agnostic utility tests, but it is
  not the persistence adapter substitute and proves no PostgreSQL semantics.
- Integration and resilience tests start an isolated real PostgreSQL instance
  owned by the test run, whether through a test-container harness or the local
  stack.
- Developer-owned persistent volumes support manual restart experiments but
  are not shared automated-test state.
- A separately managed database makes a test external-service testing and
  requires opt-in configuration, least-privilege credentials, and cleanup.

Only the selected real database can validate row locks, skip-locked claims,
isolation, constraints under concurrency, migrations, restart recovery, and
driver behavior.

### 28. Testing Strategy

Tests follow `docs/testing/README.md` and use controlled concurrency and failure
injection. Unit tests never claim to prove database transaction semantics.

Required real-database integration and resilience coverage includes:

- API idempotency: concurrent equivalent and conflicting `request_id` values,
  lost response after commit, and historical fingerprint-policy evaluation;
- workflow concurrency: duplicate, late, and conflicting outcomes, invalid
  transitions, two Orchestrators, optimistic conflicts, deadlock, and
  serialization retry;
- outbox: commit before publisher start, broker outage, lost acknowledgment,
  duplicate publication, crash and restart, concurrent publishers,
  per-workflow/channel order, poison record isolation, retry-exhaustion
  blocking, authorized terminal resolution, unsafe-continuation failure,
  deadline before the first publication attempt, deadline during an in-flight
  publication, broker acceptance followed by lost acknowledgment, republishing
  after deadline, late Agent outcome, no workflow reopening, and claim
  takeover;
- domain inbox: crash before commit, crash after commit before broker
  acknowledgment, duplicate validated `message_id`, independent logical
  consumers, valid-identity permanent rejection, cleanup, and replay;
- transport rejection: malformed JSON, missing or invalid `message_id`,
  unparseable envelope, conflicting duplicate properties, stable
  source-coordinate identity, optional byte-digest mismatch, crash before and
  after quarantine publication, lost quarantine acknowledgment, duplicate
  quarantine publication with one `rejection_id`, and crash after quarantine
  confirmation before source-offset commit;
- Agent durability: duplicate and conflicting commands, different bytes under
  one message ID, crash before/during/after execution and around outcome/event
  publication, and one durable outcome per attempt;
- migrations: forward migration, supported overlap, mismatch fail-fast,
  forward-fix or safe rollback procedure, and concurrent-start protection; and
- recovery: database restart and connection loss, cleanup restart, consistent
  backup/restore, outbox/inbox recovery, and coordinated broker replay.

Every correctness-critical failure test must assert both the durable database
records and externally visible behavior.

### 29. Selected Python Database Client

For PostgreSQL, the evaluated options are:

| Option | Strengths | Costs and reason |
| --- | --- | --- |
| Psycopg 3 | Officially supports Python 3.14, native asyncio, sync APIs, transactions, server-side binding/prepared statements, COPY/bulk operations, static typing, and separate sync/async pooling without requiring an ORM | PostgreSQL-specific and requires adapter-owned SQL, mapping, migration, and observability; selected because those semantics must remain explicit |
| asyncpg | Mature high-performance native asyncio PostgreSQL client with pooling and prepared statements | Async-only API and PostgreSQL-specific type model provide no first-slice correctness advantage over Psycopg 3; not selected |
| SQLAlchemy Core over Psycopg | Mature query construction, pooling, dialects, and a possible Oracle migration aid; supports async Psycopg | Adds another transaction and abstraction layer while correct locks, conflict codes, and PostgreSQL features still need explicit adapter knowledge; not selected initially |
| SQLAlchemy ORM | Unit of work, mappings, relationships, and broad ecosystem | Identity maps, flush timing, implicit loading, and ORM model coupling can obscure exact transaction order and are unnecessary for explicit repositories; rejected |

The initial adapter uses **Psycopg 3 with its async API and supported connection
pool**, behind platform-owned repositories. Parameterized statements are
mandatory. Driver connections, rows, exceptions, transaction states, and pool
types never cross the adapter boundary.

Psycopg's bulk and pipeline capabilities are available inside the adapter only
when semantics remain unchanged. The exact pinned release and binary/source
installation choice must be validated on CPython 3.14 for Windows development
and the target Linux/Unraid architecture. The exact migration library remains
open; migrations may use reviewed SQL without making SQL a domain contract.

If Oracle were selected in a future ADR, `python-oracledb` would be the leading
driver because its thin mode, asyncio support, pooling, and Python 3.14 support
meet the same adapter boundary. That future choice is not made here.

### 30. Coherent Persistence Architecture

The selected architecture is:

- PostgreSQL as the initial relational persistence technology;
- one initial physical database with separate Orchestrator and Test Agent
  schemas and least-privilege runtime roles;
- current workflow state plus mandatory append-only transition history;
- no full Event Sourcing;
- component-owned persistence ports and migrations;
- Psycopg 3 async access behind explicit repositories, without an ORM;
- database-enforced identity and outcome uniqueness;
- PostgreSQL Read Committed by default;
- optimistic workflow revisions plus short row locks for transition
  application;
- transactional Orchestrator and Agent outboxes;
- atomic valid-message domain-inbox/domain updates;
- separate durable pre-identity transport-rejection and quarantine recovery;
- atomic Agent completed-receipt/outcome/terminal-event/event-outbox
  persistence after deterministic work;
- explicit not-attempted, confirmed, and unknown outbox-publication certainty;
- authorized terminal disposition before a poison outbox ordering barrier can
  be released;
- short skip-locked outbox claims with expiring fenced tokens;
- no Agent execution lease in Vertical Slice 01;
- bounded database transaction and publication retries;
- real-PostgreSQL integration, concurrency, resilience, migration, and restore
  tests;
- coordinated database and broker recovery; and
- no distributed transaction between PostgreSQL and the Event Bus.

#### Guarantee and Recovery Evidence

| Guarantee | Durable record | Transaction and enforcement | Crash window and recovery | Required proof |
| --- | --- | --- | --- | --- |
| One workflow per accepted `request_id` | Accepted request plus workflow | Submission transaction; unique `request_id` and fingerprint policy | Before commit: nothing; after commit/lost response: retry resolves existing | Concurrent equivalent/conflicting and lost-response tests |
| No state-to-command loss | Workflow, transitions, Orchestrator outbox | One submission transaction; immutable outbox ID | Commit before publish: publisher recovers; lost ack remains unknown and may duplicate the same ID | Commit/publisher crash/lost-ack tests |
| Legal workflow transitions only | Current workflow revision plus transition history | Outcome/deadline transaction; row lock, revision, state check | Rollback leaves old state; after commit redelivery sees inbox/terminal state | Duplicate, late, conflict, invalid-edge, two-instance tests |
| One processed effect per valid consumer/message | Domain-inbox disposition | Inbox and domain update transaction; unique `(logical_consumer_id, validated_message_id)` | Before commit redelivery retries; after commit/before offset duplicate returns disposition | Both crash-window and independent-consumer tests |
| Stable malformed-message quarantine | Transport rejection record | Unique subscription/source/partition/offset locator plus stable `rejection_id`; quarantine confirmation precedes source offset | Crash or lost acknowledgment may duplicate quarantine with the same rejection identity; confirmed redelivery advances the source | Pre-identity corruption and every quarantine crash-window test |
| One durable Agent outcome | Completed receipt, outcome, terminal event, Agent outbox | One Agent outcome transaction; unique attempt/outcome/event | Before commit deterministic recomputation; after commit publisher/completed-receipt recovery | Every Agent crash-window and concurrency test |
| Honest publication certainty | Immutable outbox bytes, stable message ID, and certainty state | Token-guarded attempt and acknowledgment updates never equate unknown with unattempted | Ack loss retains unknown and may republish the same bytes; confirmed acceptance remains confirmed | First-attempt, in-flight, lost-ack, and duplicate-publication tests |
| Publisher ownership recovery | Outbox claim metadata | Short claim transaction; expiry and fencing token | Crash leaves expiring claim; new owner takes over; stale owner cannot finalize | Concurrent publisher, expiry, and stale-token tests |
| Per-workflow/channel order | Outbox creation sequence and terminal operator disposition | Earliest-eligible claim rule plus broker key; retry exhaustion preserves the barrier | Only authorized safe disposition releases later records; unsafe skip fails the workflow closed | Concurrent publisher, poison blocking, disposition, and ordering tests |
| Deadline reaches terminal state | Workflow, transition, attempt, outbox certainty | Deadline transaction; lock/revision; suppression only for definite nonacceptance | In-flight or unknown publication is retained and may republish; late event cannot reopen terminal state | Before-attempt, in-flight, unknown, republish-after-deadline, and late-event tests |
| Historical audit matches current state | Snapshot plus transition history | Every transition transaction writes both | No partial commit; mismatch after external corruption raises incident | Fold-and-compare integrity test |
| Restore can resume transport work | Backed-up outboxes, domain inboxes, rejection records, completed receipts, outcomes | Consistent database backup plus coordinated broker procedure | Older/newer recovery points cause replay or republication, never silent assumption | Restore with broker replay and offset-reset tests |

None of these guarantees means an irreversible external effect occurs exactly
once. The first Test Agent has no such effect.

### 31. Consequences

#### Positive Consequences

- Relational constraints and transactions directly enforce first-slice
  invariants.
- The source of truth, audit history, and transport recovery records have clear
  owners and meanings.
- Outboxes close the state-to-publication loss window without a distributed
  transaction.
- Multiple component instances can recover through database records rather
  than process memory or distributed locks.
- PostgreSQL is practical for local Docker and Unraid while retaining broad
  hosting choices.
- Component schemas and persistence ports preserve a credible later path to
  separate databases or another relational adapter.

#### Negative Consequences

- PostgreSQL, migrations, backup, restore, retention, pools, and outbox workers
  add operating responsibilities.
- One physical database is a shared failure domain and not highly available.
- Exactly-once computation and side effects remain intentionally unprovided.
- Transition, domain-inbox, transport-rejection, completed-receipt, and outbox
  records increase storage and cleanup work.
- Explicit SQL and concurrency behavior require careful review and
  real-database tests.
- PostgreSQL-specific claiming and error classification exist inside adapters.

#### Migration Impact

There is no existing implementation or data to migrate. Initial work must add
component-owned migrations, roles, repositories, recovery queries, and
Psycopg dependencies only after this ADR is Accepted.

A future database migration must preserve identifiers, fingerprints and policy
versions, workflow revisions, transition order, immutable message bytes,
publication dispositions, inbox keys, receipts, outcomes, and retention
horizons. It requires dual-version conformance and cutover planning; swapping a
connection string is insufficient.

#### Developer Impact

Developers use in-memory repositories for fast logic tests and a test-owned
PostgreSQL container for adapter semantics. They must understand transaction
scope, commit uncertainty, row locking, revision conflicts, and message
immutability. Database exceptions and schema models remain adapter internals.

#### CI Impact

Future CI can run fast tests without infrastructure and isolated integration,
resilience, migration, and restore suites with a pinned PostgreSQL container.
Those suites need more time, disk, controlled concurrency, and failure
diagnostics. This ADR does not claim that CI is already configured.

#### Operational Impact

Operators must manage database health, durable storage, credentials, schema
versions, connections, locks, outbox/inbox growth, cleanup, backups, restore
tests, and capacity. A single-node deployment needs explicit backup and data
loss expectations; two machines do not automatically provide database HA.

#### Security Impact

The database contains workflow inputs, outcomes, commands, and audit history.
It becomes a high-value trust boundary requiring encryption, least privilege,
retention, secure backups, redaction, patching, and approved destructive
operations. Separate component roles reduce but do not eliminate the impact of
one physical server.

#### Future Review Triggers

Review or supersede this ADR when:

- a side-effecting Agent requires execution claims, fencing, compensation, or
  an external idempotency protocol;
- measured contention invalidates the aggregate-locking or claiming model;
- components require independent failure, scale, regulatory, or retention
  domains;
- one or two machines cannot meet accepted RPO, RTO, or availability targets;
- PostgreSQL or Psycopg loses required Python, platform, or maintenance support;
- an Oracle deployment offers a documented operational or organizational
  advantage that outweighs migration cost;
- full Event Sourcing has a demonstrated replay or temporal-query requirement;
- cross-workflow transactions or global ordering become required; or
- retention, privacy, or archival requirements exceed the selected model.

### 32. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Incorrect transaction boundary | Name every atomic unit, review repository composition, and failure-inject before/after every commit |
| State commits without outgoing message | Require same transaction and prove outbox recovery |
| Malformed message has no trusted `message_id` | Use a separate unique transport-delivery locator and stable `rejection_id`; never invent domain identity |
| Quarantine publication duplicates after lost acknowledgment | Preserve one `rejection_id`, durable publication certainty, and source coordinates so duplicates remain diagnosable |
| Duplicate durable Agent outcome | Enforce unique attempt outcome and atomically store event outbox |
| Completed receipt is mistaken for a pre-execution claim | Name it explicitly, record it only with outcome/event commit, and test allowed deterministic recomputation |
| Stale workflow write | Require revision predicates and short aggregate locks |
| Write skew | Place first-slice invariant under one owner row or constraint; use Serializable only for a proven multi-row invariant |
| Deadlock or serialization failure | Keep lock order and transactions short; bounded full-transaction retry from stable intent |
| Lock contention | Observe waits, avoid network/work inside transactions, and measure before changing strategy |
| Long transaction | Execute Agent work and publish to broker outside database transactions |
| Unknown publication is treated as unpublished | Persist explicit certainty, retain immutable identity, and permit same-message republication without claiming broker rejection |
| Deadline silently suppresses a possibly published command | Suppress only definite nonacceptance; retain and reconcile unknown attempts, and reject late outcomes without reopening |
| Poison record is skipped after retries | Preserve the ordering barrier until an authorized audited terminal disposition proves continuation safe; otherwise fail closed |
| Outbox backlog | Observe count/age, recover claims, isolate poison records, expose blocked scopes, and relate alerts to deadlines |
| Domain-inbox or transport-rejection growth | Tie retention to broker replay and redrive horizons and use restartable cleanup |
| Premature cleanup | Enforce dependency order and test cleanup followed by delayed replay |
| Database and broker restore mismatch | Coordinate recovery points, preserve IDs, rehearse replay/republication, and keep writes closed during reconciliation |
| Agent crash during external side effect | Prohibit treating first-slice outcome uniqueness as protection; require a future side-effect policy |
| ORM hides SQL semantics | Use direct Psycopg repositories initially; keep transaction and lock behavior explicit |
| PostgreSQL features leak through ports | Express capabilities, translate errors, and run alternative-adapter conformance if replacement is attempted |
| Migration blocks deployment | Use reviewed, measured expand-and-contract changes and separate migration identity |
| Single-node database loss | State the limitation, use tested off-node backups, and define RPO/RTO before production claims |
| Storage exhaustion | Observe growth, bound retention safely, reserve capacity, and fail visibly rather than deleting correctness records |
| Sensitive data in backups | Encrypt, restrict, minimize, retain deliberately, and test secure disposal |
| Oracle portability assumptions fail | Do not claim SQL portability; require Oracle adapter and isolation/locking conformance tests |
| PostgreSQL managed services differ | Depend on documented PostgreSQL capabilities, then validate extensions, versions, backup, and failover per provider |
| Unknown commit result creates duplicates | Query by precreated stable identifiers before retry and let constraints arbitrate |
| Clock error expires claims or workflows early | Use database-observed operational lease time, bounded margins, and semantic deadline tests; do not derive business order from clock alone |

### 33. Assumptions

- ADR-0001 through ADR-0005 remain Accepted.
- Vertical Slice 01 retains one deterministic, non-side-effecting Test Agent,
  one task, one attempt, one command, and one terminal event.
- CPython 3.14 remains the accepted runtime.
- A supported Linux container image is available for the target Unraid
  architecture.
- One physical database failure domain is acceptable for local development and
  initial non-HA deployment; production availability is unresolved.
- Workflow input remains synthetic for the first slice, but persistence is
  protected as though inputs and outcomes may become sensitive later.
- Infrastructure can provide durable storage and inject separate credentials.
- Database and broker clocks are reasonably synchronized for operations, but
  neither establishes cross-system ordering.
- Exact load, retention, RPO, RTO, backup, identity, and monitoring
  requirements have not been accepted.
- No managed PostgreSQL or Oracle service is assumed.
- No external Agent side effect occurs in the first slice.

### 34. Open Questions

These questions do not leave core technology or guarantees undecided:

1. Which supported PostgreSQL major, patch, and container digest are pinned?
2. What exact component schema and role names are used?
3. Which migration tool manages reviewed component-owned migrations?
4. What application/schema overlap window and migration lock policy apply?
5. What minimum and maximum connection-pool sizes fit each deployment?
6. What bounded deadlock/serialization retry count and backoff are used?
7. What outbox claim duration, renewal margin, and publication retry budget are
   used?
8. What exact retention periods and cleanup batch sizes satisfy API, broker,
   audit, and privacy policies?
9. What backup frequency, RPO, RTO, off-machine storage, and restore authority
   apply to each deployment?
10. What final production database topology is required?
11. Which operational thresholds make readiness unhealthy or trigger alerts?
12. What separate execution policy governs the first side-effecting Agent?

### 35. Explicitly Out of Scope

This ADR does not decide:

- Event Bus technology, Kafka topic design, or application retry policy;
- API framework or additional API behavior;
- authentication provider, secrets manager, or monitoring backend;
- Docker Compose, Kubernetes, or final production topology;
- AI provider, AI Router, or LangGraph;
- a search, vector, analytics, reporting, or archival database;
- schema/table/column names or physical SQL definitions;
- exact retention, pool, retry, backup, RPO, or RTO values;
- side-effecting Agent execution beyond requiring a later decision; or
- a managed cloud database service.

### 36. Acceptance Checklist

- [ ] PostgreSQL is approved as the initial persistence technology.
- [ ] The Oracle-versus-PostgreSQL rationale, including owner expertise,
      licensing, editions, containers, and hosting options, is accepted.
- [ ] One physical database with component-owned schemas and roles is approved
      for the first slice.
- [ ] Cross-component table access and application cross-schema transactions
      are prohibited.
- [ ] Persistence ports expose required capabilities without database objects.
- [ ] Current workflow state is authoritative and transition history is
      mandatory and append-only.
- [ ] Full Event Sourcing is rejected for the first slice.
- [ ] The submission transaction atomically creates the accepted mapping,
      workflow, task, attempt, three logical transitions, and command outbox.
- [ ] `RECEIVED`, `PENDING`, and `DISPATCHED` remain separate logical
      transitions even when committed together.
- [ ] Valid-message outcome processing atomically combines domain-inbox
      disposition, transition, history, and required state.
- [ ] Agent completed receipt, outcome, terminal event, and event outbox commit
      together after deterministic execution.
- [ ] The completed receipt is not a pre-execution claim, exactly-once
      computation proof, or side-effect fence.
- [ ] No database/Event Bus distributed transaction or exactly-once side-effect
      claim is made.
- [ ] Read Committed, unique constraints, revisions, short row locks, and
      skip-locked fenced claims are approved.
- [ ] Identity and uniqueness rules cover requests, workflows, tasks, attempts,
      messages, consumers, transport deliveries, rejections, outcomes, and
      outboxes.
- [ ] ADR-0004 request fingerprint and historical-policy behavior is preserved.
- [ ] Immutable outbox bytes, asynchronous publication, explicit
      not-attempted/confirmed/unknown certainty, lost-acknowledgment duplicates,
      and restart recovery are approved.
- [ ] Domain-inbox records require validated immutable `message_id` values and
      commit with domain effects.
- [ ] Pre-identity malformed deliveries use a separate durable transport
      rejection identity, quarantine recovery flow, and source-offset barrier.
- [ ] Agent duplicate, conflict, byte-integrity, and crash-window behavior is
      approved.
- [ ] No Agent execution lease is required for the deterministic Test Agent.
- [ ] Publisher claim expiry, fencing, and graceful shutdown are approved.
- [ ] Deadline suppression applies only to definite broker nonacceptance;
      uncertain commands remain reconcilable and late events cannot reopen
      workflows.
- [ ] Poison retry exhaustion preserves its ordering barrier until an
      authorized audited terminal disposition determines continuation is safe.
- [ ] Ordering is limited to the component transaction and
      `(logical_channel, workflow_id)` publication path.
- [ ] Persistence retries preserve all identifiers, timestamps, and immutable
      message bytes.
- [ ] Component-owned migrations, separate migration identities, version
      checks, and expand-and-contract policy are approved.
- [ ] Persistence failures fail closed and required messages remain
      unacknowledged.
- [ ] Retention relationships prevent premature loss of idempotency,
      deduplication, rejection identity, completed receipt, outcome, poison
      disposition, and recovery evidence.
- [ ] Database backup/restore is coordinated with broker replay and offsets.
- [ ] Security, privacy, least privilege, parameterization, redaction, and
      secure backup requirements align with `SECURITY.md`.
- [ ] Required persistence signals are approved without selecting a monitoring
      backend.
- [ ] In-memory, SQLite, real-PostgreSQL, and external-service test boundaries
      are clear.
- [ ] Concurrency, crash-window, migration, cleanup, backup, and restore tests
      use the real selected database where semantics matter.
- [ ] Psycopg 3 async plus its supported pool is approved behind repositories.
- [ ] Every operational risk has an accepted mitigation or review trigger.
- [ ] Remaining questions are bounded implementation or deployment policy.
- [ ] The identified Vertical Slice ambiguities are visible and not silently
      treated as accepted architecture.
- [ ] Reviewers confirm consistency with ADR-0001 through ADR-0005, Vertical
      Slice 01, the test strategy, `SECURITY.md`, and `AGENTS.md`.

The review completed on 2026-07-27 found the architecture-level persistence
decisions complete. Pre-identity malformed deliveries have durable transport
identity, completed Agent receipt semantics are explicit, unknown broker
publication remains uncertain and recoverable, and poison outbox ordering has
an authorized terminal-resolution rule. The remaining questions in Section 34
are bounded implementation or deployment policy. No conflict remains with
ADR-0001 through ADR-0005 or the intended Vertical Slice 01 behavior.

## Related Decisions

- [ADR-0001: Core Design Principles](ADR-0001-core-design-principles.md)
- [ADR-0002: Platform Communication and State](ADR-0002-platform-communication-and-state.md)
- [ADR-0003: Runtime and Development Tooling](ADR-0003-runtime-and-development-tooling.md)
- [ADR-0004: API and Contract Standards](ADR-0004-api-and-contract-standards.md)
- [ADR-0005: Event Bus and Messaging Infrastructure](ADR-0005-event-bus-and-messaging-infrastructure.md)

## References

- [Platform Architecture](../README.md)
- [Vertical Slice 01](../../implementation/vertical-slice-01.md)
- [Platform test strategy](../../testing/README.md)
- [Repository security policy](../../../SECURITY.md)
- [Repository agent guidance](../../../AGENTS.md)
- [PostgreSQL transaction isolation](https://www.postgresql.org/docs/current/transaction-iso.html)
- [PostgreSQL constraints](https://www.postgresql.org/docs/current/ddl-constraints.html)
- [PostgreSQL locking clauses](https://www.postgresql.org/docs/current/sql-select.html)
- [PostgreSQL backup and restore](https://www.postgresql.org/docs/current/backup.html)
- [PostgreSQL continuous archiving and point-in-time recovery](https://www.postgresql.org/docs/current/continuous-archiving.html)
- [PostgreSQL License](https://www.postgresql.org/about/licence/)
- [Psycopg features and supported versions](https://www.psycopg.org/features/)
- [Psycopg connection pools](https://www.psycopg.org/psycopg3/docs/advanced/pool.html)
- [Oracle Database licensing information](https://docs.oracle.com/en/database/oracle/oracle-database/26/dblic/database-licensing-information-user-manual.pdf)
- [Oracle AI Database Free](https://www.oracle.com/database/free/)
- [Oracle JSON data type](https://docs.oracle.com/en/database/oracle/oracle-database/26/adjsn/json-data-type.html)
- [`python-oracledb`](https://oracle.github.io/python-oracledb/)
- [SQLAlchemy PostgreSQL dialect](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html)
- [SQLAlchemy Oracle dialect](https://docs.sqlalchemy.org/en/20/dialects/oracle.html)
