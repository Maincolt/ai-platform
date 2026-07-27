# ADR-0007: Agent Execution Model and Lifecycle

- **Status:** Accepted
- **Date:** 2026-07-27
- **Supersedes:** None
- **Superseded by:** None

## Context

ADR-0002 defines Agents as loosely coupled components selected through an
Orchestrator-owned Capability Registry. ADR-0004 defines `ExecuteTask`,
terminal-event contracts, identifiers, and idempotency semantics. ADR-0005
selects at-least-once command delivery and manual acknowledgment. ADR-0006
defines the Agent's completed-receipt, outcome, and event-outbox transaction.

Those decisions intentionally leave the in-process execution model unresolved.
Without an explicit model, an Agent could accept unbounded work, block broker
polling, treat process memory as durable state, leak framework concepts into
contracts, or imply that cancellation and timeout stop external effects.

The first implementation is the deterministic `text.word-count` Test Agent in
Vertical Slice 01. It has one task attempt, no AI provider, no external side
effect, no explicit cancellation command, and no durable execution lease. The
decision must remain extensible without designing runtime support for future
Agent categories.

### Existing Documentation Alignments and Ambiguities

The accepted ADRs do not conflict on Agent ownership or durability. The
following wording requires explicit interpretation:

- ADR-0002 says Agents register capability manifests and availability, while
  Vertical Slice 01 uses a configuration-backed manifest loaded by the
  Orchestrator and a readiness check. This ADR preserves that deliberate
  first-slice constraint; it does not introduce dynamic registration.
- ADR-0005 and parts of Vertical Slice 01 use the general term command
  "receipt." ADR-0006 now defines the authoritative first-slice meaning as a
  **completed command receipt** committed atomically with outcome, terminal
  event, and event outbox. No durable pre-execution receipt or execution lease
  exists.
- Vertical Slice 01 still contains stale technology-status text and earlier
  filenames for ADR-0005 and ADR-0006. These are documentation alignments, not
  conflicting execution decisions.
- No accepted contract defines an explicit cancellation, progress, heartbeat,
  approval, or task-started message. This ADR cannot imply that such messages
  exist.

## Decision Drivers

The execution model is evaluated against:

- deterministic recovery under at-least-once delivery;
- durable one-outcome arbitration without exactly-once computation claims;
- bounded concurrency, memory, queueing, and dependency retry;
- partition ordering and responsive broker polling;
- graceful startup, draining, shutdown, and process recovery;
- distinct deadline, timeout, and cancellation semantics;
- future long-running, AI-backed, and side-effecting work;
- Python 3.14, Docker, Unraid, and one or two physical machines;
- multiple Agent instances and consumer-group rebalances;
- observable and testable failure windows;
- least privilege and untrusted-input handling; and
- framework-neutral platform contracts and clear Orchestrator ownership.

Correctness, explainability, and recovery take priority over maximum task
throughput.

## Decision

### 1. Agent Definition

An Agent is a logical, deployable platform component that:

- consumes supported task commands through the Event Bus port;
- owns execution logic for one or more bounded capabilities;
- validates target, contract, capability, input, and policy compatibility;
- executes admitted work;
- durably records one accepted outcome per `task_attempt_id`;
- creates one immutable logical terminal event;
- recovers from durable completed receipts, outcomes, and event outboxes; and
- retains only bounded transient execution state in process.

An Agent does not own workflow orchestration, workflow state, task sequencing,
application retry, or global Agent selection.

An Agent is not inherently an LLM, prompt, tool, workflow, consumer group,
Python class, operating-system process, LangGraph graph, CrewAI Agent, or
AutoGen Agent. Any of those may be an internal implementation detail behind the
platform Agent and capability ports. One Agent deployment may have multiple
process instances, and one process may execute multiple bounded tasks.

### 2. Agent Responsibilities

The Agent owns:

- command consumption and acknowledgment;
- transport, contract, target, capability, input, and policy validation;
- duplicate and identity-conflict detection;
- execution admission, bounded concurrency, and local backpressure;
- technology-neutral execution-context construction;
- local timeout and cooperative-cancellation observation;
- capability execution and dependency access through explicit ports;
- safe error classification;
- completed-receipt, outcome, terminal-event, and event-outbox persistence;
- terminal-event publication recovery;
- task-level logging, metrics, health, readiness, draining, and shutdown.

The Agent explicitly does not own:

- workflow-state or transition decisions;
- Orchestrator `task_result_deadline` reconciliation;
- application retry or creation of a new `task_attempt_id`;
- task ordering across a workflow;
- global capability selection or scheduling;
- user authentication or API request idempotency;
- Event Bus administration;
- cross-Agent orchestration; or
- permanent workflow audit history.

The Orchestrator remains responsible for selection, dispatch, workflow state,
deadlines, terminal acceptance, and future application-level retries.

### 3. Agent Types

The following are **explanatory risk categories**, not first-slice runtime
classes or new contract enum values:

| Category | Execution characteristic | Required treatment |
| --- | --- | --- |
| Deterministic internal Agent | Same accepted input yields the same semantic result and no external effect | May recompute before durable outcome commit; Test Agent belongs here |
| Idempotent side-effecting Agent | External system accepts a stable idempotency key and can return the prior result | Requires a reviewed side-effect policy and external conformance evidence |
| Non-idempotent side-effecting Agent | Effect is irreversible or duplicate-sensitive | Requires fencing, ledger, approval, compensation, reconciliation, or another explicit protocol |
| Long-running Agent | Work exceeds ordinary consumer-processing intervals | May require progress, heartbeat, durable claim, cancellation, and revised broker interaction |
| Interactive or human-in-the-loop Agent | Work pauses for a human decision | Requires additional contracts and policy outside Vertical Slice 01 |

This classification guides review. It does not add implementation support,
manifest fields, commands, events, or scheduling behavior.

### 4. Execution Lifecycle

The first-slice lifecycle is:

1. The Event Bus adapter receives `ExecuteTask` without acknowledging it.
   The adapter associates the delivery with its current partition assignment
   ownership, which remains a transport concern.
2. Transport bytes and the exact ADR-0004 contract are validated. A record
   lacking trusted message identity follows ADR-0006 transport-rejection
   recovery, not Agent execution.
3. The Agent validates target, capability name and version, input, command
   semantics, authorization, and configured readiness. A permanent rejection
   follows the ADR-0005/ADR-0006 quarantine and durable-disposition path and
   does not continue to capability execution. Only after transport and
   semantic validation does the Agent classify a valid command whose
   `task_result_deadline` is already expired.
4. It constructs a stable, technology-neutral execution context.
5. It resolves any completed receipt and outcome by `task_attempt_id`,
   command `message_id`, and immutable command digest. A resolved duplicate
   returns the stored disposition and does not execute again.
6. It admits new work only when bounded capacity and deadline policy allow.
   If the deadline expired before admission or while waiting for capacity, it
   skips execution and constructs a stable safe deadline-expired failure.
7. It executes deterministic capability logic outside a database transaction.
8. It classifies success, failure, confirmed execution-policy cancellation, or
   lifecycle interruption. Unfinished lifecycle-interrupted work skips outcome
   creation and durability, remains unacknowledged, and proceeds only to
   resource release.
9. It constructs one immutable `TaskCompleted` or `TaskFailed` event with
   stable identity and bytes.
10. One ADR-0006 transaction commits the completed receipt, one accepted
    outcome, terminal event, and Agent event outbox.
11. The independent outbox publisher publishes or republishes the stored
    terminal event.
12. For admitted valid work, the command handler acknowledges the original
    command only after Step 10 commits. It need not wait for terminal-event
    broker acknowledgment because the durable outbox owns publication
    recovery. Rejected and duplicate paths acknowledge only after their
    respective ADR-0005/ADR-0006 durability and publication barriers. An
    adapter acknowledges only while the handler still owns the applicable
    partition assignment; stale handlers cannot advance broker progress.
13. The Agent releases admission capacity and execution resources.

