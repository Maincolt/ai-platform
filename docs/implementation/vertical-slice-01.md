# Vertical Slice 01: Deterministic Single-Agent Workflow

- **Status:** Implementation plan
- **Implementation status:** Not started
- **Source of truth:** Accepted ADR-0001 and ADR-0002

## 1. Purpose

This plan defines the smallest end-to-end workflow that proves the platform's
core architecture without calling an AI model.

The slice accepts text, durably creates one workflow and one task attempt,
selects one configured Test Agent by capability, dispatches the task
asynchronously, and exposes a queryable success or failure result.

The successful deterministic result contains:

- the original text;
- a word count; and
- the timestamp at which the Test Agent first completed that task attempt.

The slice proves:

- durable workflow state;
- asynchronous execution;
- at-least-once message delivery;
- idempotent processing;
- restart recovery;
- capability-based Agent selection;
- end-to-end traceability; and
- queryable terminal outcomes.

This document is subordinate to:

- [ADR-0001: Core Design Principles](../architecture/decisions/ADR-0001-core-design-principles.md);
- [ADR-0002: Platform Communication and State](../architecture/decisions/ADR-0002-platform-communication-and-state.md);
- the [platform architecture](../architecture/README.md);
- the [test strategy](../testing/README.md); and
- the repository [security policy](../../SECURITY.md).

## 2. Scope

The slice includes only these logical responsibilities:

- **Workflow API** — accept one local submit operation and one local query
  operation.
- **Orchestrator** — validate domain input, create domain identifiers, own
  workflow state, select the configured Agent, dispatch one task attempt,
  consume one terminal result, and recover incomplete work.
- **Workflow State Store** — durably persist Orchestrator state through an
  explicit versioned port.
- **Event Bus** — deliver task commands and results asynchronously with
  at-least-once semantics.
- **Capability Registry** — an Orchestrator-owned, configuration-backed logical
  registry containing one versioned Test Agent manifest.
- **One Test Agent** — perform deterministic word count without an LLM.
- **Shared contracts** — API, event-envelope, command, result, identifier, and
  capability-manifest contracts.
- **Configuration** — local settings, the Agent manifest, authorization policy,
  retry bounds, and deadlines.
- **Logging and health** — structured logs and component health checks.
- **Local Docker deployment** — the minimum containers, durable volume, and
  health dependencies required for the slice.
- **Automated tests** — focused no-infrastructure and local-infrastructure
  coverage.

The Workflow API, Orchestrator, and Capability Registry may share one process
while remaining separate modules. The Test Agent remains a separate consumer
process so the asynchronous boundary is real.

There is exactly one logical task and one `task_attempt_id` per workflow in
this slice.

## 3. Out of Scope

The following are deferred to future vertical slices:

- dynamic Agent registration;
- Agent heartbeats and availability expiry;
- multiple Agents and load balancing;
- application-level task retries and additional task attempts;
- `TaskStarted`, acceptance events, progress reporting, and long-running task
  leases;
- cancellation;
- workflow-level published audit or notification events;
- generic dead-letter administration, redrive, and replay;
- metrics export and an external observability stack;
- LangGraph or another orchestration framework;
- the AI Router and LLM calls;
- a frontend;
- public API exposure and production identity infrastructure;
- multi-step workflows;
- Skills;
- production high availability, scaling, and multi-host deployment;
- global message ordering;
- exactly-once delivery claims; and
- production Unraid deployment.

No contract or infrastructure component is added without an active
responsibility in this slice.

## 4. Assumptions

1. ADR-0001 and ADR-0002 remain Accepted and govern implementation.
2. The Test Agent supports only `text.word-count` capability version `1.0`.
3. Word count is the number of nonempty text segments separated by Unicode
   whitespace. Original text is returned unchanged.
4. Workflow input is synthetic local-development data.
5. The local deployment retains state across individual process and container
   restarts.
6. The Event Bus retains messages required for local restart tests.
7. The platform service starts as soon as persistence and the Event Bus are
   available. Test Agent readiness does not gate platform startup, Workflow API
   availability, or workflow queries.
8. The selected persistence design can keep Orchestrator workflow data and
   Test Agent receipt data logically isolated with least-privilege access.
9. A transactional state-and-outbox design is required, but its concrete
   mechanism remains subject to ADR-0006.
10. Retry counts, `task_result_deadline`, retention, and identifier encoding
    remain configurable until the relevant ADR accepts exact rules.
11. API examples are logical mappings. Protocol and representation remain
    subject to ADR-0004.
12. Configuration loading is the slice's registration mechanism: the Test
    Agent manifest is owned with the Agent deployment but loaded and validated
    by the Orchestrator at startup.

Assumption 12 is a constrained first-slice interpretation of ADR-0002's Agent
registration requirement. Dynamic self-registration remains future work and
must not be implied as implemented.

## 5. Architecture Overview

```text
                 submit/query
                     |
                     v
           +--------------------+
           |    Workflow API    |
           +---------+----------+
                     |
                     v
           +--------------------+
           |    Orchestrator    |
           | Capability Registry|
           +----+----------+----+
                |          |
     state port |          | async contracts
                v          v
        +-----------+  +-----------+
        | Workflow  |  | Event Bus |
        | State     |  +-----+-----+
        | Store     |        |
        +-----------+        v
                       +------------+
                       | Test Agent |
                       +-----+------+
                             |
                      isolated receipt
                      and result records
```

The smallest proposed local deployment has:

1. a platform service containing the API, Orchestrator, Capability Registry,
   and Orchestrator outbox/recovery workers;
2. the Test Agent;
3. the selected Event Bus implementation; and
4. the selected durable persistence implementation.

No AI Router, LLM, registration service, monitoring service, or metrics backend
is present.

### Boundary Rules

