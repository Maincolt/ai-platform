# ADR-0005: Event Bus and Messaging Infrastructure

- **Status:** Accepted
- **Date:** 2026-07-26
- **Supersedes:** None
- **Superseded by:** None

## Context

ADR-0001 requires modular, event-driven communication without placing vendor
concepts in platform contracts. ADR-0002 requires durable asynchronous
commands and events, at-least-once delivery, workflow-scoped ordering,
idempotent consumers, bounded retries, dead-letter handling, and safe replay.
ADR-0004 defines the portable JSON message envelope and makes `workflow_id` the
logical ordering key while keeping transport metadata outside that envelope.

Vertical Slice 01 is the first implementation target. It has exactly three
asynchronous domain contracts:

- `ExecuteTask`, produced by the Orchestrator and consumed by the Test Agent;
- `TaskCompleted`, produced by the Test Agent and consumed by the
  Orchestrator; and
- `TaskFailed`, produced by the Test Agent and consumed by the Orchestrator.

The slice must run locally in Docker on Windows and Linux development hosts,
operate on Unraid, and remain practical on one or two physical machines. It
also needs a credible path to multiple Agents, independent consumers, and
long-running workflows. Raw throughput is therefore secondary to durable and
understandable behavior, recovery, portability, and operational simplicity.

The Event Bus transports messages. It does not own workflow state, interpret
workflow transitions, select Agents, or convert transport acknowledgment into
business success. The Orchestrator remains the workflow-state authority.

### Existing Documentation Observations

The following points must remain visible rather than being silently resolved:

- ADR-0001 and ADR-0002 use the broad historical vocabulary of commands,
  facts, results, and failure events. ADR-0004 is the later contract authority:
  `TaskCompleted` and `TaskFailed` are events with
  `message_kind = event`.
- ADR-0002 is marked Accepted in its metadata but its Decision introduction
  still calls its decisions proposed. This is a status-wording inconsistency,
  not a messaging-semantics conflict, and this ADR does not modify it.
- ADR-0002 requires workflow-scoped ordering, while ADR-0004 defines
  `workflow_id` as the logical key. Neither document states whether ordering
  must span multiple physical channels. This ADR resolves that ambiguity by
  defining ordering within `(logical_channel, workflow_id)` without promising
  a total order across separate channels.
- Vertical Slice 01 permits the deterministic Test Agent to recompute after a
  crash that occurs before an outcome is durably recorded. That is narrower
  than an absolute claim that a `task_attempt_id` can never execute twice.
  This ADR guarantees no recomputation after a durable outcome and at most one
  durable outcome. Crash-safe prevention of repeated side effects for future
  non-idempotent Agents requires a later execution policy.
- Vertical Slice 01 still describes Python as a planned candidate in its
  Technology Evaluation table, while accepted ADR-0003 selects CPython 3.14.
  This unrelated documentation inconsistency is not changed by this ADR.

## Decision Drivers

The decision is evaluated against:

- asynchronous and long-running workflows;
- durable storage and at-least-once delivery;
- workflow-scoped ordering without global ordering;
- independent consumers, consumer recovery, and horizontal scaling;
- understandable acknowledgment, retry, quarantine, and replay behavior;
- local development on Windows and Linux;
- Docker and Unraid operation on one or two physical machines;
- Python 3.14 client maturity;
- isolated CI testability;
- operational observability and security;
- portability between self-hosted environments;
- resource usage and operational complexity;
- future multi-agent and event-streaming requirements; and
- strict separation of broker concepts from domain contracts.

## 1. Required Messaging Semantics

The Event Bus must provide:

- asynchronous command and event publication;
- durable storage of messages accepted by the broker;
- at-least-once delivery, with no end-to-end exactly-once claim;
- ordering within one physical partition of one logical channel;
- no global or cross-channel ordering guarantee;
- independent consumer groups;
- consumer recovery from committed positions after process or broker failure;
- explicit producer acknowledgment and consumer acknowledgment;
- bounded transport retries;
- quarantine handling for messages that cannot be processed;
- duplicate-safe consumers and stable deduplication identities;
- configurable retention sufficient for expected outage and recovery windows;
- horizontal scaling up to the available partition count; and
- transport metadata that remains separate from the ADR-0004 envelope.

A broker acknowledgment means that the broker accepted the publication under
the configured durability policy. It does not mean that an Agent executed the
command, an outcome event was processed, or a workflow reached a terminal
state.

Transport redelivery preserves the complete immutable envelope and payload. It
is not an application retry and does not create a new task attempt:

- `task_attempt_id` remains the business execution-idempotency key;
- `message_id` remains the identity of one immutable logical publication;
- correlation and causation identifiers remain unchanged; and
- transport delivery count, topic, partition, and offset remain outside the
  domain message.

The Event Bus is a replay-capable operational transport with bounded retention.
It is not the permanent workflow system of record. The Orchestrator and its
durable state capability remain authoritative for workflow state.

## 2. Technology Evaluation

### Functional Evaluation

| Option | Durability and acknowledgment | Ordering and scaling | Consumer groups and replay | Retry and quarantine | Future suitability |
| --- | --- | --- | --- | --- | --- |
| Apache Kafka | Replicated append-only logs, producer acknowledgments, committed consumer offsets, and mature idempotent-producer support | Native key-to-partition ordering; consumer parallelism is bounded by partitions | Mature independent consumer groups, offset reset, retention, and replay | No native delayed-message queue; retry and quarantine use application patterns and additional topics | Excellent event-streaming ecosystem and multi-agent growth path |
| Redpanda | Replicated append-only logs and Kafka-compatible producer, consumer, offset, and transaction APIs, subject to documented differences | Kafka-compatible keyed partitions and consumer groups | Kafka-compatible retention, offsets, groups, and replay for the selected feature subset | Same application-level retry and quarantine patterns as the selected Kafka subset | Strong fit when Kafka semantics are wanted with fewer broker-side runtime components |
| RabbitMQ | Publisher confirms, manual consumer acknowledgments, durable quorum queues, and replicated streams | Queue order is affected by multiple consumers and redelivery; streams or superstreams add partitioned ordering | Independent queues are natural; streams add replay but use a different operating model | Mature requeue, dead-letter exchange, poison-message, and delayed-retry patterns | Strong work-queue broker, but combining queue and stream features increases complexity for this replay-oriented platform |
| NATS JetStream | Durable streams, publish acknowledgments, explicit consumer acknowledgments, and at-least-once delivery | Ordered streams and shared pull consumers are simple, but stable per-workflow parallel ordering needs subject or stream design beyond a direct partition key | Durable consumers support replay and horizontal pull consumption | Backoff and maximum delivery are built in; dead-letter behavior is advisory- and application-driven | Lightweight and capable, but its partitioning and dead-letter model are less direct for the accepted workflow-key requirements |
| PostgreSQL-backed queue or outbox polling | Can be transactional with domain state when the same store is used | Competing consumers and ordering can be built with locking and sequence rules | Replay, independent subscriptions, lag, and retention require custom tables and policies | Retry and quarantine are application-owned | Useful as an outbox mechanism, but selecting it as the Event Bus would couple transport to unresolved persistence and recreate broker features |
| In-memory Event Bus | Process-local only; no restart durability | Deterministic ordering and controlled test concurrency | No meaningful process recovery or durable replay | Faults can be simulated | Selected only as a test adapter; unsuitable for integration, resilience, or deployment |