Stages 1 through 6 use bounded in-process state and read-only persistence
lookups. Stage 7 is outside a transaction. Only Stage 10 is the atomic domain
transaction. Stages 11 and 12 are separate recoverable transport activities;
there is no database/Event Bus distributed transaction. A crash before Step 10
permits deterministic recomputation. A crash after Step 10 recovers the stored
outcome and event. The deadline-expired path skips Stage 7 but still performs
Stages 8 through 12, producing a truthful non-execution failure rather than
claiming that execution started and timed out.

### 5. Execution State Model

Transient states such as observed, validating, waiting for capacity, executing,
cancellation observed, timing out, committing outcome, and draining are
in-memory control states and metrics. They are not public workflow states.

Vertical Slice 01 durably stores only:

- the completed command receipt;
- the accepted outcome;
- the immutable terminal event and event outbox; and
- publication recovery metadata defined by ADR-0006.

No durable `RUNNING`, validation, queue, cancellation-requested, or execution
claim state is added. Loss of in-memory execution state causes unacknowledged
work to be redelivered. `COMPLETED` and `FAILED` remain Orchestrator-owned
workflow states, not Agent execution records.

### 6. Execution Context

The capability receives a technology-neutral context containing only validated
and bounded values needed for execution, such as:

- `workflow_id`, `task_id`, and `task_attempt_id`;
- command `message_id`, `correlation_id`, and `causation_id`;
- capability and contract identity;
- absolute `task_result_deadline` and local remaining-time budget;
- cooperative cancellation signal;
- safe logger or telemetry context;
- validated capability input;
- stable idempotency key, initially `task_attempt_id`;
- immutable execution configuration snapshot; and
- bounded resource budget.

The context never exposes Kafka consumers, partitions, offsets, database
connections or sessions, ORM models, raw secrets, global mutable state,
framework runtime objects, or provider SDK clients as platform contracts.
Dependency clients are injected behind capability-specific ports. This ADR
does not prescribe a Python class.

### 7. Capability Validation

Validation distinguishes:

| Condition | Meaning | Initial disposition |
| --- | --- | --- |
| Invalid transport or contract | Bytes or exact declared contract cannot be trusted | ADR-0005 quarantine through ADR-0006 rejection recovery |
| Unsupported capability or version | Valid command is not supported by this target | Permanent semantic rejection and quarantine; no unbounded retry |
| Invalid target | Command is not addressed to this configured Agent deployment | Permanent rejection and quarantine |
| Invalid task input | Payload violates the supported capability contract | Permanent rejection and quarantine |
| Security or policy rejection | Command is not authorized or violates execution policy | Permanent rejection, safe audit, and quarantine |
| Critical configuration/dependency unready | Agent cannot safely accept its capability | Readiness false; do not admit new work |
| Capacity occupied | Agent is healthy but currently saturated | Backpressure through the broker; do not create a domain failure |
| Execution failure after admission | Supported work fails during execution | Safe durable `TaskFailed` where the handler can classify it |

Permanent invalid work does not loop through transport retry. Temporary
capacity pressure does not create a new event. The Test Agent supports only
`text.word-count` capability version `1.0` and the exact accepted first-slice
contracts.

Dependency disposition is determined at the capability boundary. After valid
work is admitted, a safely classified dependency failure with exhausted
bounded retry becomes one stable `TaskFailed` when persistence is available.
If schema compatibility, required credential resolution, process
infrastructure, or local durability is unavailable or unknown, the Agent
cannot reliably create an outcome and leaves the command unacknowledged.
Authentication or configuration failure discovered before admission is a
non-retryable readiness failure. Repeated systemic dependency failure stops or
reduces admission before identical terminal failures can form a high-rate
stream.

### 8. Capability Declaration Boundary

The first-slice declaration remains the versioned, configuration-backed
manifest already described by Vertical Slice 01:

- stable `agent_id` and implementation version;
- capability name and version; and
- exact accepted command and produced event contract versions.

The Agent deployment owns the declaration. Code-owned capability metadata and
deployment configuration are validated together; the Orchestrator loads the
result through configuration at startup. There is no dynamic discovery,
self-registration protocol, or runtime code loading.

Input/output schema identities are determined by the declared ADR-0004
contracts. Concurrency, timeout, resource, and side-effect properties remain
local validated configuration or review metadata in this slice. Adding them to
the portable manifest requires normal contract versioning; this ADR does not
silently add fields. Dynamic availability and registry behavior remain a later
decision.

### 9. Agent Selection Boundary

The Orchestrator selects a configured compatible Agent target before creating
`ExecuteTask`. The first-slice command identifies:

- the stable logical Agent deployment through `agent_id`; and
- the selected capability name and version.

The Agent verifies those values but does not reroute the command or select
another Agent. Consumer-group names, topic names, hosts, containers, process
instances, and partitions are transport or deployment details and are not the
domain target. Broker routing implements delivery after selection; it is not
the selection model. Dynamic scheduling is out of scope.

### 10. Concurrency Model

Evaluated execution strategies are:

| Strategy | Benefits | Costs and decision |
| --- | --- | --- |
| One command per process | Simple isolation and ordering | Underuses I/O concurrency and scales only by processes; not the general initial model |
| Fixed bounded in-process workers | Predictable capacity and memory, simple backpressure | Tasks share a process; selected for trusted Test Agent |
| Unbounded asyncio task per command | Simple code and high apparent concurrency | Unbounded memory, dependencies, and shutdown; rejected |
| Thread pool | Integrates blocking I/O | Threads do not make ordinary Python CPU work parallel and cancellation cannot stop a running call; adapter-only option |
| Process pool or subprocess | CPU parallelism and stronger failure isolation | Serialization, lifecycle, memory, and shutdown cost; future capability adapter |
| External executor | Independent scale and isolation | Adds another distributed execution system; not justified |

The initial Agent uses one asyncio event loop per process, a small
configuration-bounded execution supervisor, and at most one in-flight command
per assigned partition. Global concurrency cannot exceed the configured limit
and useful concurrency cannot exceed assigned partitions under the
per-partition ordering rule.

Each assigned partition has a technology-neutral processing lane. Records are
admitted and durably disposed in order within that lane, while different lanes
may progress independently and finish out of order. Prefetched records remain
in a bounded adapter handoff and do not become concurrently executing work in
the same lane. Completion in one lane cannot advance transport progress for
another lane.

The consumer/polling path remains responsive and separate from task execution.
Task handlers catch and classify capability failures so one task does not
cancel unrelated siblings. Owned structured tasks are observed and drained;
there are no arbitrary fire-and-forget tasks.

I/O-bound async dependencies may share the event loop. A known blocking
I/O call may use a bounded thread adapter. CPU-heavy Python work requires a
bounded process/subprocess adapter or more Agent instances; the GIL means a
thread pool is not assumed to provide CPU parallelism. Exact limits require
measurement.

### 11. Admission Control and Backpressure

The broker is the durable waiting area. The Agent does not create an unbounded
in-memory queue.

When global capacity or a partition lane is full, the adapter pauses the
affected partition where supported or stops fetching additional work while
continuing the client activity required to retain healthy consumer-group
membership. Other assigned partitions may continue when they have capacity.
The adapter resumes a partition only after its lane and global capacity allow
admission. At most a small configured number of delivered-but-not-executing
records may exist in the adapter handoff; they remain unacknowledged and are
not durable Agent queue state.

One in-flight command per partition preserves ADR-0005 ordering. Offset
progress for a partition cannot pass a record until its required durable
disposition completes; completion in another partition cannot satisfy or skip
that barrier. Capacity across partitions is fair enough to prevent one hot
partition from consuming every slot; exact scheduling is an implementation
policy. Consumer polling, poll intervals, handoff bounds, and processing limits
must be configured together and tested through rebalance.

A contract-valid, correctly targeted command whose deadline expired before
admission is removed from the capacity path without running capability work.
The Agent constructs a stable safe deadline-expired `TaskFailed`, atomically
persists its completed receipt, outcome, event, and event outbox, and
acknowledges only after that boundary. This finite disposition prevents
redelivery from becoming an implicit wait for capacity. Transport-invalid
commands still use quarantine recovery.