- The Workflow API owns transport concerns, not domain identifiers or state.
- Only the Orchestrator mutates workflow execution state.
- The Capability Registry is inside the Orchestrator boundary.
- The Test Agent cannot read or mutate workflow records.
- Task commands and results cross the Event Bus.
- Orchestrator and Agent code depend on platform-owned ports, not concrete bus
  or persistence interfaces.
- Each component writes only its own inbox, outbox, or receipt data.

## 6. End-to-End Sequence

### Startup

1. Persistence and the Event Bus become healthy.
2. The platform service starts and validates configuration.
3. The Orchestrator loads the versioned Test Agent manifest into its in-process
   Capability Registry.
4. The platform service reloads nonterminal workflows and resumes unpublished
   outbox messages.
5. The Workflow API becomes ready for submissions and queries independently of
   Test Agent startup. Agent readiness never prevents workflow queries.
6. Independently, the Test Agent starts, validates its local configuration, and
   becomes ready to consume its supported command. It may become ready before
   or after the Workflow API.

### Workflow Execution

1. A caller submits text and capability `text.word-count` version `1.0`.
2. The Workflow API validates transport shape and request size.
3. The Workflow API accepts a client `request_id` or generates one, then
   delegates workflow creation and any valid propagated correlation context to
   the Orchestrator.
4. The Orchestrator checks the accepted-request mapping. An equivalent request
   with the same `request_id` returns the existing workflow identifiers and
   current state; a different request with that `request_id` returns the stable
   conflict error `REQUEST_ID_CONFLICT`.
5. For a new `request_id`, the Orchestrator validates domain input and
   capability support. Invalid or unsupported input is rejected without
   creating a workflow.
6. The Capability Registry selects the configured, compatible Test Agent only
   if its current readiness check succeeds. If no ready Agent exists, the
   Orchestrator returns `AGENT_TEMPORARILY_UNAVAILABLE` without creating a
   workflow.
7. The Orchestrator creates `workflow_id`, `task_id`, `task_attempt_id`, and
   `correlation_id` unless a valid correlation context was propagated.
8. The Orchestrator durably creates the workflow as `RECEIVED`, associated with
   `request_id`.
9. The Orchestrator transitions the workflow to `PENDING`. The `RECEIVED` and
   `PENDING` transitions are logically distinct but may be committed in one
   database transaction with both transition-history records preserved.
10. The Orchestrator creates an `ExecuteWordCountTask` command and its
    `message_id`.
11. The Orchestrator atomically records the command in its outbox and
     transitions the workflow to `DISPATCHED`.
12. The outbox publisher publishes the command using
     `partition_key = workflow_id`.
13. The Event Bus delivers the command at least once.
14. The Test Agent validates the envelope, selected Agent, capability, contract
     version, and payload.
15. The Test Agent checks its receipt store by `task_attempt_id` and command
     `message_id`.
16. On first processing, the Agent computes word count, captures one processing
     timestamp, creates its result `message_id`, and atomically stores the
     receipt, terminal result, and result-outbox record.
17. The Agent publishes either `TaskCompleted` or `TaskFailed`.
18. On transport redelivery, the Agent republishes the stored result using the
     same result `message_id` without recomputing.
19. The Orchestrator validates and deduplicates the result by consumer and
     result `message_id`, verifies `task_attempt_id`, and transitions directly
     from `DISPATCHED` to `COMPLETED` or `FAILED`.
20. The caller queries the Workflow API and receives the durable terminal state
     and success or failure result.

## 7. Component Responsibilities

### Workflow API

- Bind only to an explicitly configured local or internal interface.
- Validate transport syntax, request size, and required fields.
- Accept or generate `request_id`.
- Propagate only a valid caller correlation context.
- Delegate all workflow creation to the Orchestrator.
- Return identifiers created by the Orchestrator.
- Expose local submit and query operations independently of Test Agent
  readiness.
- Keep workflow queries available whenever the platform service is ready.
- Return `AGENT_TEMPORARILY_UNAVAILABLE` when the Orchestrator reports that no
  configured compatible Agent is ready; this rejection occurs before workflow
  creation.
- Return existing identifiers and current state for an equivalent accepted
  `request_id`, and `REQUEST_ID_CONFLICT` when the same `request_id` identifies
  a different request.
- Enforce `LocalDevelopmentAuthorizationPolicy`.
- Return stable sanitized errors.

Logical operations:

| Operation | Input | Output |
| --- | --- | --- |
| `SubmitWorkflow` | `request_id` if supplied, text, capability name, capability version | `request_id`, `workflow_id`, `task_id`, `task_attempt_id`, `correlation_id`, current state |
| `GetWorkflow` | `workflow_id` | identifiers, state, result or failure, and timestamps |

The API does not write the state store or publish task commands.

### Orchestrator

- Validate domain input before workflow creation.
- Resolve accepted `request_id` mappings idempotently before creating domain
  identifiers.
- Generate all domain identifiers.
- Own the five-state workflow model and every transition.
- Persist workflow, task, task-attempt, transition, inbox, and outbox records.
- Load and validate the configured Agent manifest.
- Require and select a ready compatible Test Agent before workflow creation.
- Create the command envelope and command `message_id`.
- Publish through its durable outbox.
- Consume terminal results idempotently.
- Resume unpublished outbox records after restart.
- Resolve an expired durable `task_result_deadline` without creating another
  task attempt.

### Workflow State Store

- Provide durable, versioned persistence ports.
- Support atomic workflow-state and Orchestrator-outbox writes.
- Support atomic Agent-receipt, result, and Agent-outbox writes.
- Support inbox or receipt deduplication.
- Support optimistic concurrency or equivalent lost-update protection.
- Support transition and task-attempt history.
- Support indexed lookup for nonterminal and expired `DISPATCHED` workflows.
- Preserve data across restart.
- Enforce logical access separation between Orchestrator and Agent data.