### Operational Evaluation

| Option | Python ecosystem | Local, Docker, Windows, and Unraid | Resource and cluster model | Maturity, portability, and outcome |
| --- | --- | --- | --- | --- |
| Apache Kafka | Broad client ecosystem; `confluent-kafka` and `aiokafka` support Python 3.14 | Official container operation works from Windows or Linux Docker hosts and on Linux-based Unraid | Kafka 4.x is KRaft-only; a combined broker/controller is possible for development, while resilient production needs a controller and broker quorum | Apache-2.0, most mature ecosystem, and widest managed-service compatibility; not selected as the initial broker because the JVM and KRaft operating model add local overhead |
| Redpanda | Uses Kafka clients; `librdkafka` is validated, while individual clients still require adapter conformance tests | A single Docker container is practical for development on Windows/Linux hosts and Unraid; the broker itself is Linux-based | Single binary with no JVM or separate ZooKeeper/KRaft service; single-node operation is simple, but production mode still requires meaningful CPU, memory, and durable disk | Community Edition is source-available under BSL, not Apache-2.0; selected as the preferred initial self-hosted implementation, with license review and Kafka-subset portability tests required |
| RabbitMQ | Mature `pika` and asynchronous client options | Excellent Docker support and familiar Windows/Linux development | One node is straightforward; quorum queues and streams require multiple nodes for fault tolerance and add Erlang runtime overhead | Mature MPL-2.0 AMQP ecosystem with hosted options; rejected because replay plus key partitioning would require a more complex mix of queue, stream, and superstream features |
| NATS JetStream | Mature asynchronous `nats.py` client | Very small operational footprint and straightforward containers across target hosts | Single binary; simple single node and compact clusters | Apache-2.0 and operationally attractive; rejected because the accepted partition-key model and first-class quarantine workflow map less directly than Kafka partitions and consumer offsets |
| PostgreSQL-backed queue | Excellent Python database clients | Easy when a database already exists, but the database choice is unresolved | Reuses database resources but creates polling, vacuum, lock, and custom retention load | PostgreSQL is mature, permissively licensed, and widely hosted, but a queue implementation would be platform-specific code and would conflate transport with persistence |
| In-memory adapter | No additional dependency is required | Runs everywhere Python runs | Minimal resources and no cluster | Selected for deterministic unit and component tests only |

### Protocol, Implementation, Managed Services, and Test Adapters

These terms are deliberately distinct:

- The **domain contract** is the ADR-0004 JSON envelope and payload. It has no
  broker dependency.
- The **Event Bus port** is the platform-owned behavioral boundary defined in
  Section 4.
- The first **transport adapter** uses the Kafka protocol and only a documented
  tested subset of its features.
- **Redpanda Community Edition** is the preferred initial self-hosted
  implementation of that subset.
- Apache Kafka or a managed Kafka-compatible service is not automatically
  interchangeable. Each candidate must pass adapter conformance, security,
  administration, and failure-recovery tests before deployment.
- The **in-memory adapter** is development-only and does not prove broker
  semantics.

No managed cloud service is an architectural dependency.

All deployable broker candidates can be exercised through isolated containers
in CI, but their startup cost and failure controls differ. The in-memory option
is the only zero-service test adapter and cannot substitute for the selected
broker's integration and resilience suite.

### Kafka Protocol Capability Boundary

The Kafka-protocol adapter may depend only on this baseline capability set:

- produce records and receive broker publication acknowledgment;
- consume records from configured platform topics;
- keyed partitions using `workflow_id` as the record key;
- traditional consumer groups and partition assignment;
- manual offset commits after durable processing;
- message headers for nonauthoritative transport metadata;
- broker-supported client authentication;
- topic and consumer-group authorization;
- topic retention by configured age and size;
- idempotent producer behavior; and
- basic administration required for platform topics, limited to creating,
  describing, and validating topics and their approved partition, replication,
  retention, and access configuration.

The adapter, infrastructure definitions, and domain modules must not depend on
the following without a future ADR:

- Kafka Streams;
- ksqlDB or KSQL;
- Kafka Connect;
- MirrorMaker;
- a deployed Schema Registry;
- Tiered Storage;
- broker transactions as the mechanism for business or workflow consistency;
- broker-side transformations;
- Redpanda-specific Admin APIs; or
- any implementation-specific extension outside the allowed capability set.

Idempotent production is allowed because it reduces duplicate broker records
created by transport retries. It does not replace `message_id` deduplication,
the transactional outbox, or business idempotency. Message headers are
transport metadata and must not become an alternative source for domain
semantics already carried by the ADR-0004 envelope.

This allowlist uses mature Kafka capabilities implemented across Redpanda,
Apache Kafka, and common managed Kafka services. Excluding broker-side
processing, proprietary administration, managed-only storage, and auxiliary
Kafka products reduces migration surface and feature mismatch. It does not
reduce current platform capability: Vertical Slice 01 needs only durable keyed
publication, consumer groups, acknowledgments, retention, security, and basic
topic administration.

## 3. Kafka Versus Redpanda

| Concern | Apache Kafka | Redpanda | Decision effect |
| --- | --- | --- | --- |
| Protocol | Defines the Kafka APIs and ecosystem | Implements Kafka-compatible APIs with documented exceptions | Select a tested Kafka API subset, not blanket interchangeability |
| Coordination | Kafka 4.x uses KRaft and has removed ZooKeeper | Internal Raft implementation; no ZooKeeper or KRaft service to operate | Redpanda has fewer broker-side runtime components for the initial deployment |
| Development deployment | Combined broker/controller mode is available | Single broker binary and container | Redpanda is preferred for the small local stack |
| Production clustering | Mature broker and controller quorum practices | Mature broker clustering with its own administrative model | Neither provides machine-level high availability on only one physical failure domain |
| Memory and disk | JVM and page-cache operating model; tunable for small environments | No JVM, but production recommendations still require dedicated CPU, memory, and durable high-performance disk | Do not describe Redpanda as resource-free or use developer mode as production evidence |
| Operational tooling | Extensive Kafka ecosystem and long operational history | `rpk`, Admin API, and optional Console; smaller ecosystem | Redpanda simplifies initial administration but has a narrower independent tooling base |
| Maturity | Longest history and broadest third-party support | Younger implementation with a growing compatibility surface | Maintain Apache Kafka conformance as a portability check |
| License | Apache-2.0 | Community Edition uses the Business Source License and later converts code to Apache-2.0; commercial service restrictions apply | Repository-owner license compliance review is required before implementation or deployment |
| Standard clients | Native reference clients and broad third-party support | Standard clients work only within Redpanda's implemented Kafka subset | Use a narrow adapter and test every required feature |
| Migration | Source implementation | Kafka-compatible target/source for supported APIs | Broker data, consumer offsets, ACLs, configuration, and operational metadata do not migrate merely by changing a bootstrap address |
| Unraid and small self-hosting | Viable in containers, but KRaft/JVM tuning remains | Viable in one container for local or small self-hosted use | Redpanda is the preferred initial implementation |