Partition revocation closes admission for that lane and triggers lifecycle
cancellation of unfinished transient work. The Event Bus adapter fences offset
commit using its current assignment generation, ownership token, or equivalent
mechanism. A handler from a revoked or earlier assignment may finish and
attempt the outcome transaction, but it cannot acknowledge broker progress for
the new owner. The new owner resolves any committed outcome through the
completed receipt; otherwise deterministic work may be recomputed.

Shutdown stops admission before draining. Capacity exhaustion creates no
`TaskFailed`, retry publication, or new domain event.

### 12. Duplicate Delivery and Conflict Handling

ADR-0004 and ADR-0006 remain authoritative:

| Condition | Behavior |
| --- | --- |
| Same attempt, message ID, and immutable bytes after commit | Return the stored outcome and make the same terminal event eligible for republication |
| Same attempt and message ID while executing in one process | Best-effort coalesce with the owned execution; correctness does not depend on it |
| Same attempt and message ID executing in different instances | Deterministic duplicate computation is allowed; one durable outcome wins |
| Same attempt with different message ID | Permanent command conflict; do not overwrite the accepted mapping or outcome |
| Same message ID with different bytes | Integrity violation and quarantine |
| Different attempt ID | Independent application attempt selected by the Orchestrator |
| Duplicate after event publication | Return stored outcome; lost publication confirmation may republish the same event ID |
| Duplicate after command acknowledgment loss | Resolve completed receipt and acknowledge without recomputation |
| Redelivery after partition revocation | Resolve a committed outcome or safely recompute deterministic uncommitted work |

Before the completed-receipt transaction, in-memory coalescing is only an
optimization. Database uniqueness arbitrates competing commits. The loser
loads the winner and either returns the identical accepted outcome or reports a
conflict. No case proves exactly-once computation.

Assignment fencing protects broker progress, not computation or outcome
commit. A stale execution may race the new owner, and database uniqueness still
selects one accepted outcome. This duplicate computation remains acceptable
only for the deterministic, side-effect-free Test Agent.

### 13. Cancellation Model

Cancellation causes and their durable meanings remain distinct:

- **Execution-policy cancellation:** an Agent execution timeout, exhausted
  local execution budget, capability policy cancellation, or
  `task_result_deadline` reached after admission. When the Agent has confirmed
  that capability work stopped at a safe boundary and can classify the
  failure, it may persist a truthful terminal `TaskFailed`.
- **Lifecycle cancellation:** graceful shutdown, process drain, partition
  revocation, infrastructure restart, or forced termination. It controls
  process ownership and must not by itself create a business `TaskFailed`.
- **Orchestrator deadline expiry:** may make the workflow terminal while Agent
  work continues; it is not an explicit cancellation command.
- **Future explicit cancellation:** requires a new accepted command/event
  contract and is absent.

For unfinished deterministic first-slice work interrupted by lifecycle
cancellation, the Agent does not persist a completed receipt or outcome, does
not acknowledge the command, and releases or abandons transient execution for
Event Bus redelivery. If the outcome transaction committed first, normal
completed-receipt, duplicate, and event-outbox recovery applies. Work that
truthfully completes after partition revocation may still race to commit its
outcome, but assignment fencing prevents the stale handler from committing an
offset.

A contract-valid command already expired before admission follows the stable
non-execution failure path in Sections 4 and 11. It is not lifecycle
cancellation and does not claim that capability execution began. Deadline
expiry during execution requests execution-policy cancellation. If confirmed
cooperative cancellation stops the work safely, the Agent records a stable
failure; if cancellation-insensitive work completes, the Agent records and
publishes the actual outcome and the Orchestrator may classify it as late.

An asyncio cancellation exception alone is insufficient evidence that a
thread, subprocess, provider request, dependency operation, or external effect
stopped. The adapter or capability boundary must positively establish safe
termination before cancellation becomes a terminal business failure.
Vertical Slice 01 has no explicit cancellation command.

### 14. Timeout Model

Timeouts have separate owners:

| Timeout | Owner and semantics |
| --- | --- |
| Command-processing/retry bound | Event Bus adapter under ADR-0005; bounds handler transport attempts |
| Admission wait | Agent; bounded by remaining deadline and local capacity policy; expiry produces the durable non-execution failure |
| Task execution | Agent capability policy; bounds one admitted execution |
| Provider/tool call | Dependency adapter; no longer than remaining execution budget |
| Persistence operation | Persistence adapter under ADR-0006; separate transaction timeout and retry |
| Event publication attempt | Agent outbox publisher; changes publication state, not outcome |
| Graceful shutdown | Agent process supervisor; bounds draining |
| `task_result_deadline` | Orchestrator; maximum time for durable terminal result acceptance |

The Agent execution budget is the bounded minimum of capability configuration,
the command's remaining `task_result_deadline`, and any stricter deployment
resource policy, with a configurable best-effort reserve for outcome commit and
publication. It is not one global timeout reused for persistence, publication,
and dependencies.

Absolute contract deadlines use ADR-0004 UTC timestamps. Local elapsed
durations use a monotonic clock. Clock skew and reserve margins are observable
and tested. A local timeout means the Agent stopped awaiting or accepting the
operation result; it is not evidence that an external action stopped.

Deadline disposition depends on the stage:

- if already expired when received, transport and semantic validation still
  run so invalid commands use quarantine rather than an Agent outcome;
- after successful validation but before admission, or while waiting for
  admission, expiry produces the stable durable non-execution `TaskFailed`;
- during execution, expiry requests execution-policy cancellation and creates
  `TaskFailed` only after safe stop and classification; and
- while outcome persistence is retrying, the already constructed stable
  outcome remains unchanged, retry stays bounded, and the command remains
  unacknowledged until durability succeeds.

### 15. Deadline Races

The Agent cannot determine the Orchestrator's durable workflow state. It
therefore records the truthful terminal result of admitted work and makes the
event publishable even when its local clock indicates the result may be late.

| Race | Result |
| --- | --- |
| Valid command is already expired before admission | Agent skips execution and durably records the stable non-execution failure; Orchestrator may accept or classify it as late |
| Deadline expires while waiting for admission | Same finite non-execution failure path; capacity pressure cannot cause infinite redelivery |
| Work finishes before deadline, commit finishes after | Agent commits truthful outcome; Orchestrator decides whether it arrived durably in time |
| Outcome commits just before Orchestrator deadline transition | Event publication may still be late; Orchestrator row lock and state transition arbitrate |
| Publication occurs after workflow failure | Event is delivered and recorded as late; workflow cannot reopen |
| Deadline expires while executing | Agent requests execution-policy cancellation; confirmed safe stop produces failure, otherwise the actual completion remains authoritative |
| Deadline expires during persistence retry | Stable outcome intent is not reclassified; retry remains bounded and a committed outcome is still published and may be late |
| Deadline expires after event publication before processing | Orchestrator's first accepted terminal transition wins |

The Agent does not suppress a committed terminal event merely because the
deadline passed. ADR-0006 ensures late events cannot reopen a terminal
workflow.

### 16. Error Classification

Internal classifications and initial dispositions are:

| Classification | Disposition |
| --- | --- |
| Invalid transport, contract, identity, or immutable bytes | Quarantine; no domain execution |
| Unsupported capability/version or invalid target | Permanent quarantine; no retry loop |
| Policy or authorization rejection | Permanent quarantine and safe audit |
| Capacity pressure | Backpressure; no acknowledgment and no domain failure |
| Valid command expired before admission | Durable safe non-execution `TaskFailed`; acknowledge only after completed-receipt/outcome/event/outbox commit |
| Execution timeout or confirmed cooperative execution-policy cancellation | Durable safe `TaskFailed` only after safe stop and classification |
| Lifecycle cancellation before outcome commit | No completed receipt, outcome, or acknowledgment; abandon transient work for redelivery |
| Deterministic task failure | Durable `TaskFailed` |
| Classified capability-operation dependency failure after admission | After bounded safe retry, durable stable `TaskFailed`; acknowledge only after the ADR-0006 transaction |
| Agent infrastructure failure or unknown local durability | No reliable outcome and no command acknowledgment; recover or redeliver |
| Systemic dependency failure | Stop or reduce admission and mark readiness unavailable; current command follows the classified outcome or infrastructure-failure rule |
| Authentication or configuration failure before admission | Non-retryable configuration/readiness failure and operator action; do not create an ordinary task retry loop |
| Persistence unavailable | No command acknowledgment; retain or recompute after recovery |
| Internal Agent defect | Isolate task where possible; bounded transport retry or process restart, then quarantine/deadline resolution |
| Integrity conflict | Fail closed, record safe evidence, and quarantine |
| Process termination | No new outcome; committed state recovers, uncommitted command redelivers |