Infrastructure provisions the persistence capability. The Orchestrator owns the
workflow model and transitions.

### Event Bus

- Deliver `ExecuteWordCountTask`, `TaskCompleted`, and `TaskFailed`.
- Provide at-least-once delivery.
- Preserve identity during transport redelivery.
- Partition workflow messages using `workflow_id`.
- Support bounded consumer processing attempts.
- Store or route exhausted messages and sanitized failure metadata through the
  selected transport's dead-letter mechanism.
- Expose acknowledgement and delivery state through a platform-owned port.
- Retain enough durable state for restart tests.

The Event Bus does not publish a generic dead-letter domain event.

### Capability Registry

- Remain a logical module inside the Orchestrator.
- Load one versioned manifest from local configuration at startup.
- Validate capability and contract compatibility.
- Evaluate the configured Test Agent's current readiness when a new workflow is
  submitted.
- Report that no selectable Agent exists when the configured compatible Test
  Agent is not ready, so the submission is rejected before workflow creation.
- Select the single compatible Agent deterministically.

It does not retain availability history, process announcements, or track
heartbeats. The Registry remains configuration-based for this slice; the
readiness check does not introduce dynamic registration or discovery.

### Test Agent

- Expose liveness and readiness checks.
- Consume only the configured command contract.
- Validate every untrusted envelope and payload.
- Deduplicate using both `task_attempt_id` and command `message_id`.
- Store a result against one specific `task_attempt_id`.
- Return the stored result for duplicate delivery.
- Compute word count deterministically.
- Publish only `TaskCompleted` or `TaskFailed`.
- Create its own result `message_id` and set `causation_id` to the command
  `message_id`.
- Support a test-only terminal failure mode enabled only by local test
  configuration.
- Never call an LLM or AI Router.

### Shared Contracts, Configuration, and Logging

- Define versioned API, message-envelope, command, result, and manifest
  contracts.
- Keep contracts independent from frameworks, transport, and persistence.
- Validate configuration at startup.
- Commit only nonsecret example configuration.
- Emit structured logs with the fields in Section 15.

## 8. Workflow State Model

### Persisted States

| State | Meaning |
| --- | --- |
| `RECEIVED` | A valid domain request and its identifiers are durably accepted. |
| `PENDING` | The workflow has a selected, ready configured Agent and is ready for dispatch. |
| `DISPATCHED` | The task command is durably stored in the Orchestrator outbox. |
| `COMPLETED` | A valid success result for the task attempt is durably accepted. |
| `FAILED` | A valid failure result, terminal task-result timeout, or terminal processing failure is durably accepted. |

`COMPLETED` and `FAILED` are terminal.

Invalid API shape, unsupported capability, and invalid domain input are rejected
before workflow creation. A new submission without a ready configured Agent is
also rejected before workflow creation and cannot leave a workflow indefinitely
in `PENDING`.

### Transitions

| From | To | Cause | Owner |
| --- | --- | --- | --- |
| none | `RECEIVED` | Valid domain request is durably created | Orchestrator |
| `RECEIVED` | `PENDING` | Task and its single attempt are created | Orchestrator |
| `PENDING` | `DISPATCHED` | Command for the selected compatible Agent is stored in outbox | Orchestrator |
| `DISPATCHED` | `COMPLETED` | Valid `TaskCompleted` result | Orchestrator |
| `DISPATCHED` | `FAILED` | Valid `TaskFailed` result | Orchestrator |
| `DISPATCHED` | `FAILED` | No terminal result arrives by `task_result_deadline` or terminal consumer processing fails | Orchestrator |

A duplicate, late, or conflicting result cannot move a terminal workflow.

`RECEIVED` and `PENDING` remain two logical transitions with separate history
records. Their workflow snapshot, task, task attempt, accepted-request mapping,
and both transition records may be persisted in one database transaction. No
crash-recovery boundary is required between the two states.

There is no persisted validation, running, or cancellation state. Long-running
task lifecycle and cancellation are future work.

### Task Attempt

The workflow has one stable `task_id` and one `task_attempt_id`.
`attempt_number` is always `1` in this slice.

The attempt records:

- `workflow_id`;
- `task_id`;
- `task_attempt_id`;
- `attempt_number`;
- command `message_id`;
- selected Agent identity;
- `task_result_deadline`;
- publication state;
- result `message_id` if present; and
- terminal outcome if present.

The identifier exists now so later application-level retries can add a new
attempt without redefining contracts.

## 9. Commands and Results

The Event Bus carries only three workflow message contracts.

| Message | Kind | Producer | Consumer | Responsibility |
| --- | --- | --- | --- | --- |
| `ExecuteWordCountTask` | Command | Orchestrator | Test Agent | Request execution of one identified task attempt. |
| `TaskCompleted` | Result | Test Agent | Orchestrator | Return original text, word count, and stable processing timestamp. |
| `TaskFailed` | Result | Test Agent | Orchestrator | Return a safe terminal error for the identified attempt. |

### Command Payload

`ExecuteWordCountTask` contains:

- `task_attempt_id`;
- `attempt_number = 1`;
- selected `agent_id`;
- capability name and version;
- original text; and
- `task_result_deadline`.

### Success Result

`TaskCompleted` contains:

- `task_attempt_id`;
- `attempt_number = 1`;
- original text;
- word count;
- first successful processing timestamp;
- Agent identifier and version; and
- capability name and version.

### Failure Result

`TaskFailed` contains:

- `task_attempt_id`;
- `attempt_number = 1`;
- safe error code;
- sanitized summary;
- failure timestamp;
- Agent identifier and version; and
- capability name and version.

Failure is terminal in this slice. A retryable flag is unnecessary until
application-level retries exist.

No startup, heartbeat, started, audit, workflow-terminal, or generic
dead-letter message contract is created.