At the time of review, Redpanda's production guidance requires at least two
physical CPU cores, at least 2 GB of memory per core, and durable local storage
with specific filesystem and I/O expectations. Its development mode relaxes
resource checks but can bypass `fsync`. The selection is therefore based on a
simpler component and administration footprint, not a claim that production
Redpanda has negligible resource requirements.

The architecture selects the Kafka protocol for the first transport adapter and
Redpanda Community Edition as the preferred initial self-hosted broker. It does
not select Apache Kafka-specific domain contracts, Redpanda administrative
APIs for domain code, Redpanda Cloud, or any other managed service.

Migration between Redpanda, Apache Kafka, and managed Kafka services requires:

- verification of every producer, consumer, group, offset, security, and
  administration feature used by the adapter;
- a planned topic and retention mapping;
- explicit data copy or dual-publish/cutover where retained data is required;
- consumer-offset migration or an approved replay start position;
- recreation and verification of identities, ACLs, certificates, and quotas;
  and
- resilience tests against the target implementation.

## 4. Event Bus Port

Domain modules depend on a technology-neutral Event Bus port with operations
equivalent to:

- publish one already validated immutable message to a logical channel and
  receive publication acknowledgment or a classified failure;
- consume messages for a named logical subscription;
- acknowledge a message after successful durable processing;
- reject a message with a retryable or permanent classification;
- access bounded transport metadata for diagnostics and acknowledgment;
- pause or stop new intake; and
- finish, abandon, or safely return in-flight work during shutdown.

The port must not expose Kafka or Redpanda producers, consumers, topics,
partitions, offsets, administration APIs, RabbitMQ exchanges, queues, or
delivery tags to the Orchestrator, Agent domain logic, or shared contracts.

Some transport behavior cannot be made identical. Adapter capabilities and
deployment configuration must document:

- whether negative acknowledgment is native or emulated;
- partition and consumer-group semantics;
- rebalance or lease behavior;
- maximum message size;
- retention and replay controls;
- native delayed-delivery support;
- producer idempotence; broker transactions remain outside the baseline
  capability set and cannot implement business consistency;
- broker durability and replication requirements; and
- transport-specific authentication and authorization features.

Domain behavior may require a capability, such as durable replay, but must not
branch on a broker product name.

The Kafka adapter implements only the capability allowlist in Section 2.
Unsupported capabilities are absent from the Event Bus port rather than
exposed conditionally. Infrastructure code may perform the allowed basic topic
administration, but domain modules may not invoke Kafka, Redpanda, or managed
service administration APIs. Adapter startup must fail clearly when a
configured broker cannot provide the required allowed capabilities.

### Messaging and Persistence Responsibility Boundary

This ADR defines messaging semantics only. Requiring durable coordination does
not select a persistence product, storage schema, or concrete transaction.

| Responsibility | Architectural owner and boundary in this ADR | Deferred to ADR-0006 |
| --- | --- | --- |
| Event Bus | Stores broker-accepted records for configured retention; assigns keyed partitions; delivers and redelivers records; maintains consumer-group positions; acknowledges publications; and carries transport quarantine records | No workflow, outcome, receipt, inbox, outbox, or deduplication state model |
| Outbox | The producing component retains one immutable outgoing publication and its publication state until broker acknowledgment; the outbox closes the state-to-publish failure window | Persistence technology, record ownership, transaction scope, durability, schema, queries, and recovery storage |
| Inbox | A consuming component durably records accepted message processing so redelivery does not repeat a state transition or side effect | Persistence technology, atomic relationship to domain updates, schema, retention, concurrency, and recovery |
| Workflow persistence | The Orchestrator owns workflow state and transitions; the broker is not their source of truth | Store selection, workflow storage ownership, transaction and durability guarantees, schema design, and recovery storage |
| Agent outcome persistence | The Agent owns its durable outcome and the immutable event prepared for publication | Store selection, transaction boundaries among receipt, outcome, and event outbox, schema design, and recovery storage |
| Deduplication persistence | Consumers require durable deduplication by consumer identity and `message_id`; Agents also enforce `task_attempt_id` business idempotency | Store, key representation, retention, concurrency protection, durability, cleanup, and recovery |
| Receipt persistence | The Agent durably records command receipt and its relationship to the retained outcome | Store, ownership boundaries, atomicity, schema, retention, and restart recovery |

ADR-0006 will define:

- persistence technology;
- storage ownership and access boundaries;
- concrete transactional boundaries;
- durability guarantees;
- persistence schema design; and
- recovery storage and queries.

ADR-0005 requires those future decisions to satisfy the messaging semantics
above, but does not preselect how they are implemented. Broker offsets and
retained messages cannot substitute for the required durable application
records.

## 5. Logical Channels

### Options

| Model | Advantages | Disadvantages |
| --- | --- | --- |
| Category channels such as `commands` and `events` | Few resources and simple global discovery | Broad access, mixed retention, increasing consumer filtering, and weak bounded-purpose ownership |
| Bounded-purpose channels such as `task-commands` and `task-outcomes` | Clear ownership, access control, scaling, retention, and replay boundaries without one resource per contract | No total order across the two channels; future bounded purposes add resources intentionally |
| One channel per contract | Precise routing, retention, and authorization | Three resources for the first slice, greater operational overhead, and avoidable coupling between physical resources and individual contract names |

### Selected Logical Channels

Vertical Slice 01 uses two logical channels:

- `task-commands`, containing `ExecuteTask`; and
- `task-outcomes`, containing `TaskCompleted` and `TaskFailed`.

This bounded-purpose model is selected because it separates work dispatch from
outcome observation, permits least-privilege Agent access, and avoids creating
a physical resource for every contract. Consumers validate `contract_name` and
`contract_version`; they do not infer the contract solely from the channel.

No progress, audit, registration, retry, or other domain channel is introduced.
Quarantine resources are operational transport resources, not new domain
events.

Future heterogeneous Agent types cannot simply use independent consumer groups
on `task-commands`, because every group would receive every retained command.
Before adding another command-consuming Agent class, the routing model must be
reviewed for capability-oriented subscriptions or additional bounded-purpose
channels. That future review does not add a channel or consumer to this slice.

## 6. Physical Naming

Logical channel names are stable platform concepts. Deployment configuration
maps them to physical broker resources.

The default physical naming pattern is:

```text
<platform>.<environment>.<logical-channel>.v<contract-major>
```

Illustrative names are:

```text
ai-platform.dev.task-commands.v1
ai-platform.dev.task-outcomes.v1
ai-platform.dev.task-commands.v1.quarantine
ai-platform.dev.task-outcomes.v1.quarantine
```