Raw exception names, stack traces, secrets, provider payloads, and unrestricted
text are not event fields. `TaskFailed` uses ADR-0004 safe stable error
contracts. A valid admitted capability operation whose dependency failure can
be safely classified becomes terminal after its bounded retry budget is
exhausted when persistence remains available. Persistence, schema, required
credential-resolution, process-wide infrastructure, or unknown-durability
failures leave the command unacknowledged. Event Bus redelivery is never an
implicit unbounded dependency retry loop.

### 17. `TaskCompleted` and `TaskFailed` Creation

For one `task_attempt_id`, the Agent:

- accepts at most one durable outcome;
- creates one immutable logical terminal event and stable `message_id`;
- preserves the command's `correlation_id`;
- sets causation to the command `message_id`;
- validates exact contract and capability payloads;
- stores safe failure classification only;
- fixes the semantic completion/failure timestamp and immutable event bytes
  before the retryable outcome transaction; and
- commits completed receipt, outcome, event, and event outbox atomically.

Competing executions never overwrite:

- identical outcomes resolve to the existing accepted outcome and event;
- different success values are an integrity conflict;
- success versus failure is an integrity conflict; and
- different failures are an integrity conflict.

Database uniqueness and conditional persistence select the first valid durable
winner. The losing execution reads the winner for duplicate handling or fails
closed on mismatch.

### 18. Retry Boundaries

| Retry kind | Identity and owner |
| --- | --- |
| Event Bus redelivery | Adapter delivers the same command, `message_id`, and `task_attempt_id` |
| Agent-internal operation retry | Capability/dependency adapter retries one operation inside the same execution context and attempt |
| Persistence transaction retry | ADR-0006 reconstructs the transaction from stable intent and IDs |
| Event-outbox publication retry | Publisher sends the same immutable event bytes and `message_id` |
| Orchestrator application retry | Orchestrator creates a new `task_attempt_id`; Agent never does |

Agent-internal retry is permitted only when:

- the operation is read-only, deterministic, or externally idempotent;
- a small configured attempt and elapsed-time budget remains;
- the failure is explicitly retryable;
- backoff is bounded, jittered, deadline-aware, and cancellation-aware;
- execution context and external idempotency key remain stable; and
- attempts and exhaustion are observable.

Authentication, policy, validation, and integrity failures are not retried.
Retry concurrency and dependency-wide budgets prevent storms. A future
side-effect protocol governs retry of external writes.

Rate limits, dependency unavailability, provider timeouts, and deterministic
dependency rejections are capability-operation failures after admission when
their outcome is safely known. They retry only within the internal attempt and
elapsed-time budget, global concurrency bound, cancellation policy, and
remaining task deadline. Exhaustion produces one stable `TaskFailed` for the
admitted attempt when persistence is available. If the Agent cannot resolve
required credentials, validate schema/configuration, or determine local
durability, it cannot reliably create an outcome and leaves the command
unacknowledged. Repeated systemic dependency failure closes or reduces
admission before it can generate a high-rate stream of identical failures.

### 19. External Dependency Boundary

Agents use technology-neutral capability ports for AI providers, databases,
HTTP services, filesystems, shell/process execution, code execution, tools, and
future human approval.

Dependency implementations are injected; SDK clients and provider types stay
inside adapters. Credentials are references resolved at runtime and never task
payloads. Every call has validated input/output, explicit timeout and retry
policy, safe logging, side-effect classification, and an external idempotency
key where supported.

Access is deny by default. Capabilities receive only approved dependencies,
filesystem paths, network destinations, subprocess operations, and data. The
platform does not grant unrestricted tools merely because a capability or
model requests them.

### 20. Side-Effect Policy

Vertical Slice 01 performs no external side effect.

Before any side-effecting Agent is introduced, a separate ADR or explicitly
reviewed extension must define:

- external idempotency-key support and result lookup;
- operation ledger and unknown-outcome reconciliation;
- durable execution claim and fencing where required;
- partial-success and compensation behavior;
- confirmation, human approval, or policy gates;
- replay and retry safety; and
- recovery after process, database, broker, and external-system failure.

Durable outcome uniqueness does not prevent duplicate external effects.
Consumer-group ownership does not fence a former process. Cancellation does
not roll back an external action, and timeout does not prove whether it
occurred. Because these are architecture-level guarantees, the first
side-effecting Agent requires a future ADR rather than an undocumented local
extension.

### 21. Process and Task Isolation

The trusted deterministic Test Agent runs its built-in capability in the Agent
Python process. Bounded tasks share that process and its event loop. Task
handlers isolate ordinary exceptions and bounded resources so one task failure
does not automatically fail siblings.

This model is selected for its low startup, memory, Docker, Windows, Linux, and
Unraid cost. It does not isolate memory leaks, native crashes, CPU exhaustion,
malicious inputs, arbitrary filesystem/network access, or unsafe code.

One process per task, subprocesses, per-task containers, and external sandboxes
add progressively stronger isolation with startup, cleanup, portability, and
observability cost. A stronger model is required before running untrusted code,
arbitrary tools, unstable native libraries, hard CPU/memory workloads, or
capabilities requiring distinct network/filesystem policy. This ADR selects no
sandbox product.

### 22. Resource Limits

Every Agent deployment validates bounded policies for:

- concurrent and in-flight tasks;
- admission and execution duration;
- input, output, and event size;
- memory, CPU, log volume, and temporary disk;
- outbound network and approved destination scope;
- provider token/cost budget;
- thread, subprocess, or process-pool capacity; and
- dependency retry concurrency.

Capability configuration defines execution-specific bounds. Deployment
configuration enforces process/container resources and network/filesystem
policy. Commands may request only values within both sets and cannot expand
them. Capability declarations may later advertise reviewable bounds through a
versioned contract.

Exact numbers require measurement. A limit that cannot be safely enforced must
fail closed or make the capability unavailable; it cannot become silent
unbounded consumption.

### 23. Graceful Shutdown

Shutdown proceeds as follows:

1. enter draining and make readiness unavailable;
2. close admission for every assigned partition lane;
3. pause or stop new broker intake per partition while maintaining safe group
   behavior;
4. allow a bounded grace period for in-flight deterministic work;
5. commit outcomes that finish within the durability window;
6. never acknowledge a command without committed completed receipt, outcome,
   event, and event outbox;
7. stop claiming new event-outbox records;
8. finish or relinquish publication claims without converting unknown
   publication to nonacceptance;
9. close persistence and broker resources; and
10. abandon unfinished transient work for redelivery.

If a task completes during shutdown, it may commit and be acknowledged within
the grace period while its adapter still owns the partition assignment. At
timeout, lifecycle cancellation is requested, but that signal does not create
a business `TaskFailed`. Unfinished work has no completed receipt or outcome,
is not acknowledged, and is abandoned for redelivery. The process may
terminate without every task finishing. Forced termination loses only
transient state.

Partition revocation uses the same lifecycle-cancellation rule for the
affected lane without stopping independent lanes. A stale handler may commit a
truthful completed outcome, but assignment fencing prevents it from committing
an offset after ownership is lost. A published event with unknown
acknowledgment remains unknown under ADR-0006. Persistence failure prevents
command acknowledgment and leaves recovery to redelivery.

### 24. Startup and Recovery

Startup order is:

1. load and validate nonsecret configuration and secret references;
2. initialize persistence and verify migration compatibility;
3. load and validate the capability declaration;
4. initialize required dependency adapters and credentials;
5. start the Agent event-outbox publisher and recover eligible records and
   expired claims;
6. initialize the Event Bus consumer and assignment handling;
7. establish a fenced processing lane for each assigned partition and start
   the bounded execution supervisor; and
8. expose readiness only when required dependencies and recovery workers are
   usable.

Outbox recovery begins before or alongside command intake and receives bounded
priority so completed work is not starved by new execution. It need not drain
the entire backlog before readiness if publication and intake remain bounded
and healthy.

On restart, no in-memory state is trusted. The Agent recovers event outboxes,
resolves completed receipts and outcomes on redelivery, and recomputes
deterministic work only when no durable outcome exists. Unknown publication
outcomes preserve their identity and may republish under ADR-0006.

Assignment and revocation callbacks create and close adapter-owned partition
lanes. Generations, ownership tokens, offsets, and consumer objects never enter
the capability context. After rebalance, the new owner resolves a committed
outcome before executing; an uncommitted command may be recomputed.

### 25. Health, Readiness, and Draining

- **Liveness** means the process, event loop, and supervisor respond and can
  make progress. A temporary dependency failure does not necessarily make the
  process dead.
- **Readiness** means configuration and schema are compatible, persistence is
  usable, Event Bus consumption and event publication recovery can operate,
  required capability dependencies and credentials are valid, and the process
  is not draining.
- **Dependency health** reports bounded safe status for persistence, Event Bus,
  and capability-specific dependencies without exposing addresses or secrets.
- **Draining** rejects new admission while bounded execution and publication
  recovery wind down.

Capacity usage is an availability signal distinct from liveness. Ordinary
short saturation uses broker backpressure and need not flap readiness.
Sustained saturation that makes accepted deadline service impossible may make
the capability unavailable according to configured policy. With one
first-slice capability, a required dependency failure makes the Agent unready;
a future multi-capability Agent may expose capability-level availability
without making unrelated capabilities unavailable.

Repeated dependency failures that show the capability cannot safely serve new
work stop or reduce admission and make the capability or Agent unready.
Recovery is bounded and may require operator intervention. A command already
admitted still follows its own deterministic disposition: safely classified
dependency failure commits one stable outcome when persistence is available;
an infrastructure or unknown-durability failure remains unacknowledged. This
prevents readiness failure from becoming a stream of identical task failures.

No HTTP framework or monitoring backend is selected.

### 26. Agent Configuration

Validated configuration categories include:

- stable Agent and deployment identity;
- supported capability and contracts;
- execution and per-partition concurrency;
- admission, execution, dependency, publication, and shutdown timeout bounds;
- dependency endpoint references and retry policies;
- resource limits and approved external access;
- Event Bus logical subscription mapping;
- persistence connection reference;
- security credentials by reference; and
- safe observability settings.

Configuration is validated before readiness, separates secrets from ordinary
values, and cannot redefine domain contracts. One execution receives an
immutable snapshot. Invalid critical configuration fails closed.

Vertical Slice 01 uses restart-based configuration changes. Runtime reload
would require atomic configuration snapshots, compatibility, in-flight policy,
and audit behavior that the slice does not need.

### 27. Framework Evaluation

| Option | Fit and strengths | Costs and decision |
| --- | --- | --- |
| Plain Python application services | Directly implements accepted Event Bus, persistence, lifecycle, and test ports with minimal hidden behavior | Selected; project owns explicit semantics |
| Asyncio worker infrastructure | Python 3.14 structured tasks, timeouts, and async adapters fit I/O lifecycle | Selected as infrastructure, not a domain framework |
| LangGraph | Stateful graph execution, persistence, durable execution, streaming, and human-in-the-loop support | Overlaps Orchestrator workflow and ADR-0006 persistence for this slice; not selected |
| AutoGen | Agent runtimes, messages, teams, cancellation, and multi-agent collaboration | Introduces another Agent identity/routing/lifecycle model and provider-oriented abstractions; not selected |
| CrewAI | Agents, Crews, and Flows provide role and workflow abstractions | Crews/Flows overlap global orchestration and add no deterministic word-count benefit; not selected |
| Celery | Mature worker pools, acknowledgment, routing, retry, and time limits | Duplicates the accepted Kafka adapter, consumer groups, retry, and worker transport; not selected |
| Temporal worker | Strong durable workflow/activity execution and recovery | Adds another workflow engine and persistence/retry authority under the Orchestrator; not selected |
| Custom plugin framework | Could standardize dynamic capability discovery and loading | Unnecessary trust, packaging, compatibility, and isolation surface; rejected for the slice |

Vertical Slice 01 uses plain Python application services behind platform-owned
ports. A future framework may implement one capability internally only if it
does not own platform workflow state, replace message/persistence contracts, or
leak its runtime objects. Adoption requires Python 3.14, local-operation,
failure, durability, cancellation, and lock-in review. The decision is not
based on whether a framework calls its objects “agents.”

### 28. Async Execution Model

Each Agent process uses one asyncio event loop for:

- broker adapter coordination;
- partition-lane assignment, pause/resume, and revocation coordination;
- async persistence and outbox operations;
- async dependency calls;
- bounded execution supervision;
- timeout and cancellation signaling; and
- startup, draining, and shutdown.

Owned structured-concurrency scopes or an equivalent supervised task registry
track every spawned task. Each task has an owner, capacity slot, cancellation
policy, observed exception, and shutdown path. Capability exceptions are caught
at the task boundary so they do not unintentionally cancel sibling work.
Infrastructure exceptions may deliberately drain and restart the process.

Known blocking I/O may use bounded `asyncio.to_thread` only when thread safety
and non-cancellation are understood. CPU-heavy work uses a bounded process pool
or subprocess capability adapter. No arbitrary fire-and-forget task is
allowed.

Execution-policy and lifecycle cancellation use distinct supervisor causes.
Lifecycle cancellation abandons unfinished transient work without constructing
a business failure. An asyncio cancellation exception is merely a control
signal until the relevant capability or dependency boundary confirms safe
termination.

The Event Bus adapter owns partition lanes and assignment fencing. Rebalance
callbacks close admission for revoked lanes and invalidate their offset-commit
authority. Capability tasks receive no consumer object, offset, assignment
generation, or ownership token. Polling remains responsive while owned
execution tasks run, and independent partitions may advance concurrently
within the global bound.

### 29. Capability Plugin Model

Evaluated capability packaging models are:

- built-in modules;
- dependency-injected implementations;
- Python entry points;
- filesystem plugins;
- remote capability services; and
- dynamically downloaded code.

The Test Agent uses one built-in capability implementation selected by
validated configuration and exposed behind a platform-owned capability port.
Dependency injection supports isolated tests and later replacement without
dynamic loading.

Entry-point, filesystem, remote, or downloaded plugins are not selected.
Dynamic plugins would require signing, trust policy, compatibility,
dependency/process isolation, sandboxing, upgrade, rollback, and provenance
decisions.

### 30. Agent Identity

The identities are distinct:

| Identity | Stability and use |
| --- | --- |
| Capability name/version | Stable semantic work contract |
| Agent implementation/version | Stable software release identity |
| Agent deployment (`agent_id`) | Configured logical command target, stable across process restarts |
| Process instance | Ephemeral execution/logging identity; changes on restart |
| Consumer group | Deployment transport identity; not a domain Agent |
| Execution owner | Current process/task owner in transient state; no durable first-slice lease |
| Public task target | Deployment `agent_id` plus capability name/version |

Hostnames, container IDs, broker member IDs, and process IDs remain operational
metadata and never portable message identities. The exact process-instance
identifier format is bounded implementation policy.

### 31. Security

Agent security requires:

- least-privilege Event Bus consume/publish and component-schema identities;
- runtime secret injection and rotation outside task payloads;
- TLS and certificate verification outside isolated local development;
- authenticated dependency adapters;
- exact contract, target, capability, input, and policy validation;
- safe deserialization before execution;
- no arbitrary code, shell, filesystem, subprocess, or network access by
  default;