## 10. Event-Envelope Proposal

The envelope is versioned and independent from the selected transport.

| Field | Required | Ownership and lifecycle |
| --- | --- | --- |
| `message_id` | Yes | Created by the message producer. Stable across transport redelivery. |
| `event_type` | Yes | Stable contract name for the command or result. |
| `message_kind` | Yes | `command` or `result` in this slice. |
| `contract_version` | Yes | Version used for compatibility validation. |
| `occurred_at` | Yes | UTC creation time set by the producer. |
| `producer` | Yes | Logical component and runtime instance. |
| `workflow_id` | Yes | Complete workflow identity created by the Orchestrator. |
| `task_id` | Yes | Logical task identity created by the Orchestrator. |
| `task_attempt_id` | Yes | One application-level execution attempt created by the Orchestrator. |
| `correlation_id` | Yes | End-to-end execution identity created by the Orchestrator unless valid context is propagated. |
| `causation_id` | Results | Direct causal command `message_id`; null for the command created from an API request. |
| `request_id` | Command | Incoming request identity accepted or generated by the Workflow API. |
| `partition_key` | Yes | Set to `workflow_id`; ordering is not global. |
| `capability_name` | Yes | Initially `text.word-count`. |
| `capability_version` | Yes | Initially `1.0`. |
| `payload` | Yes | Contract-specific validated data. |

### Identifier Ownership

- The Workflow API accepts or generates `request_id`.
- The Workflow API propagates only a valid correlation context.
- The Orchestrator creates `workflow_id`, `task_id`, and `task_attempt_id`.
- The Orchestrator creates `correlation_id` when none is validly propagated.
- Every producer creates the `message_id` for its own message.
- Every producer sets `causation_id` to the direct causal message where one
  exists.
- The Workflow API returns the identifiers created by the Orchestrator.

### API Request Idempotency

An accepted `request_id` identifies one canonical validated submission:
workflow text, capability name, capability version, and API contract version.

- Repeating the `request_id` with an equivalent request returns the existing
  `workflow_id`, `task_id`, `task_attempt_id`, `correlation_id`, and current
  workflow state.
- Repeating the `request_id` with a different canonical request returns
  `REQUEST_ID_CONFLICT`.
- The accepted-request mapping is created atomically with the workflow and is
  unique by `request_id`, so concurrent submissions cannot create two
  workflows for one accepted `request_id`.
- A submission rejected before workflow creation, including
  `AGENT_TEMPORARILY_UNAVAILABLE`, does not create an accepted-request mapping.

### Retry Identity Rules

Application-level retries are not implemented, but future retries must:

- retain `workflow_id`;
- retain `task_id`;
- create a new `task_attempt_id`;
- create a new command `message_id`; and
- increment `attempt_number`.

Transport redelivery:

- retains `workflow_id`;
- retains `task_id`;
- retains `task_attempt_id`;
- retains `message_id`; and
- does not increment `attempt_number`.

Identifiers remain opaque strings at boundaries. Encoding and compatibility
rules require ADR-0004.

## 11. Capability Manifest Proposal

The Orchestrator loads one manifest from local configuration.

| Field | Required | Meaning |
| --- | --- | --- |
| `manifest_version` | Yes | Version of the manifest contract. |
| `agent_id` | Yes | Stable Test Agent identity. |
| `agent_version` | Yes | Test Agent implementation version. |
| `capability_name` | Yes | `text.word-count`. |
| `capability_version` | Yes | `1.0`. |
| `accepted_command_contract_versions` | Yes | Supported `ExecuteWordCountTask` versions. |
| `produced_result_contract_versions` | Yes | Supported `TaskCompleted` and `TaskFailed` versions. |

The manifest contains no availability, health-history, heartbeat, freshness,
draining, or degraded status fields.

Readiness is a local deployment condition, not manifest data. The configured
Agent becomes selectable only after its container or process readiness check
passes at submission time. Platform startup and workflow queries do not depend
on that readiness. If the selected Agent becomes unavailable after acceptance,
bounded transport processing and `task_result_deadline` eventually resolve the
workflow to `FAILED`.

Configuration is registration for this slice. Dynamic Agent-owned registration
is deferred.

## 12. Persistence Model

The durable persistence capability is the source of truth for workflow state.
Events communicate commands and results but do not replace the workflow
snapshot.

### Logical Records

| Record | Owner | Required data |
| --- | --- | --- |
| API request mapping | Orchestrator | Unique `request_id`, canonical request fingerprint, `workflow_id`, domain identifiers, and creation outcome for request idempotency. |
| Workflow | Orchestrator | `workflow_id`, `request_id`, `correlation_id`, input, capability, state, result or failure, timestamps, and revision. |
| Task | Orchestrator | `task_id`, workflow reference, capability, selected Agent, and terminal outcome. |
| Task attempt | Orchestrator | `task_attempt_id`, `task_id`, attempt number, command ID, `task_result_deadline`, publication state, result ID, and outcome. |
| Transition | Orchestrator | Previous state, new state, direct cause, actor, and timestamp. |
| Orchestrator inbox | Orchestrator | Consumer identity, result `message_id`, task-attempt reference, outcome, and retention deadline. |
| Orchestrator outbox | Orchestrator | Command envelope, publication state, transport attempts, and timestamps. |
| Configured manifest | Orchestrator | Validated manifest version and content loaded for the current deployment. |
| Agent command receipt | Test Agent | `task_attempt_id`, command `message_id`, status, processing timestamp, and retained outcome. |
| Agent result outbox | Test Agent | Result envelope, stable result `message_id`, publication state, and timestamps. |
| Dead-letter metadata | Transport/consumer boundary | Original message reference, bounded attempts, sanitized failure, and disposition. |

A stored Agent result is associated with exactly one `task_attempt_id`.