The environment is included by the deployment mapping when environments share
a broker. A dedicated broker may provide isolation at the cluster level, but
the mapping remains configuration rather than a domain constant. Kafka does
not provide a portable namespace abstraction across all compatible services,
so this ADR does not depend on one.

A new physical major is required when incompatible contract majors must coexist
or when a migration requires a new partition topology. Minor contract versions
remain distinguished by the envelope and do not create topics automatically.
AsyncAPI continues to describe logical channels and must not hardcode these
illustrative physical names.

## 7. Partitioning and Ordering

The adapter serializes the lowercase `workflow_id` string as the Kafka record
key. Every command or event for the same workflow uses that key.

The ordering guarantee is:

- total broker-record order only within one physical partition of one topic;
- logical platform ordering within `(logical_channel, workflow_id)`;
- no ordering between different workflows;
- no total ordering between `task-commands` and `task-outcomes`; and
- no guarantee that concurrent processing completion follows delivery order
  unless the consumer processes the partition serially.

The two first-slice topics use the same configured partition count and stable
adapter partitioning behavior. This makes a workflow map predictably within
each channel, but matching partition numbers across topics do not create a
cross-topic order.

The Orchestrator must validate the current workflow state and expected
transition for every event. A broker-ordered event can still be semantically
late, duplicate, conflicting, or invalid.

Partition count is deployment-configurable but fixed and small for an initial
topic generation. The exact count is chosen from measured concurrency and the
maximum useful consumer-instance count; it is not optimized for hypothetical
high throughput.

Adding partitions can remap a key and disturb ordering assumptions. When
ordering continuity matters, change partition count by provisioning a new
versioned physical topic, controlling cutover, draining or replaying the old
topic, and moving consumers deliberately. An in-place increase requires
explicit proof that affected workflows are drained or can tolerate the remap.
Kafka topics cannot reduce their partition count.

## 8. Delivery Semantics

At-least-once delivery is selected because it remains valid across producer
retries, lost acknowledgments, consumer failure, group rebalance, and process
termination. Exactly-once transport features do not make database state,
Agent work, or external side effects execute exactly once.

A message is considered durably published when:

1. the validated immutable message has been accepted by the broker;
2. the producer receives the configured strongest acknowledgment supported by
   the deployment, initially Kafka `acks=all`; and
3. the deployment's required in-sync-replica and durable-storage policy is
   satisfied.

On a single-node deployment, `acks=all` can acknowledge only that node. It does
not protect against loss of the machine or its storage. Development modes that
bypass durable disk synchronization do not prove the production guarantee.

Consumers use manual acknowledgment. For the Kafka adapter, acknowledgment
means committing progress only after validation and required durable domain
processing. If processing succeeds but the commit is lost, the message may be
redelivered and consumer idempotency resolves the duplicate.

Duplicate delivery is detected at two separate levels:

- consumer identity plus `message_id` deduplicates a logical publication; and
- `task_attempt_id` protects Agent business execution and the stored outcome.

## 9. Consumer Acknowledgement

Consumers acknowledge only after:

1. the envelope and exact declared schema have been validated;
2. authorization, identity, causation, and semantic relationships have been
   checked;
3. required workflow, receipt, outcome, inbox, or outbox state is durably
   stored; and
4. any required quarantine publication for a permanently rejected message has
   been acknowledged.

Consumers do not commit before required state persistence. Automatic offset
commit is disabled.

- A transient failure leaves progress uncommitted and enters bounded retry.
- Malformed, unsupported, unknown, or permanently invalid input does not retry
  forever; it is quarantined and then the source position can advance.
- If quarantine publication fails, the source message remains unacknowledged.
- A rebalance, consumer lease or poll timeout, cancellation, or process
  termination can abandon uncommitted work and cause redelivery.

Graceful shutdown stops new intake, allows a bounded interval for in-flight
durable processing and acknowledgment, and then closes the consumer. Work
that cannot reach its durability point is abandoned without committing so
another consumer can recover it.

## 10. Retry Strategy

Transport retry and application retry are separate:

### Immediate Transport Redelivery

Short transient failures use a small configured number of consumer-side
retries with bounded backoff. The Kafka adapter pauses or retains the affected
partition position and does not commit past the failed record. Initial
processing is serial per partition so retry does not violate partition order.

### Delayed Transport Retry

Vertical Slice 01 has no delayed transport retry. Kafka has no portable native
delayed-message primitive, while retry topics, scheduled republishing, and a
separate scheduler each add ordering, retention, and operating complexity.
After the immediate retry budget is exhausted, the record is quarantined and
the workflow resolves through `TaskFailed` or `task_result_deadline`.

Adopting delayed retry later requires review of retry topics versus scheduled
republishing, ordering implications, and recovery ownership.

### Application Retry

An application retry is an Orchestrator decision that creates a new
`task_attempt_id` and a new command publication. Application retry policy is
out of scope for this ADR and absent from Vertical Slice 01.

Every transport retry or redelivery preserves:

- `message_id`;
- `task_attempt_id`;
- `correlation_id`;
- `causation_id`; and
- the complete immutable envelope and payload.

It never creates a new logical publication.

## 11. Dead-Letter and Quarantine Handling

Vertical Slice 01 uses a restricted quarantine topic for each logical source
channel. Quarantine is selected over an implicit broker dead-letter feature
because Kafka-compatible brokers do not define a portable per-record
dead-letter operation.

Failure classifications include:

| Classification | Initial disposition |
| --- | --- |
| Malformed JSON | Quarantine without domain processing |
| Schema-invalid envelope or payload | Quarantine with safe validation summary |
| Unsupported contract version | Quarantine with `UNSUPPORTED_CONTRACT_VERSION` |
| Unknown contract name | Quarantine as unsupported contract |
| Permanent semantic or authorization rejection | Quarantine without retry |
| Repeated transient processing failure | Quarantine after bounded immediate retries |
| Suspected consumer implementation defect | Quarantine the affected record, pause or stop the consumer when failures appear systemic, and require operator diagnosis |

A quarantine record preserves, subject to security and retention policy:

- the original immutable bytes or a protected reference when retaining the
  bytes is unsafe;
- source topic, partition, and offset;
- record key and safe headers;
- failure classification and sanitized diagnostic detail;
- consumer component and logical subscription;
- failure timestamp;
- transport delivery or retry count when available; and
- `message_id`, `workflow_id`, `task_attempt_id`, and contract metadata when
  they can be extracted safely.

Quarantine data is operational metadata, not a new domain event. It must not
contain public stack traces, credentials, or unsanitized exception data.

Replay is an explicit authorized operator action after diagnosis or correction.
It is never an automatic infinite loop. Replaying a command requires the same
idempotency and side-effect safeguards as any other delivery.

## 12. Producer Reliability

### Evaluated Patterns