- allowlisted dependencies and destinations where feasible;
- validated prompt, model, and tool input/output for future AI capabilities;
- sanitized logs and protected outcomes;
- reviewed dependency and container provenance; and
- no secrets in commands, outcomes, events, errors, metrics, or images.

Trust boundaries exist between Orchestrator, broker, Agent adapter, Agent
capability, persistence, and every external provider/tool. Internal network
location, command receipt, or capability registration does not grant
authorization. This ADR selects no identity provider or sandbox.

### 32. Observability

Without selecting a backend, Agent signals cover:

- commands received, validated, admitted, backpressured, rejected, and
  acknowledged;
- partition lanes assigned, paused, resumed, revoked, fenced, and drained;
- duplicates, command-identity conflicts, and deterministic recomputation;
- active execution, capacity, partition occupancy, and admission wait;
- execution, timeout, cancellation, and drain duration;
- success and safe failure classification;
- dependency latency, retry, rate limit, and failure;
- systemic dependency admission suppression and readiness transitions;
- persistence transaction and outcome-commit latency/failure;
- event-outbox count, oldest age, publication certainty, and failure;
- recovered outcomes and event publications; and
- liveness, readiness, dependency health, and shutdown progress.

Safe context includes `workflow_id`, `task_id`, `task_attempt_id`, command and
outcome-event `message_id`, `correlation_id`, capability name/version, Agent
deployment, process instance, and execution classification.

Complete command input, prompts, provider responses, secrets, unrestricted
outcomes, and stack traces are not logged by default.

### 33. Local Development

The local model supports:

- one Test Agent process or container;
- the ADR-0005 Redpanda container and ADR-0006 PostgreSQL container;
- Windows and Linux development and Unraid deployment;
- deterministic capability execution and controlled failure injection; and
- multiple Agent instances sharing one deployment identity and consumer group
  for rebalance and duplicate tests.

Test levels use:

- direct capability calls for deterministic unit tests;
- in-memory Event Bus and persistence fakes for lifecycle/component tests;
- the real Agent application with fake capability dependencies for component
  and shutdown tests;
- real isolated PostgreSQL and Redpanda for integration, concurrency,
  acknowledgment, rebalance, and recovery tests; and
- external providers only in explicit opt-in external-service tests.

No AI provider is required for Vertical Slice 01.

### 34. Testing Strategy

Tests follow `docs/testing/README.md` and use controlled clocks, concurrency,
process failure, and dependency injection.

Required coverage includes:

- contract/capability validation: valid command, unsupported capability or
  version, malformed input, invalid target, policy rejection, and unavailable
  dependency;
- duplicate/conflict: duplicates during execution and after outcome,
  publication, or lost acknowledgment; mismatched attempt/message/bytes; and
  competing identical and conflicting outcomes;
- concurrency/backpressure: hard capacity bound, no unbounded task creation,
  partition pause/resume, one in-flight per partition, multiple instances,
  rebalance, fairness, and shutdown at capacity;
- timeout/cancellation: already-expired deadline, expiry during admission or
  execution, local execution timeout, confirmed execution-policy cancellation,
  lifecycle cancellation without business failure, cancellation-aware and
  insensitive work, late publication, and terminal workflow;
- crash recovery: interruption before/during execution, after work before
  commit, after commit before publication, after broker acceptance before
  acknowledgment, before command offset commit, and with outbox backlog;
- failure classification: admitted capability dependency failure,
  authentication/configuration failure, systemic dependency failure,
  rate-limit exhaustion, persistence/unknown-durability infrastructure
  failure, deterministic failure, internal defect, policy, and integrity
  failure;
- startup/shutdown: dependency and schema ordering, invalid configuration,
  outbox recovery priority, draining, bounded grace, forced termination, and
  persistence failure during shutdown; and
- isolation/security: denied dependency/tool access, sanitized telemetry,
  bounded outputs, and resource-policy enforcement.

Real Event Bus integration tests additionally cover:

- two partitions completing out of order without cross-partition offset
  advancement;
- one blocked partition while another advances;
- rebalance during execution and stale completion after revocation;
- outcome commit before revocation with the offset still uncommitted;
- revocation before outcome commit;
- shutdown with work on multiple partitions;
- duplicate redelivery to the new owner; and
- no offset skipping under pause, resume, retry, revocation, or failure.

In-memory tests do not prove PostgreSQL uniqueness, broker ordering,
acknowledgment, process termination, thread cancellation, rebalance, or
container resource behavior.

### 35. Initial Test Agent Decision

Vertical Slice 01 uses:

- a plain Python Agent application service on CPython 3.14;
- one asyncio event loop per process;
- ADR-0005 `confluent-kafka` and ADR-0006 Psycopg 3 adapters behind ports;
- one built-in deterministic `text.word-count` capability;
- small configurable in-process concurrency, bounded globally and to one
  in-flight command per assigned partition;
- independent adapter-owned per-partition lanes with assignment-fenced offset
  commits;
- broker-aware per-partition backpressure and no durable or unbounded Agent
  queue;
- no durable execution lease or public `RUNNING` state;
- no external effect, provider, LLM, or AI Router;
- no dynamic plugin loading or explicit cancellation command;
- capability execution bounded by local policy and remaining result deadline;
- truthful completed-receipt/outcome/event persistence even when publication
  may be late; and
- bounded graceful shutdown with safe command redelivery.

### 36. Coherent Agent Execution Architecture

The decision is:

- an Agent is a deployable capability executor and durable outcome owner, not
  a workflow engine;
- the Orchestrator owns selection, workflow state, result deadline, and
  application retry;
- commands follow the thirteen-stage lifecycle in Section 4;
- first-slice capabilities are built in, dependency injected, and declared
  through the existing configuration-backed manifest;
- Agent targets are logical deployment plus capability identities;
- one asyncio loop and a bounded supervised worker set execute at most one
  command per partition;
- adapter-owned partition lanes progress independently within the global bound,
  and assignment fencing prevents stale offset commits;
- the broker supplies durable per-partition backpressure; no unbounded memory
  queue exists;
- completed receipts and database uniqueness arbitrate duplicates and
  conflicts without exactly-once computation claims;
- execution-policy cancellation may create `TaskFailed` only after confirmed
  safe stop and classification; lifecycle cancellation creates no business
  failure for unfinished work;
- no explicit cancellation command exists;
- timeout categories remain separate and execution uses a bounded combination
  of capability policy and remaining `task_result_deadline`;
- a valid command expired before admission receives a finite durable
  non-execution failure;
- the Agent persists and publishes truthful terminal outcomes; only the
  Orchestrator accepts or rejects late events;
- retry identity and ownership follow Section 18;
- admitted classified dependency exhaustion becomes one durable failure, while
  infrastructure or unknown-durability failure remains unacknowledged and
  systemic failure closes or reduces admission;
- external dependencies remain behind restricted ports;
- every side-effecting Agent requires a future ADR;
- trusted deterministic work runs in process; stronger isolation has explicit
  review triggers;
- startup recovers completed work, shutdown drains for a bound, and
  uncommitted work redelivers;
- liveness, readiness, dependency health, and draining remain distinct;
- plain Python and asyncio are selected without an Agent framework;
- dynamic plugins are rejected for the slice;
- platform and provider/framework types do not cross the Agent boundary;
- least privilege, safe validation, and redaction are mandatory; and
- real-broker/database/process tests prove infrastructure semantics.

#### Guarantee and Failure-Window Evidence