The Test Agent receipt rule is:

- same `task_attempt_id` and same command `message_id`: return or republish the
  stored outcome;
- same `task_attempt_id` with a different command `message_id`: treat as a
  conflicting command and fail safely;
- different `task_attempt_id`: a different application attempt, which is
  future behavior and is not produced by this slice.

### Required Persistence Guarantees

ADR-0006 must evaluate the selected technology against:

- durable workflow snapshots;
- transactional workflow-state and outbox writes;
- inbox and Agent receipt deduplication;
- optimistic concurrency or equivalent protection;
- transition and task-attempt history;
- indexed recovery queries;
- configurable retention;
- restart durability; and
- logical separation between Orchestrator and Agent data.

The Orchestrator atomically commits:

- a state transition;
- any inbox acknowledgement; and
- any resulting outbox change.

For initial workflow creation, one transaction may commit the unique API request
mapping, workflow, task, task attempt, the logical `RECEIVED` and `PENDING`
transitions, and both transition-history records. This preserves the state
model without requiring recovery between the two initial transitions.

The Test Agent atomically commits:

- the command receipt;
- the stable result; and
- the result-outbox entry.

An outbox publisher may publish the same logical message more than once.
Stable identifiers and durable receipts make that safe.

Retention duration remains unresolved. Input is synthetic, and full workflow
text is not written to logs.

## 13. Delivery, Deduplication, and Recovery

### Transport Attempts

- Delivery is at least once.
- Redelivery preserves all domain identifiers and `message_id`.
- `attempt_number` remains `1`.
- Consumers validate before processing.
- Consumer processing attempts are bounded by configuration.
- After exhaustion, the failed message and sanitized failure metadata are
  stored or routed through the selected transport's dead-letter mechanism.
- Exact dead-letter topology, format, retention, inspection, and replay are
  defined by ADR-0005.

No generic dead-letter domain event exists.

### Workflow Resolution

- A valid `TaskCompleted` transitions `DISPATCHED` to `COMPLETED`.
- A valid `TaskFailed` transitions `DISPATCHED` to `FAILED`.
- A workflow reaches `DISPATCHED` when its command is durably recorded in the
  Orchestrator outbox, before transport publication acknowledgement.
- Publication acknowledgement is transport state. If publication is
  unconfirmed after restart and `task_result_deadline` has not expired, the
  Orchestrator republishes the same outbox envelope with the same `message_id`.
- `task_result_deadline` is the maximum time allowed to receive either
  `TaskCompleted` or `TaskFailed`. If it expires without a terminal result, the
  Orchestrator transitions the workflow to `FAILED` regardless of publication
  acknowledgement state.
- The slice does not create another `task_attempt_id`.

A terminal consumer failure must therefore become queryable either through
`TaskFailed` or `task_result_deadline` reconciliation. This slice does not
define a separate publication deadline.

### Platform Service Recovery

On restart, the platform service:

1. reloads nonterminal workflows;
2. resumes unpublished Orchestrator outbox messages;
3. reloads configured Agent manifests;
4. inspects `DISPATCHED` workflows whose `task_result_deadline` expired; and
5. transitions an expired workflow to `FAILED`, or safely republishes an
   unconfirmed command whose deadline has not expired.

### Test Agent Recovery

On restart, the Test Agent:

1. reloads processed command receipts;
2. resumes unpublished result-outbox messages;
3. republishes a stored result with the same result `message_id`; and
4. resumes consuming only after its dependencies are ready.

If the Agent crashed after storing a receipt but before storing a result, it
may safely recompute the deterministic word count for the same
`task_attempt_id`. The first completed result and timestamp are then stored
atomically.

### Replay Safety

Generic replay is not implemented. Dead-letter redrive and event replay are
future work. A later slice must not blindly repeat irreversible side effects.

## 14. Security Considerations

### Validation and Untrusted Data

- Reject malformed API requests before workflow creation.
- Reject unsupported capability or domain input before `RECEIVED`.
- Validate every message and manifest against its versioned contract.
- Verify workflow, task, attempt, Agent, capability, and causation
  relationships before applying a result.
- Treat text and event payloads as data, never as executable instructions.
- Return stable safe error codes and exclude stack traces from contracts.

### Local Authorization

An authorization interface exists at the Workflow API boundary.

`LocalDevelopmentAuthorizationPolicy`:

- permits requests only when local-development mode is explicitly enabled;
- requires the API to bind to an explicitly configured local or internal
  interface;
- introduces no external identity claim, fake production token, or identity
  provider; and
- is replaceable without bypassing the authorization interface.

The Orchestrator validates the configured Agent identity and allowed capability
before dispatch. Configuration registration does not grant broader
authorization.

### Secrets and Least Privilege

- Commit only nonfunctional example configuration.
- Keep credentials and machine-local values outside source control.
- Do not put secrets in API payloads, messages, logs, test fixtures, images, or
  state snapshots.
- The Workflow API cannot write persistence directly.
- The Test Agent cannot access workflow records.
- Bus and persistence access are limited to each component's routes and
  logical data.
- Containers run without elevated privilege unless a documented requirement
  proves it necessary.

No destructive or irreversible action occurs in this slice. Future such actions
require explicit human approval as defined by `SECURITY.md`.

## 15. Observability Requirements

### Structured Logs

Required fields are:

- `timestamp`;
- `level`;
- `component`;
- `instance_id`;
- `environment`;
- `workflow_id`;
- `task_id`;
- `task_attempt_id`;
- `message_id`;
- `correlation_id`;
- `causation_id`;
- `event_type`;
- `contract_version`;
- `processing_outcome`;
- `duration_ms`; and
- `error_code`.

Fields that do not apply to a log entry are null or omitted consistently.
Transport processing count may be logged separately from domain
`attempt_number`.

The original workflow text and secrets are not logged.