| Pattern | Failure behavior | Outcome |
| --- | --- | --- |
| Publish then update database | Broker may contain work for state that was never committed | Rejected |
| Update database then publish directly | A crash can commit state but lose the message | Rejected |
| Transactional outbox | State and immutable outgoing message are committed together; a separate publisher retries broker delivery | Selected |
| Broker transaction | Cannot atomically include the independent workflow database and would couple domain processing to broker APIs | Rejected as the database consistency mechanism |
| Uncoordinated dual-write with reconciliation | Requires detecting and repairing both missing state and missing messages | Rejected as the primary model |

The Orchestrator uses a transactional outbox:

1. the Orchestrator validates the transition and constructs the immutable
   `ExecuteTask` message;
2. workflow state and the outbox message are durably committed in one state
   transaction;
3. the workflow reaches `DISPATCHED` when the command is durably recorded in
   the outbox, as required by Vertical Slice 01;
4. a recovery-capable publisher reads unpublished outbox records and publishes
   them through the Event Bus port;
5. the publisher marks publication only after broker acknowledgment; and
6. restart recovery resumes every record whose publication is not confirmed.

An acknowledgment can be lost after the broker accepted the message.
Republishing therefore uses the original bytes, key, and `message_id` and may
create duplicate broker records. Consumer deduplication remains required even
when the Kafka producer uses idempotent mode.

This ADR requires the outbox behavior because it is part of reliable message
publication, but defines no persistence technology, storage owner, transaction
implementation, durability level, schema, table, or recovery query. ADR-0006
must define those persistence details while preserving the publication
semantics above.

## 13. Agent Result Publication

The Test Agent requires a durable command receipt, a durable outcome record,
and an event outbox that can be committed atomically through the persistence
capability selected later.

The sequence is:

1. receive and validate `ExecuteTask`;
2. check the receipt and outcome by `task_attempt_id` and command
   `message_id`;
3. return or republish the stored outcome when processing already completed;
4. perform deterministic work only when no completed outcome exists;
5. durably record one outcome and one immutable `TaskCompleted` or
   `TaskFailed` event with its stable event `message_id`;
6. publish or republish that event through the Agent outbox; and
7. acknowledge the command only after the receipt, outcome, and event-outbox
   durability point.

Transport redelivery after Step 5 never repeats the work. If the Test Agent
crashes before Step 5, Vertical Slice 01 permits recomputation because the
operation is deterministic and has no external side effect. The durable model
guarantees one accepted outcome, not universal at-most-once computation across
an unrecorded crash window.

Future side-effecting Agents must use an idempotent external operation,
pre-execution claim or lease, side-effect ledger, or another explicitly
documented policy. This ADR does not select Agent persistence or a universal
side-effect protocol.

The receipt, outcome, deduplication, and event-outbox records are application
persistence, not Event Bus state. ADR-0006 must define their storage ownership,
transactional boundaries, durability, schema, retention, and restart-recovery
mechanism.

## 14. Consumer Groups and Scaling

Vertical Slice 01 defines only two logical subscriptions:

- all Test Agent instances share one consumer group for `ExecuteTask` on
  `task-commands`; and
- all Orchestrator instances share one consumer group for `TaskCompleted` and
  `TaskFailed` on `task-outcomes`.

One partition is assigned to at most one active member of a traditional
consumer group at a time. One message is therefore processed by one active
group member, subject to redelivery after failure or rebalance.

Different consumer groups may independently receive the same retained event.
Adding instances increases parallelism only up to the topic's partition count.
All records for one workflow key remain assigned to one partition within the
logical channel. Scaling does not remove message or business idempotency
requirements.

No additional consumer is introduced for hypothetical future use.

## 15. Message Retention and Replay

The Event Bus is a replay-capable transport with bounded retention, not the
permanent system of record.

Deployment configuration defines separate retention categories for:

- task commands, covering expected Agent outage and recovery;
- task outcomes, covering expected Orchestrator outage, lag, and controlled
  event replay;
- quarantine records, covering diagnosis and explicitly authorized
  disposition; and
- broker internal consumer-offset and transaction metadata.

Each category has age and size limits, disk alerts, and a documented behavior
when capacity is approached. Exact durations and byte limits require workload,
privacy, recovery-time, and storage-capacity evidence and remain bounded open
questions.

Broker retention does not replace workflow snapshots, transition history,
Agent outcomes, or outboxes. Replay from retained offsets must remain
idempotent. Event replay may rebuild derived state; command replay must not
blindly repeat irreversible effects.

## 16. Schema and Contract Handling

The adapter carries UTF-8 JSON conforming to ADR-0004.

Before publication:

- the producer validates the envelope and payload against the exact declared
  schema;
- the Event Bus adapter accepts immutable validated bytes and the logical
  `workflow_id` ordering key; and
- the adapter rejects an unknown logical channel or unsupported adapter
  capability.

After consumption and before domain processing:

- the consumer validates JSON syntax, the complete envelope, exact contract
  version, payload, identifiers, and relationships;
- unsupported contract names or versions are quarantined safely; and
- domain logic receives validated platform models, not broker records.

The adapter:

- preserves the complete envelope and payload and the original `message_id`;
- uses `workflow_id` as the record key;
- never rewrites timestamps, identifiers, contract names, or versions; and
- never injects topic, partition, offset, consumer group, retry count, broker
  timestamp, or delivery state into the portable envelope.

No deployed schema registry is selected. Repository-owned JSON Schemas remain
authoritative.

## 17. Security

Production and shared deployments require:

- encryption in transit for client-to-broker and inter-broker traffic;
- authenticated producers, consumers, and administrators;
- deny-by-default authorization scoped to physical topics, consumer groups,
  and required administrative operations;
- separate principals for the platform service, Test Agent, and operational
  quarantine access;
- runtime secret injection through the future approved secret boundary;
- certificate and credential rotation without embedding material in images or
  source control;
- restricted broker listeners and administration interfaces;
- network exposure limited to explicitly required clients; and
- pinned, maintained broker and client artifacts reviewed under
  `SECURITY.md`.

The Orchestrator principal writes task commands and reads task outcomes. The
Test Agent principal reads task commands and writes task outcomes. Neither
receives broad cluster-administration access. Quarantine access is more
restricted because records can retain workflow content.

Local development may use simplified authentication only on an isolated,
test-owned network with nonsecret credentials and loopback-limited exposure.
That configuration is explicitly non-production and must not become the
production default.

This ADR does not select an identity provider, secrets manager, SASL
mechanism, or certificate-issuance process.

## 18. Observability

Required operational signals include:

- publication acknowledgment, failure, and latency;
- outbox backlog age and count;
- consumer lag by group and partition;
- message processing latency;
- redelivery and retry counts;
- validation and unsupported-version failures;
- quarantine publication and backlog counts;
- consumer-group membership, health, rebalance, and partition assignment;
- broker health, under-replicated or unavailable partitions, disk usage, and
  retention pressure; and
- graceful-shutdown and in-flight-message outcomes.

Logs include, where safely available:

- `message_id`;
- `workflow_id`;
- `task_id`;
- `task_attempt_id`;
- `correlation_id`;
- `contract_name` and `contract_version`;
- logical channel and logical subscription;
- producer or consumer component;
- safe topic, partition, offset, and delivery metadata; and
- classified processing or publication outcome.