| Guarantee | Responsible component | Durable record | Admission/concurrency mechanism | Failure window and recovery | Required proof |
| --- | --- | --- | --- | --- | --- |
| Supported work only | Agent validation boundary | Quarantine/rejection or no outcome | Validate before admission | Crash before disposition redelivers; permanent invalid input quarantines without execution | Contract, target, capability, and policy tests |
| Bounded execution | Agent supervisor and Event Bus adapter | None before outcome | Global bound plus one in-flight per partition lane | Crash loses slots and broker redelivers; no durable queue is lost | Capacity, memory, pause/resume, independent-lane, and rebalance tests |
| Finite expired-command disposition | Agent and persistence adapter | Completed receipt, deadline-expired outcome, terminal event, and outbox | Validate before deadline disposition; skip capability admission | Invalid transport quarantines; valid expired work commits non-execution failure or remains unacknowledged until persistence recovers | Expired-on-receipt, admission-wait expiry, persistence-retry, and late-event tests |
| One accepted outcome | Agent and persistence adapter | Completed receipt, outcome, terminal event | Unique attempt/outcome transaction | Precommit crash may recompute; postcommit duplicate reads winner | Competing execution and every commit-window test |
| No lost terminal event after outcome | Agent outbox publisher | Outcome and event outbox in one transaction | Publisher claims are separate from execution slots | Postcommit crash resumes immutable event; unknown broker ack may duplicate | Outbox crash and lost-ack tests |
| Partition-safe acknowledgment | Event Bus adapter and Agent handler | Completed receipt/outcome before offset | Ordered lane plus assignment-generation, ownership-token, or equivalent fencing | No lane advances past unfinished work; stale owner cannot commit; postcommit revoke redelivers and deduplicates | Out-of-order partitions, blocked lane, revoke-before/after-commit, stale completion, and no-skip tests |
| Deadline cannot be reopened | Orchestrator, with truthful Agent event | Agent outcome plus Orchestrator workflow/inbox | Orchestrator row lock/revision, not Agent clock | Late commit/publication is recorded but terminal workflow remains unchanged | All deadline-race and late-event tests |
| Cancellation claim is honest | Agent supervisor and capability/dependency adapter | Terminal outcome only for confirmed execution-policy cancellation; none for unfinished lifecycle cancellation | Typed cancellation cause plus bounded supervised execution | Async cancellation alone proves nothing; insensitive work may continue and unfinished lifecycle work redelivers | Confirmed execution stop, lifecycle cancellation, blocking, forced-stop, and external-boundary tests |
| Deterministic dependency disposition | Agent capability/dependency and persistence adapters | Stable failure outcome when safely classified; none when infrastructure cannot persist reliably | Bounded internal retry plus systemic admission suppression | Exhausted admitted operation commits once; infrastructure failure redelivers; systemic failure becomes unready without a failure storm | Exhaustion, rate-limit, auth/config, persistence, unknown-durability, and systemic-failure tests |
| Safe shutdown and revocation | Agent supervisor and Event Bus adapter | Any outcome committed before stop; outbox claims | Draining closes lanes, bounds grace, and fences revoked assignments | Uncommitted work redelivers; stale offset commit is rejected; unknown publication stays unknown | Multi-partition drain, revocation races, forced termination, and persistence-outage tests |
| Framework neutrality | Agent/capability ports | Versioned platform contracts | Dependency injection and boundary review | Framework replacement cannot change message or workflow semantics | Port, contract, and forbidden-type tests |
| No duplicate-effect guarantee | Future side-effect policy owner | None in first slice | Side effects prohibited | Any future effect blocks adoption until a separate ADR defines recovery | Architecture review and side-effect conformance gate |

### 37. Consequences

#### Positive Consequences

- Agent and Orchestrator ownership is explicit.
- Bounded execution and broker backpressure prevent uncontrolled memory growth.
- Durable outcome and outbox recovery align with accepted messaging and
  persistence semantics.
- The deterministic Test Agent remains simple and locally reproducible.
- Framework, provider, broker, and database objects stay behind ports.
- Timeout, deadline, cancellation, and shutdown claims remain testable and
  intentionally limited.

#### Negative Consequences

- The Agent must coordinate polling, partition ordering, execution slots,
  persistence, outbox publication, and draining.
- In-process tasks share a failure and resource domain.
- Deterministic work may be computed more than once.
- One in-flight command per partition can limit throughput.
- Cooperative cancellation cannot stop every blocking operation.
- Future long-running and side-effecting Agents require more architecture.

#### Migration Impact

There is no Agent implementation to migrate. Implementation must introduce the
selected boundaries only after this ADR is Accepted. A future framework,
plugin, isolation, or side-effect model must preserve command/event contracts,
completed-receipt semantics, outcome uniqueness, and Orchestrator ownership.

#### Developer Impact

Developers must separate capability logic from consumer, persistence, and
provider adapters; use bounded owned tasks; classify failures; propagate safe
context; and test crash windows. They must not infer durability from in-memory
states or cancellation from task exceptions.

#### CI Impact

Fast suites can use fakes, while partition, acknowledgment, rebalance,
persistence, process, and shutdown semantics require isolated Redpanda and
PostgreSQL plus process-level failure injection. No CI workflow is claimed to
exist.

#### Operational Impact

Operators manage concurrency, backlog, partition assignment, readiness,
dependency health, outbox recovery, resource limits, and shutdown grace.
Scaling is bounded by partitions and database/dependency capacity, not just
process count.

#### Security Impact

The Agent is a command and tool-execution trust boundary. Built-in
capabilities, deny-by-default dependencies, least privilege, safe logs, and no
dynamic loading reduce first-slice exposure. In-process execution is not a
sandbox.

#### Future Review Triggers

Review or supersede this ADR when:

- the first side-effecting, interactive, or long-running Agent is proposed;
- explicit cancellation, progress, heartbeat, or approval contracts are
  required;
- measured load needs concurrent processing within a partition;
- untrusted code or arbitrary tools require stronger isolation;
- one process cannot contain native crashes, leaks, or CPU-heavy work;
- dynamic capabilities or plugins become a documented requirement;
- a framework provides a measured benefit without taking workflow ownership;
- capability-level availability or dynamic registry behavior is needed; or
- broker consumer timing conflicts with task duration.

### 38. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Duplicate computation | Permit only for deterministic first-slice work and enforce one durable outcome |
| Duplicate external effect | Prohibit side-effecting adoption until a future ADR defines idempotency, fencing, and reconciliation |
| Unbounded concurrency or queue | Hard global capacity, one in-flight per partition, bounded handoff, and broker pause/resume |
| Long execution blocks broker polling | Separate consumer coordination from owned execution tasks and test rebalance timing |
| Event-loop blocking | Require async ports or bounded thread/process adapters and observe loop responsiveness |
| Lifecycle cancellation creates an unintended business failure | Separate cancellation causes; unfinished shutdown/revocation work records no outcome and redelivers |
| Async task cancellation is mistaken for external cancellation | Require confirmed safe stop before execution-policy failure and never claim rollback from an exception alone |
| Already-expired command loops forever | Persist a stable non-execution failure after validation and acknowledge only after its durability boundary |
| Deadline race | Persist truthful outcome and let Orchestrator durable state arbitrate |
| Outcome commits after terminal workflow | Publish it as late; Orchestrator cannot reopen terminal state |
| Work continues after drain | Bound grace, signal cancellation, terminate if necessary, and redeliver uncommitted work |
| Memory leak or native crash | Bound tasks/resources, restart process, and trigger stronger isolation review |
| Dependency retry or failure-event storm | Bound attempts, elapsed time, concurrency, and backoff; suppress admission and readiness on systemic failure |
| One capability crashes the process | Validate inputs, catch task errors, and use subprocess/container isolation when evidence requires |
| Dynamic plugin compromise | Do not load dynamic code in the slice; require signing, trust, rollback, and sandbox decisions later |
| Provider SDK leaks into contracts | Inject adapters behind platform ports and prohibit SDK types at boundaries |
| Agent framework conflicts with Orchestrator | Select plain Python and require any future framework to remain capability-internal |
| Capability metadata becomes stale | Validate code-owned metadata with configuration at startup and fail readiness on mismatch |
| Long task exceeds consumer timing | One in-flight per partition, responsive polling, bounded execution, and future long-running review |
| Stale handler commits offset after rebalance | Fence commit with adapter-owned assignment generation or ownership token and test every revoke/commit ordering |
| One partition skips unfinished work or advances another | Use ordered independent lanes and never commit progress across partitions |
| In-memory state is treated as durable | Persist only ADR-0006 completed records and test process loss at every stage |
| Late outcome reopens workflow | Orchestrator state/revision validation rejects terminal transitions |
| Secret, prompt, or provider data leaks | Minimize context, sanitize telemetry, restrict outcomes, and test redaction |
| Capacity readiness flaps | Use broker backpressure for ordinary saturation and a configured sustained-unavailability policy |