### Health Checks

- Platform-service liveness confirms the process is responsive.
- Platform-service readiness requires valid configuration, reachable
  persistence, a ready Event Bus publisher/consumer, loaded compatible
  manifest, and started recovery worker.
- Platform-service readiness and Workflow API query availability do not require
  a ready Test Agent. Submission eligibility is evaluated separately for each
  new workflow.
- Test Agent liveness confirms the process is responsive.
- Test Agent readiness requires valid configuration, reachable receipt
  persistence, and a ready Event Bus consumer.
- Local persistence and Event Bus containers expose basic health checks needed
  for startup ordering and tests.

No monitoring service or metrics backend is introduced. Metrics export is
deferred. A small number of internal counters, such as duplicate commands,
outbox backlog, and terminal outcomes, may be exposed or logged only when useful
for tests.

## 16. Proposed Repository Structure

This task creates no source directory. The proposed minimal layout remains:

```text
.
├── src/
│   └── platform/
│       ├── api/
│       ├── orchestrator/
│       │   └── capability-registry/
│       ├── agents/
│       │   └── test-agent/
│       ├── contracts/
│       ├── ports/
│       │   ├── event-bus/
│       │   └── persistence/
│       ├── adapters/
│       │   ├── event-bus/
│       │   └── persistence/
│       └── shared/
│           ├── configuration/
│           └── logging/
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── component/
│   ├── integration/
│   └── end-to-end/
├── infrastructure/
│   └── local/
└── docs/
    └── implementation/
        └── vertical-slice-01.md
```

The runtime ADR determines package metadata, concrete filenames, and whether
any logical directories should be combined.

## Technology Evaluation

No new technology is selected by this plan.

| Area | Current status | Required evaluation |
| --- | --- | --- |
| Runtime language | Python is a planned candidate, not Accepted. | ADR-0003 compares it with suitable service-language alternatives and decides runtime and development tooling. |
| Orchestration framework | LangGraph is not Accepted and is unnecessary for this slice. | Defer it. An ADR is required before later adoption as an Orchestrator dependency. |
| Event Bus | Kafka is a planned candidate, not Accepted. | ADR-0005 compares durable message-broker options against partitioning, acknowledgement, bounded retry, dead-letter, and local durability needs. |
| Persistence | No durable workflow store is Accepted. | ADR-0006 compares storage categories against the guarantees in Section 12. |
| Containers | Docker-based deployment is Accepted by ADR-0001. | Detailed local topology and orchestration remain unresolved. |
| Local orchestration | Docker Compose is a planned candidate, not Accepted. | Cover it in an existing decision if sufficient, otherwise use a separate local-container-topology ADR. |

A relational database is a strong persistence candidate because the slice
requires transactional state/outbox writes, concurrency protection, history,
and indexed recovery queries. This is an evaluation direction, not a product
selection.

Redis may be evaluated for caching, leases, temporary availability, or
projections. It is not assumed to be the durable workflow source of truth and
must prove every Section 12 guarantee before being considered for that role.

This plan does not select PostgreSQL, Oracle, Redis, or another persistence
product.

## 17. Testing Strategy

The slice follows the repository [test strategy](../testing/README.md).

### No-Infrastructure Tests

- workflow state-transition unit tests;
- `RECEIVED` and `PENDING` single-transaction history tests;
- event-envelope validation tests;
- identifier ownership and propagation tests;
- equivalent and conflicting `request_id` idempotency tests, including
  concurrent submissions;
- capability-manifest validation tests;
- deterministic word-count tests;
- Orchestrator result idempotency tests;
- Agent deduplication tests using `task_attempt_id` and command `message_id`;
- stable Agent result and processing-timestamp tests;
- outbox, inbox, and receipt model tests;
- configuration validation tests;
- `LocalDevelopmentAuthorizationPolicy` tests; and
- structured-log redaction tests.

### Local-Infrastructure Tests

- concrete Event Bus publish and consume test;
- concrete persistence durability and atomicity test;
- platform and Workflow API startup while the Test Agent is unavailable;
- workflow query while the Test Agent is unavailable;
- temporary-unavailable submission rejection without workflow creation;
- Orchestrator outbox recovery after restart;
- Test Agent stored-result republication after restart;
- duplicate command-delivery test;
- end-to-end success test;
- end-to-end Agent failure test;
- workflow query after platform and Agent restart;
- structured-log correlation and causation test; and
- Docker startup, health-check, persistent-volume, and shutdown validation.

### Deferred Tests

- dynamic registration and heartbeat tests;
- stale Agent and availability-expiry tests;
- application-level retry and retry-exhaustion tests;
- started/running lease recovery tests;
- cancellation and progress tests;
- metrics backend tests;
- generic dead-letter replay tests; and
- broad chaos or resilience testing.

No shared, hosted, external AI, or production service is required. All
infrastructure tests run against an isolated local stack owned by the test run.

## 18. Implementation Phases

### Phase 1: Decisions and Contracts

- **Goal:** Accept required ADRs and define identifiers, API contracts, event
  envelope, command/result payloads, and the configured Agent manifest.
- **Modules affected:** ADR files, `src/platform/contracts/`,
  `src/platform/shared/`, `tests/unit/`, and `tests/contract/`.
- **Dependencies:** ADR-0001 and ADR-0002.
- **Tests:** Envelope, identifier ownership/propagation, API fixtures, message
  fixtures, manifest compatibility, and invalid-version tests.
- **Completion criteria:** ADR-0003 through ADR-0006 are Accepted as required;
  contracts are versioned, technology-neutral, and validated locally.
- **Suggested commit:** `Define vertical slice decisions and contracts`

### Phase 2: Workflow Domain and Persistence Ports

- **Goal:** Implement the five-state workflow, task and single-attempt models,
  Orchestrator persistence port, inbox/outbox, and Agent receipt/result port.