Logs do not contain complete workflow input, message bodies, credentials,
certificates, or unsafe stack traces. This ADR selects no monitoring, metrics,
logging, or tracing backend.

## 19. Local Development

The local model is:

- a single containerized Redpanda broker for ordinary development;
- the same Kafka-protocol adapter used by deployed components;
- an in-memory Event Bus adapter for isolated unit and component tests only;
- a test-owned Redpanda container for integration, resilience, and
  end-to-end tests; and
- optional, explicitly configured compatibility tests against Apache Kafka or
  another candidate deployment before migration.

Windows developers run the Linux broker through Docker or equivalent container
tooling. Linux and Unraid run the same pinned container image. CI workers start
an isolated broker container owned by the test job; no shared or managed broker
is required.

Redpanda developer mode may be used for fast exploratory work, but it can
bypass durable disk synchronization. Tests that assert durable publication,
broker restart recovery, or disk behavior use a durability-preserving test
configuration and a persistent test-owned volume.

Ordinary development does not require a production cluster. Production
replication, failure domains, backups, and upgrade procedures require the later
deployment-topology decision.

## 20. Testing Strategy

Tests align with `docs/testing/README.md`.

### Unit and Component Tests

The in-memory adapter supports deterministic tests of:

- Event Bus port calls and classified failures;
- logical routing;
- producer and consumer validation;
- acknowledgment policy;
- retry classification;
- deduplication decisions;
- graceful shutdown; and
- injected duplicate, late, and out-of-order messages.

These tests do not claim Kafka or Redpanda behavior.

### Contract Tests

Repository-owned contract tests verify:

- exact producer and consumer schemas;
- preservation of immutable bytes and identifiers;
- `workflow_id` key mapping and stable partition vectors;
- unsupported contract handling;
- separation of transport metadata; and
- adapter capability declarations.

### Local Integration, Resilience, and End-to-End Tests

A test-owned Redpanda container verifies:

- publish and consume behavior through the real adapter;
- ordering within one workflow and no assumed order across workflows or
  channels;
- at-least-once redelivery;
- duplicate `message_id` and `task_attempt_id`;
- manual acknowledgment after durable processing;
- failure before acknowledgment;
- group rebalance and consumer scaling;
- producer failure before and after durable state changes;
- Orchestrator and Agent outbox recovery;
- immediate retry and exhausted-retry quarantine;
- quarantine publication failure;
- graceful shutdown;
- broker and component restart;
- retention and controlled replay;
- unsupported versions;
- transport metadata isolation; and
- single-node data-loss limitations where they can be tested safely.

No delayed-retry test is required because delayed retry is not selected for the
first slice.

External or separately operated broker tests are opt-in external-service tests.
An in-memory adapter never substitutes for real-broker integration coverage.

## 21. Selected Python Client

| Concern | `confluent-kafka` | `aiokafka` |
| --- | --- | --- |
| Async integration | Current releases provide first-class asyncio producer and consumer APIs as well as mature synchronous APIs | Native asyncio design is its central strength |
| Performance and reliability | Built on `librdkafka`, with broad production use and mature producer, consumer, administration, statistics, idempotence, and transaction features | Mature asyncio client with idempotent producer and transaction support; generally less operational surface |
| Maintenance and ecosystem | Production/stable project maintained by Confluent; `librdkafka` is validated by Redpanda | Maintained by the aio-libs community and classified beta on PyPI |
| Python 3.14 and platforms | Publishes CPython 3.14 wheels for mainstream Windows, Linux x86-64, and Linux ARM64 targets | Publishes CPython 3.14 wheels for Windows and mainstream Linux x86-64 and ARM64 targets |
| Dependencies | Native `librdkafka` dependency, normally supplied in wheels; source builds and uncommon architectures require care | Python-facing asyncio API with compiled wheel artifacts on common platforms |
| Typing | Adapter-owned types are still required; upstream typing gaps must not leak through the port | Adapter-owned types are still required; upstream typing gaps must not leak through the port |
| Broker portability | Strong standard Kafka client; Redpanda documents `librdkafka` as validated, while the Python wrapper still requires conformance testing | Standard Kafka-protocol client, but not listed among Redpanda's specifically validated Python clients |

`confluent-kafka` is selected for the initial adapter because its current
asyncio support removes the earlier event-loop integration disadvantage while
retaining `librdkafka` reliability, operational statistics, idempotent-producer
support, administration features, and broad Kafka deployment compatibility.

The project will pin the selected release through uv only when implementation
begins. The adapter must hide all client types, callbacks, exceptions,
partitions, and offsets from domain modules. `aiokafka` remains the fallback if
conformance testing reveals an unresolved asyncio, typing, packaging, or
Redpanda compatibility issue.

## 22. Decision

The coherent messaging architecture is:

- a technology-neutral platform-owned Event Bus port;
- a Kafka-protocol transport adapter limited to produce, consume, keyed
  partitions, traditional consumer groups, manual offset commits, message
  headers, authentication, authorization, retention, idempotent production,
  and basic platform-topic administration;
- no dependency on Kafka Streams, ksqlDB, Connect, MirrorMaker, Schema
  Registry, Tiered Storage, broker transactions for business consistency,
  broker-side transformations, Redpanda-specific Admin APIs, or other
  implementation-specific extensions without a future ADR;
- Redpanda Community Edition as the preferred initial self-hosted broker;
- no managed-service dependency and no claim of full Kafka implementation
  interchangeability;
- `confluent-kafka` as the preferred Python client behind the adapter;
- two bounded-purpose logical channels: `task-commands` and `task-outcomes`;
- deployment-configured physical names with platform, environment, purpose,
  and contract-major components;
- UTF-8 `workflow_id` record keys;
- ordering within `(logical_channel, workflow_id)`, with no global or
  cross-channel order;
- small deployment-configured partition counts that are fixed for a physical
  topic generation;
- at-least-once delivery with strongest configured producer acknowledgment,
  idempotent producer mode, manual consumer acknowledgment, and idempotent
  consumers;
- traditional consumer groups for Test Agent command processing and
  Orchestrator outcome processing;
- a transactional Orchestrator outbox;
- a durable Agent receipt, outcome, and event outbox;
- durable inbox and deduplication behavior whose persistence technology,
  ownership, transaction boundaries, guarantees, schema, and recovery storage
  are deferred to ADR-0006;
- bounded immediate transport retry and no delayed retry in Vertical Slice 01;
- restricted per-channel quarantine topics and explicit operator replay;
- bounded configurable retention, with workflow state remaining external and
  authoritative;
- an in-memory adapter for unit and component tests only; and
- a real containerized Redpanda broker for integration, resilience, and
  end-to-end tests.

## 23. Consequences

### Positive Consequences

- Keyed partitions directly implement the accepted workflow-ordering model.
- Consumer groups provide independent subscriptions, recovery positions, and
  bounded horizontal scaling.
- Redpanda provides the required Kafka subset without a JVM or separate KRaft
  service in the initial local stack.