### 39. Assumptions

- ADR-0001 through ADR-0006 remain Accepted.
- Vertical Slice 01 retains one deterministic, non-side-effecting Test Agent,
  one task attempt, and one terminal event.
- The Event Bus and persistence adapters provide the already accepted
  semantics.
- Python 3.14 and asyncio are available on target container architectures.
- Test Agent word counting is bounded and trusted enough for in-process
  execution.
- Event Bus polling can remain responsive while execution runs in owned tasks.
- Local Docker and Unraid can enforce basic process/container resource limits.
- No AI provider, human approval, untrusted code, or arbitrary tool is required
  for the first slice.
- Dynamic registry, production topology, sandbox, monitoring backend, and
  side-effect protocol remain unresolved.
- Clock synchronization is operationally adequate for deadline comparison but
  does not establish distributed order.

### 40. Open Questions

The following do not leave the core execution model undecided:

1. What small default and maximum execution concurrency fit measured workloads?
2. What local execution-timeout reserve remains before
   `task_result_deadline`?
3. What shutdown grace period fits container and broker settings?
4. What exact memory, CPU, output, log, disk, network, and provider budgets
   apply?
5. What exact versioned format eventually carries richer capability metadata?
6. What process-instance identifier format is used in telemetry?
7. Which standard-library or small helper abstraction implements supervised
   structured concurrency?
8. How is health exposed by the eventual service framework?
9. What ADR governs the first side-effecting Agent?
10. What future mechanism replaces configuration-backed registration and
    availability?
11. What sustained saturation threshold changes capability availability?

### 41. Explicitly Out of Scope

This ADR does not decide:

- dynamic Agent registry implementation or global scheduling;
- workflow application retry;
- new public commands or events;
- explicit cancellation, progress, heartbeat, or approval protocols;
- AI provider, model, AI Router, prompt format, or LangGraph workflow;
- vector database or arbitrary tool execution;
- sandbox product, Kubernetes, or final deployment topology;
- secrets manager or monitoring backend; or
- side-effecting execution protocol beyond requiring a future ADR.

### 42. Acceptance Checklist

- [ ] The deployable Agent definition and non-workflow ownership are approved.
- [ ] Agent and Orchestrator responsibilities remain distinct.
- [ ] All lifecycle stages and transaction boundaries are explicit.
- [ ] Transient execution state is not a public or durable workflow state.
- [ ] Execution context excludes broker, persistence, secret, SDK, and
      framework objects.
- [ ] Contract, target, capability, input, readiness, capacity, and policy
      validation are distinct.
- [ ] The configuration-backed capability declaration remains first-slice
      registration.
- [ ] The Orchestrator selects a logical deployment and capability target.
- [ ] One asyncio loop, bounded owned tasks, and one in-flight command per
      partition are approved.
- [ ] Independent ordered partition lanes progress within the global bound.
- [ ] Broker-aware per-partition backpressure replaces unbounded in-memory
      queueing.
- [ ] Offset progress cannot cross unfinished records or partitions, and stale
      assignment owners are fenced from acknowledgment.
- [ ] Duplicate and conflict cases preserve ADR-0004 and ADR-0006 semantics.
- [ ] No exactly-once computation or side-effect claim is made.
- [ ] Timeout categories and owners remain distinct.
- [ ] A valid command expired before admission receives a finite durable
      non-execution failure after validation.
- [ ] `task_result_deadline` is not represented as an explicit cancellation
      command.
- [ ] Execution-policy, lifecycle, Orchestrator-deadline, blocking, and future
      explicit cancellation are distinguished.
- [ ] Lifecycle cancellation creates no business failure for unfinished work,
      and asyncio cancellation alone proves no external stop.
- [ ] Deadline races preserve truthful Agent outcomes and Orchestrator terminal
      authority.
- [ ] Error classifications map safely to failure, quarantine, retry,
      readiness, or no acknowledgment.
- [ ] Terminal event identity, causation, timestamp, bytes, uniqueness, and
      atomic outbox persistence are approved.
- [ ] Transport, internal operation, persistence, outbox, and application
      retries remain distinct.
- [ ] Admitted classified dependency failures terminate after bounded retry,
      infrastructure failures remain unacknowledged, and systemic failures
      suppress admission/readiness rather than producing a failure storm.
- [ ] External dependencies use restricted injected ports and stable
      idempotency keys where supported.
- [ ] A future ADR is required before side-effecting execution.
- [ ] Trusted deterministic in-process isolation and stronger-isolation review
      triggers are approved.
- [ ] Resource categories are bounded without inventing unsupported exact
      production values.
- [ ] Startup prioritizes recoverable completed work and verifies dependencies.
- [ ] Recovery never relies on lost in-memory execution state.
- [ ] Draining, shutdown, and partition revocation abandon unfinished work
      without unsafe outcomes or acknowledgment.
- [ ] Liveness, readiness, dependency health, capacity, and draining are
      distinct.
- [ ] Configuration is validated, secret-separated, and immutable per
      execution.
- [ ] Plain Python application services are selected over an Agent framework.
- [ ] One asyncio event loop and owned structured tasks are approved.
- [ ] The built-in dependency-injected capability model is approved.
- [ ] Dynamic plugin loading is absent.
- [ ] Capability, implementation, deployment, process, consumer-group,
      execution-owner, and public-target identities are distinct.
- [ ] Least privilege, safe deserialization, restricted tools, provenance, and
      telemetry redaction align with `SECURITY.md`.
- [ ] Required observability is defined without selecting a backend.
- [ ] Local fakes and real Redpanda/PostgreSQL/process tests have distinct
      proof responsibilities.
- [ ] The testing matrix covers validation, duplicates, capacity, cancellation,
      deadline races, dependency disposition, crashes, startup, shutdown,
      partition-lane independence, revocation fencing, offset skipping, and
      security.
- [ ] Reviewers confirm consistency with ADR-0001 through ADR-0006, Vertical
      Slice 01, the test strategy, `SECURITY.md`, and `AGENTS.md`.
- [ ] Every open question is bounded implementation or future-policy work.

## Related Decisions

- [ADR-0001: Core Design Principles](ADR-0001-core-design-principles.md)
- [ADR-0002: Platform Communication and State](ADR-0002-platform-communication-and-state.md)
- [ADR-0003: Runtime and Development Tooling](ADR-0003-runtime-and-development-tooling.md)
- [ADR-0004: API and Contract Standards](ADR-0004-api-and-contract-standards.md)
- [ADR-0005: Event Bus and Messaging Infrastructure](ADR-0005-event-bus-and-messaging-infrastructure.md)
- [ADR-0006: Persistence, State, and Recovery](ADR-0006-persistence-state-and-recovery.md)

## References

- [Platform Architecture](../README.md)
- [Vertical Slice 01](../../implementation/vertical-slice-01.md)
- [Platform test strategy](../../testing/README.md)
- [Repository security policy](../../../SECURITY.md)
- [Repository Agent guidance](../../../AGENTS.md)
- [Python 3.14 asyncio tasks, cancellation, task groups, timeouts, and threads](https://docs.python.org/3.14/library/asyncio-task.html)
- [LangGraph reference](https://langchain-ai.github.io/langgraph/reference/)
- [AutoGen Agent and Agent Runtime](https://microsoft.github.io/autogen/stable/user-guide/core-user-guide/framework/agent-and-agent-runtime.html)
- [AutoGen teams](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/tutorial/teams.html)
- [CrewAI Agents and Flows](https://docs.crewai.com/core-concepts/Agents)
- [Celery task documentation](https://docs.celeryq.dev/en/stable/userguide/tasks.html)
- [Temporal documentation](https://docs.temporal.io/)
- [Temporal Python SDK](https://pypi.org/project/temporalio/)