- **Modules affected:** `src/platform/orchestrator/`,
  `src/platform/ports/persistence/`, and unit/component tests.
- **Dependencies:** Phase 1 and ADR-0006.
- **Tests:** State transitions, terminal protection, request mapping,
  `task_attempt_id` rules, outbox/inbox atomic models, receipt conflicts, and
  concurrency behavior.
- **Completion criteria:** Domain behavior is independent from the selected
  persistence adapter and all valid transitions are Orchestrator-owned.
- **Suggested commit:** `Add workflow domain and persistence ports`

### Phase 3: Orchestrator and Capability Registry

- **Goal:** Create workflows, load the configured manifest, select the Test
  Agent, create one command, process results, and apply idempotent terminal
  transitions.
- **Modules affected:** `src/platform/orchestrator/`,
  `src/platform/orchestrator/capability-registry/`, and component tests.
- **Dependencies:** Phases 1 and 2.
- **Tests:** Invalid pre-creation input, identifier ownership, manifest
  compatibility, deterministic selection, command creation, duplicate results,
  conflicting results, and `task_result_deadline` failure.
- **Completion criteria:** A controlled-port workflow reaches `COMPLETED` or
  `FAILED` with exactly one task attempt.
- **Suggested commit:** `Implement minimal workflow orchestration`

### Phase 4: Test Agent

- **Goal:** Implement deterministic word count, command validation, durable
  receipt/result handling, duplicate behavior, and test-only terminal failure.
- **Modules affected:** `src/platform/agents/test-agent/`, Agent receipt port
  usage, configuration, logging, and tests.
- **Dependencies:** Phases 1 and 2.
- **Tests:** Word count, invalid command, selected-Agent mismatch,
  `task_attempt_id` and message-ID deduplication, conflicting duplicate,
  stable result/timestamp, failure mode, and result-outbox recovery.
- **Completion criteria:** One attempt produces one stable success or failure
  result and no AI dependency exists.
- **Suggested commit:** `Add deterministic word count test agent`

### Phase 5: Workflow API

- **Goal:** Add local submit/query operations, transport validation,
  `request_id`, local authorization, and stable errors.
- **Modules affected:** `src/platform/api/`, API contracts, platform startup,
  and component/security tests.
- **Dependencies:** Phases 1 and 3 and ADR-0004.
- **Tests:** Valid submit, invalid pre-creation input, request idempotency,
  query success/failure/not-found, identifier return, bind configuration,
  authorization policy, and error sanitization.
- **Completion criteria:** The API delegates creation to the Orchestrator and
  returns only Orchestrator-generated domain identifiers.
- **Suggested commit:** `Add local workflow submission and query API`

### Phase 6: Concrete Adapters and Docker Deployment

- **Goal:** Implement selected persistence and Event Bus adapters, platform and
  Agent containers, local orchestration, durable volumes, and health checks.
- **Modules affected:** `src/platform/adapters/`, `infrastructure/local/`,
  example configuration, and infrastructure tests.
- **Dependencies:** Phases 1 through 5, ADR-0005, ADR-0006, and an accepted
  local-topology decision if required.
- **Tests:** Bus publish/consume, bounded processing attempts, selected
  dead-letter behavior, persistence durability/atomicity, image startup,
  readiness ordering, volume persistence, least privilege, and shutdown.
- **Completion criteria:** The documented local Docker stack becomes healthy
  without committed secrets and preserves state across restart.
- **Suggested commit:** `Add local vertical slice adapters and deployment`

### Phase 7: Integration, End-to-End, and Restart Tests

- **Goal:** Prove success, failure, duplicate delivery, recovery, queryability,
  and traceability against the local stack.
- **Modules affected:** `tests/integration/`, `tests/end-to-end/`, local test
  controls, and fixtures.
- **Dependencies:** Phase 6.
- **Tests:** Every local-infrastructure test listed in Section 17.
- **Completion criteria:** A clean stack passes success and failure paths,
  duplicate commands do not duplicate outcomes, restarts recover outboxes and
  results, and one trace joins every component.
- **Suggested commit:** `Add vertical slice end-to-end recovery tests`

### Phase 8: Verified Documentation

- **Goal:** Document only demonstrated local operation, troubleshooting,
  restart/recovery, contracts, and architectural boundaries.
- **Modules affected:** root and directory README files, `docs/`, and
  `infrastructure/local/`.
- **Dependencies:** Phases 1 through 7.
- **Tests:** Markdown links, documented Docker commands, clean startup, health,
  success/failure queries, restart, shutdown, and secret checks.
- **Completion criteria:** A contributor can reproduce verified behavior from a
  clean checkout and no deferred feature is claimed as implemented.
- **Suggested commit:** `Document verified vertical slice operation`

## 19. Acceptance Criteria

The slice is accepted when:

- a valid workflow can be submitted through the local API;
- invalid or unsupported input is rejected before workflow creation;
- the platform service and Workflow API become ready when persistence and the
  Event Bus are available, independently of Test Agent readiness;
- workflow queries remain available while the configured Test Agent is not
  ready;
- a new submission without a ready configured Test Agent returns
  `AGENT_TEMPORARILY_UNAVAILABLE` before workflow creation and leaves no
  workflow in `PENDING`;
- the Workflow API owns `request_id` and the Orchestrator generates all domain
  identifiers;
- an equivalent request with an accepted `request_id` returns the existing
  workflow identifiers and current state;
- a different request with an accepted `request_id` returns
  `REQUEST_ID_CONFLICT`, and no accepted `request_id` creates two workflows;
- workflow state is durably persisted;
- `RECEIVED` and `PENDING` remain separate logical transitions with preserved
  history even when committed in one transaction;
- the configuration-backed Capability Registry selects the compatible Test
  Agent;