- The Event Bus port and canonical contracts isolate broker and client APIs.
- Outboxes close the state-versus-publication loss window without requiring a
  distributed transaction.
- Explicit retry and quarantine behavior prevents poison-message loops.
- Kafka-protocol conformance provides a credible path to Apache Kafka and
  compatible managed offerings after validation.

### Negative Consequences

- A durable broker, topics, groups, offsets, retention, ACLs, and quarantine
  resources add operational work.
- Redpanda production mode is not a negligible service and requires suitable
  CPU, memory, storage, and tuning.
- Redpanda Community Edition is BSL source-available rather than OSI-approved
  open source.
- Kafka has no native portable delayed-message primitive, so the first slice
  omits delayed transport retry.
- Two channels do not provide cross-channel total ordering.
- Partition counts constrain maximum active consumer parallelism and are
  difficult to change without ordering impact.
- Transactional outboxes and durable deduplication create persistence and
  recovery work.
- `confluent-kafka` introduces native artifacts and client-specific adapter
  maintenance.

### Migration Impact

There is no Event Bus implementation to migrate. Vertical Slice 01 already
requires an Event Bus port, outbox recovery, Agent outcome durability,
at-least-once delivery, and `workflow_id` ordering.

Implementation must add only the adapter, configured broker resources, and
tests required by the relevant phase. A future broker migration requires the
explicit compatibility and cutover work in Section 3; changing bootstrap
configuration alone is insufficient.

### Developer Impact

- Developers run a small Redpanda container for real-broker work.
- Fast tests use the in-memory adapter but must not assert broker guarantees.
- Message handlers must validate exact contracts and remain idempotent.
- Consumer code commits only after durable processing.
- Broker exceptions and metadata remain inside the adapter.
- New logical channels, delayed retries, or partition-topology changes require
  architecture review.

### CI Impact

Future CI can run unit, component, and contract tests without a broker, then
start a pinned Redpanda container for integration and resilience tests.
Commands remain platform-neutral and do not require a managed service.

Broker tests require more time, memory, disk, and failure diagnostics than
in-memory tests. The repository does not currently claim that such CI is
configured.

### Operational Impact

- Operators manage broker health, disk capacity, retention, partitions,
  replication, consumer lag, ACLs, certificates, quarantine, and upgrades.
- One-node operation is convenient but is not machine-failure tolerant.
- Consumer lag and outbox backlog become first-class recovery indicators.
- Topic creation and configuration are infrastructure responsibilities, not
  application side effects.
- Replay and quarantine redrive require explicit authorization and audit.

### Security Impact

- The broker becomes a sensitive data and command boundary requiring TLS,
  authentication, ACLs, restricted networking, patching, and retention policy.
- Quarantine can retain original workflow data and therefore requires tighter
  access and potentially shorter retention.
- Redpanda licensing and container provenance require review before adoption.
- Local insecure settings must remain isolated and visibly non-production.

### Future Review Triggers

Review or supersede this decision when:

- Redpanda license terms or required features no longer fit the project;
- the required Kafka feature subset differs materially across target brokers;
- measured load requires a different partition or cluster topology;
- heterogeneous Agent classes require command routing beyond the single Test
  Agent consumer group;
- delayed transport retry becomes a demonstrated requirement;
- cross-channel total ordering becomes necessary;
- a side-effecting Agent requires stronger execution guarantees;
- one or two physical machines cannot meet durability or availability goals;
- broker resource cost is disproportionate to the workload;
- the selected Python client loses runtime, platform, or maintenance support;
  or
- privacy requirements require a different retention or quarantine design.

## 24. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Broker operational complexity | Keep the first topology small, provision it as code, pin releases, document health and recovery, and avoid optional enterprise features |
| Single-node data loss | State the limitation, retain durable outboxes and workflow state, back up according to the later topology decision, and require multiple failure domains for real high availability |
| Disk exhaustion | Configure age and size retention, monitor disk and partition growth, reject unsafe capacity assumptions, and define capacity alerts |
| Consumer lag | Observe lag and processing latency, bound message cost, scale only within partition limits, and investigate sustained backlog |
| Partition hot spots | Use stable `workflow_id` keys, measure distribution, and avoid placing unrelated global work on one key |
| Changing partition counts | Prefer a new physical topic generation and controlled cutover; never assume an in-place increase preserves key mapping |
| Poison-message retry loops | Classify failures, bound immediate retry, quarantine permanent or exhausted records, and require explicit replay |
| Duplicate processing | Preserve `message_id` and `task_attempt_id`, use durable inbox or receipt records, and test acknowledgment loss |
| Outbox backlog | Recover publishers on startup, observe age and count, retain original bytes and identity, and alert before workflow deadlines expire |
| State and message inconsistency | Commit state and outbox atomically and make publication acknowledgment a separate recoverable transport state |
| Agent outcome loss | Atomically retain receipt, outcome, and event outbox before acknowledging the command |
| Kafka-compatible implementations differ | Restrict the feature subset, run conformance and failure tests, and plan migrations rather than assuming interchangeability |
| Kafka ecosystem capabilities expand the adapter implicitly | Enforce the Section 2 allowlist in the port, dependency review, configuration, and conformance tests; require a future ADR for every prohibited capability |
| Messaging semantics are mistaken for persistence design | Keep the Section 4 responsibility matrix authoritative and require ADR-0006 to select stores, owners, transactions, durability, schemas, and recovery storage |
| Development and production diverge | Use the real broker for integration tests and prevent developer mode from proving durability |
| Broker concepts leak through the port | Prohibit client types and metadata in domain modules, review adapter boundaries, and test transport-metadata isolation |
| Sensitive retained messages | Minimize payloads, encrypt transport, restrict topic and quarantine access, bound retention, and never log bodies |
| Redpanda BSL use violates repository-owner policy or intended deployment terms | Complete license compliance review before implementation or deployment; retain Apache Kafka as the tested protocol-compatible alternative |
| Client native wheels are unavailable on a target | Validate CPython 3.14 artifacts for every target architecture and test source-build or alternative-client fallback before deployment |

## 25. Assumptions

- ADR-0001 through ADR-0004 remain Accepted.
- Vertical Slice 01 contains only `ExecuteTask`, `TaskCompleted`, and
  `TaskFailed`.
- CPython 3.14 remains the accepted runtime.
- Workflow and Agent persistence capabilities can provide the atomicity needed
  by the selected outbox, inbox, receipt, outcome, and deduplication model;
  ADR-0006 will select the technology, ownership, transaction boundaries,
  durability, schema, and recovery storage.
- Initial development and self-hosting can provide a Linux container runtime
  and a durable local volume.
- One physical machine is acceptable for development and non-high-availability
  use; production availability requirements remain unresolved.
- The planned self-hosted use does not offer Redpanda as a commercial
  streaming or queuing service to third parties; license compliance must be
  confirmed before implementation or deployment.
- Required Kafka API features are limited to the explicit Section 2 allowlist.
- No deployed schema registry, broker transform, Kafka Streams application, or
  managed-service-only feature is required.