- one task command is dispatched asynchronously;
- the command contains `workflow_id`, `task_id`, `task_attempt_id`,
  `message_id`, `correlation_id`, and the required contract metadata;
- the Test Agent returns original text, correct word count, and a stable
  processing timestamp;
- duplicate delivery of the same command does not duplicate execution outcome;
- the Agent deduplicates using `task_attempt_id` and command `message_id`;
- a terminal Agent failure produces a queryable `FAILED` workflow;
- exhausted command processing eventually results in a queryable `FAILED`
  workflow through terminal result or `task_result_deadline`;
- `DISPATCHED` begins when the command is durably recorded, publication
  acknowledgement remains transport state, and expiry of
  `task_result_deadline` produces a terminal `FAILED` workflow;
- the platform service resumes unpublished outbox messages after restart;
- the Test Agent republishes stored results using the same result `message_id`
  after restart;
- completed and failed workflows remain queryable after restart;
- logs include `task_attempt_id` and connect the execution through correlation
  and causation identifiers;
- the documented Docker stack starts, becomes healthy, and stops;
- required automated tests pass; and
- no LLM, AI Router, frontend, dynamic Agent discovery, cancellation,
  application-level retry, or metrics backend is introduced.

## 20. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Transport redelivery is mistaken for a new attempt | Preserve `task_attempt_id`, command `message_id`, and `attempt_number`; test duplicate delivery. |
| Future application retry is mistaken for a duplicate | Define new-attempt identity rules now and deduplicate by attempt plus command ID. |
| API and Orchestrator both generate domain IDs | Make API transport-only and assert ownership in contract tests. |
| State and outbox diverge | Require ADR-0006 to prove transactional writes and recovery behavior. |
| A result is published twice after restart | Persist stable result `message_id`; Orchestrator inbox deduplicates it. |
| Configured Agent is unavailable | Reject new submissions before workflow creation; if an accepted workflow already exists, bound processing and fail it at `task_result_deadline`; dynamic availability is deferred. |
| Dead-letter behavior leaks transport assumptions | Define it in ADR-0005 and test the selected adapter without a generic domain event. |
| Persistence candidate cannot satisfy source-of-truth requirements | Evaluate against Section 12 and treat relational storage as a strong candidate. |
| Local authorization is mistaken for production identity | Name and scope `LocalDevelopmentAuthorizationPolicy`; bind only locally. |
| Scope expands into platform hardening | Enforce Sections 3, 17, 18, and 19 during review. |

## 21. Open Questions

1. Which runtime language and development toolchain will ADR-0003 accept?
2. Which API protocol, representation, schema format, identifier encoding, and
   error model will ADR-0004 accept?
3. Which Event Bus and topology will ADR-0005 accept?
4. How many consumer processing attempts are allowed, and what dead-letter
   mechanism does the selected bus support?
5. Which persistence technology and transactional outbox design will ADR-0006
   accept?
6. How are Orchestrator and Test Agent data isolated in the selected store?
7. Is a separate local-container-topology ADR required?
8. What is the `request_id` idempotency retention period?
9. What duration should `task_result_deadline` use?
10. How long are inbox, outbox, receipt, result, transition, and dead-letter
    records retained?
11. How does the configuration-backed Registry evaluate current Test Agent
    readiness at submission time without becoming dynamic discovery?
12. Does configuration-backed registration satisfy ADR-0002's requirement that
    Agents register manifests and availability, or is a follow-up clarification
    required?
13. What future mechanism replaces `LocalDevelopmentAuthorizationPolicy` for
    external access?

## 22. Required ADRs

Do not implement the corresponding phase until its ADR is Accepted.

### `ADR-0003-runtime-and-development-tooling.md`

Title: **Runtime and Development Tooling**

Decide:

- language;
- package and lockfile tooling;
- supported runtime;
- formatting;
- linting;
- typing; and
- test conventions.

### `ADR-0004-api-and-contract-standards.md`

Title: **API and Contract Standards**

Decide:

- API protocol;
- representation;
- schema format;
- compatibility;
- identifier encoding; and
- error model.

### `ADR-0005-event-bus.md`

Title: **Event Bus**

Decide:

- Event Bus technology;
- topics or routing;
- workflow partitioning;
- acknowledgements;
- transport retries;
- dead-letter behavior; and
- local retention and durability.

### `ADR-0006-workflow-persistence.md`

Title: **Workflow Persistence**

Decide:

- durable store;
- transactions;
- outbox;
- Orchestrator inbox and Test Agent receipt model;
- concurrency protection;
- recovery queries;
- retention; and
- logical access separation.

### Optional Local-Container-Topology ADR

Create a separate ADR only if accepted ADR-0001 and the preceding decisions do
not sufficiently cover local orchestration, deployment units, networks,
volumes, startup dependencies, image strategy, and Unraid portability.

This plan does not create or accept any ADR.

## 23. Definition of Done

Vertical Slice 01 is done when:

- ADR-0003 through ADR-0006 are Accepted and any required topology ADR is
  Accepted;
- Phases 1 through 8 are complete in focused reviewed commits;
- only the five persisted workflow states exist;
- every workflow has one `task_id` and one `task_attempt_id`;
- only the command and two result contracts in Section 9 are implemented;
- the Workflow API delegates all domain identifier creation;
- persistence, Event Bus, configuration, and authorization remain behind
  explicit contracts;
- all no-infrastructure and local-infrastructure tests pass;
- success, terminal failure, duplicate delivery, and both restart paths are
  demonstrated;
- completed and failed workflows remain queryable after restart;
- structured logs provide end-to-end correlation and causation evidence;
- the local Docker procedure is reproducible from a clean checkout;
- no secret is committed or logged;
- no exactly-once or production-readiness claim is made;
- all deferred features remain absent; and
- documentation describes only tested behavior.