- Exact retry counts, retention durations, replication factors, image pins,
  and certificate processes require deployment evidence.

## 26. Open Questions

The following bounded implementation and deployment questions do not change
the accepted broker, capability boundary, port, channels, ordering, or delivery
semantics:

1. What small initial partition count matches measured local concurrency?
2. What age and size limits apply to commands, outcomes, and quarantine data?
3. What replication factor and physical failure-domain layout apply outside
   local single-node operation?
4. What bounded immediate retry count and backoff values fit
   `task_result_deadline`?
5. What exact authorized quarantine inspection, correction, replay, and
   disposal procedure is used?
6. Which Redpanda image and version are pinned for the first implementation?
7. Which TLS certificate-issuance and rotation process is selected?
8. Who records the required Redpanda Community Edition license compliance
   review before the first implementation or deployment?

## 27. Explicitly Out of Scope

This ADR does not decide:

- workflow or Agent persistence technology;
- concrete inbox, outbox, receipt, or outcome table design;
- the Workflow API framework;
- an authentication provider or secrets manager;
- authorization outside broker-level requirements;
- a monitoring, logging, metrics, or tracing backend;
- full deployment topology, backup, or disaster recovery;
- Kubernetes;
- an AI provider, AI Router, or LangGraph;
- additional commands, events, logical domain channels, or consumers;
- application-level workflow retry policy;
- production retention durations or capacity;
- a deployed schema registry;
- broker-side data transforms; or
- managed cloud service selection.

## 28. Acceptance Checklist

- [ ] The Kafka-protocol adapter and preferred Redpanda Community Edition
      implementation are approved.
- [ ] The Redpanda BSL trade-off and pre-implementation license compliance
      requirement are approved.
- [ ] At-least-once delivery and the prohibition on end-to-end exactly-once
      claims are approved.
- [ ] The technology-neutral Event Bus port and capability boundary are
      approved.
- [ ] The allowed Kafka capabilities are explicit and sufficient for Vertical
      Slice 01.
- [ ] Kafka Streams, ksqlDB, Connect, MirrorMaker, Schema Registry, Tiered
      Storage, business-consistency transactions, broker-side transformations,
      Redpanda-specific Admin APIs, and implementation-specific extensions
      require a future ADR.
- [ ] `task-commands` and `task-outcomes` are approved as the only first-slice
      logical channels.
- [ ] Physical naming and deployment mapping remain outside domain contracts.
- [ ] UTF-8 `workflow_id` keying and small deployment-configured partition
      counts are approved.
- [ ] Ordering is approved within `(logical_channel, workflow_id)`, without
      global or cross-channel ordering.
- [ ] Manual acknowledgment after validation and durable processing is
      approved.
- [ ] Bounded immediate retry and no first-slice delayed retry are approved.
- [ ] Per-channel quarantine and explicit operator replay are approved.
- [ ] The transactional Orchestrator outbox is approved architecturally without
      selecting persistence.
- [ ] Durable Agent receipt, outcome, and event-outbox behavior is approved.
- [ ] Event Bus, outbox, inbox, workflow state, Agent outcome, deduplication,
      and receipt responsibilities are distinct.
- [ ] ADR-0006 owns persistence technology, storage ownership, transactional
      boundaries, durability guarantees, schema design, and recovery storage.
- [ ] The Test Agent crash-window recomputation interpretation is approved.
- [ ] The two Vertical Slice 01 consumer groups and partition-limited scaling
      model are approved.
- [ ] Bounded configurable retention and broker replay behavior are approved.
- [ ] The broker is not treated as the workflow system of record.
- [ ] ADR-0004 contract bytes, identifiers, version validation, and
      transport-metadata separation are preserved.
- [ ] Broker TLS, authentication, least privilege, secret injection, and
      isolated development defaults align with `SECURITY.md`.
- [ ] Required operational signals and safe log fields are approved without
      selecting a monitoring backend.
- [ ] In-memory and real-broker local test responsibilities are distinct.
- [ ] The complete contract, integration, resilience, restart, retention, and
      replay test expectations are approved.
- [ ] `confluent-kafka` is approved behind the Event Bus adapter, or its
      fallback condition is accepted as bounded.
- [ ] Single-node, disk, lag, partition, duplicate, outbox, compatibility,
      licensing, and retained-data risks are accepted with their mitigations.
- [ ] Every remaining open question has an owner or is accepted as a bounded
      implementation or deployment policy.
- [ ] Reviewers confirm consistency with ADR-0001 through ADR-0004, Vertical
      Slice 01, the test strategy, `SECURITY.md`, and `AGENTS.md`.
- [ ] No out-of-scope persistence, identity, monitoring, deployment, AI, or
      additional domain-message decision has been introduced.

## Related Decisions

- [ADR-0001: Core Design Principles](ADR-0001-core-design-principles.md)
- [ADR-0002: Platform Communication and State](ADR-0002-platform-communication-and-state.md)
- [ADR-0003: Runtime and Development Tooling](ADR-0003-runtime-and-development-tooling.md)
- [ADR-0004: API and Contract Standards](ADR-0004-api-and-contract-standards.md)

## References

- [Platform Architecture](../README.md)
- [Vertical Slice 01](../../implementation/vertical-slice-01.md)
- [Platform test strategy](../../testing/README.md)
- [Repository security policy](../../../SECURITY.md)
- [Repository agent guidance](../../../AGENTS.md)
- [Apache Kafka design](https://kafka.apache.org/42/design/design/)
- [Apache Kafka KRaft operations](https://kafka.apache.org/42/operations/kraft/)
- [Apache Kafka topic and partition operations](https://kafka.apache.org/42/operations/basic-kafka-operations/)
- [Apache Kafka Docker images](https://kafka.apache.org/42/getting-started/docker/)
- [Redpanda Kafka compatibility](https://docs.redpanda.com/streaming/current/develop/kafka-clients/)
- [Redpanda licensing](https://docs.redpanda.com/streaming/current/get-started/licensing/overview/)
- [Redpanda development deployment](https://docs.redpanda.com/current/deploy/redpanda/manual/production/dev-deployment/)
- [Redpanda production requirements](https://docs.redpanda.com/25.2/deploy/redpanda/manual/production/requirements/)
- [Redpanda authentication](https://docs.redpanda.com/streaming/current/manage/security/authentication/)
- [RabbitMQ quorum queues](https://www.rabbitmq.com/docs/quorum-queues)
- [RabbitMQ streams and superstreams](https://www.rabbitmq.com/docs/streams)
- [NATS JetStream](https://docs.nats.io/nats-concepts/jetstream)
- [NATS JetStream consumers](https://docs.nats.io/nats-concepts/jetstream/consumers)
- [`confluent-kafka` project metadata](https://pypi.org/project/confluent-kafka/)
- [`confluent-kafka` client documentation](https://docs.confluent.io/kafka-clients/python/current/overview.html)
- [`aiokafka` project metadata](https://pypi.org/project/aiokafka/)
- [`aiokafka` API documentation](https://aiokafka.readthedocs.io/en/stable/api.html)
