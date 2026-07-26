# Vertical Slice 01: Deterministic Single-Agent Workflow

- **Status:** Implementation plan
- **Implementation status:** Not started
- **Source of truth:** Accepted ADR-0001 and ADR-0002

## 1. Purpose

This plan defines the smallest end-to-end workflow that can demonstrate the
core AI Platform architecture without calling an AI model.

The slice accepts text, creates and durably tracks one workflow, selects one
compatible Test Agent, dispatches one asynchronous task, and returns a
deterministic result containing:

- the original text;
- a word count; and
- the timestamp at which the Test Agent first completed processing.

The slice proves component boundaries, contracts, at-least-once delivery,
idempotency, recovery, capability discovery, and traceability. It is not a
production deployment plan.

This document is subordinate to:

- [ADR-0001: Core Design Principles](../architecture/decisions/ADR-0001-core-design-principles.md);
- [ADR-0002: Platform Communication and State](../architecture/decisions/ADR-0002-platform-communication-and-state.md);
- the [platform architecture](../architecture/README.md);
- the [test strategy](../testing/README.md); and
- the repository [security policy](../../SECURITY.md).

## 2. Scope

The slice contains only these logical responsibilities:

- **Workflow API** — submit a workflow and query its current state and result.
- **Orchestrator** — validate requests, own workflow state and transitions,
  select an Agent, dispatch work, consume results, and recover incomplete work.
- **Workflow State Store** — durably persist workflow-owned state through an
  explicit state contract.
- **Event Bus** — deliver asynchronous commands, facts, results, and lifecycle
  events with at-least-once semantics.
- **Capability Registry** — an Orchestrator-owned logical registry populated by
  Test Agent startup announcements and availability reports.
- **One Test Agent** — perform a deterministic word-count task without an LLM.
- **Shared contracts** — versioned API, event-envelope, task, result, and
  capability-manifest contracts.
- **Configuration** — explicit local settings with secrets kept outside source
  control.
- **Logging and basic observability** — structured logs, correlation fields,
  health checks, and minimal metrics.
- **Local Docker-based deployment** — independently runnable local components
  using an orchestration mechanism that remains to be accepted.
- **Automated tests** — local tests and local-infrastructure tests required by
  this plan.

The Workflow API, Orchestrator, and Capability Registry may share one
deployable process in this slice while remaining separate logical modules. The
Test Agent remains a separate consumer process so the asynchronous boundary is
real.

## 3. Out of Scope

The following are intentionally excluded:

- the AI Router;
- LLM or external AI provider calls;
- LangGraph or any other orchestration framework unless separately accepted;
- multiple Agents or multi-step workflows;
- general-purpose Skills;
- a frontend;
- public internet exposure;
- enterprise identity, single sign-on, or multi-tenancy;
- production high availability, autoscaling, or multi-host deployment;
- global message ordering;
- exactly-once delivery claims;
- a generic event-sourcing platform;
- blind replay of commands or irreversible side effects;
- a graphical dead-letter administration interface;
- an external logging, metrics, or tracing stack;
- continuous-integration automation; and
- deployment to a production Unraid environment.

Cancellation is represented in the state model but no public cancellation API
is included in this slice.

## 4. Assumptions

The plan uses the following explicit assumptions:

1. ADR-0001 and ADR-0002 remain Accepted and govern implementation.
2. The Test Agent supports exactly one capability,
   `text.word-count`, at capability version `1.0`.
3. A workflow contains exactly one task and selects exactly one compatible
   Agent instance.
4. Word count means the number of nonempty text segments separated by Unicode
   whitespace. The original text is returned unchanged.
5. Workflow input is synthetic local-development data. No confidential,
   personal, regulated, or production data is used.
6. The Workflow API is local-only. Authorization is represented by a replaceable
   boundary and a deny-by-default placeholder, not by an identity service.
7. The local deployment has durable storage across individual process or
   container restarts.
8. The Event Bus can durably retain messages required to complete local
   restart-recovery tests.
9. One physical durable state capability may host multiple logically isolated
   namespaces for the slice. The Orchestrator alone owns workflow state; the
   Test Agent may own only its task-processing receipt and result records.
10. A transactional outbox/inbox approach is the provisional consistency
    pattern. It requires acceptance as part of the state technology and
    consistency ADR before implementation.
11. The provisional API examples in this plan use request and query operations
    with an HTTP-style mapping. The final protocol, representation, and
    framework remain unresolved.
12. Retry counts, stale-task deadlines, retention, and identifier encoding are
    configurable working defaults until the relevant ADRs accept them.

Assumptions 9 through 12 are not new accepted architecture decisions.

## 5. Architecture Overview

The minimum logical flow is:

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
       state contract         | asynchronous contracts
                  |          |
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

The diagram describes logical boundaries, not accepted technologies.

The smallest proposed local deployment has four runtime units:

1. a platform service containing the Workflow API, Orchestrator, Capability
   Registry, and Orchestrator background workers;
2. the Test Agent;
3. the Event Bus implementation; and
4. the durable state implementation.

Structured logs are written by the platform service and Test Agent to their
standard process output. No separate observability service is introduced.

### Boundary Rules

- Only the Orchestrator mutates workflow state.
- The Test Agent cannot read or update workflow records.
- The Orchestrator and Test Agent depend on ports owned by the platform, not on
  implementation-specific bus or store interfaces.
- Workflow API operations call the Orchestrator within the platform service.
- Task collaboration crosses the Event Bus.
- Agent processing receipts use a logically isolated state contract and cannot
  grant access to workflow state.
- The AI Router is not built, configured, or invoked.

## 6. End-to-End Sequence

### Bootstrap

1. The durable state capability and Event Bus become ready.
2. The platform service starts, validates configuration, restores durable
   workflow and outbox state, and starts recovery workers.
3. The Test Agent starts, validates its manifest, and connects to the Event
   Bus and its isolated processing-receipt state.
4. The Test Agent publishes `AgentCapabilityAnnounced`.
5. The Orchestrator validates the manifest and upserts it into the Capability
   Registry.
6. The Test Agent periodically publishes `AgentHeartbeat`. A registration
   becomes unavailable after its configured freshness deadline.

### Workflow Execution

1. A caller submits text and requests capability `text.word-count` version
   `1.0`.
2. The Workflow API validates request shape and size, creates `workflow_id` and
   `correlation_id`, and delegates to the Orchestrator.
3. The Orchestrator atomically persists the workflow as `RECEIVED`, records the
   initial transition, and adds `WorkflowRequested` to its outbox.
4. The Orchestrator performs domain validation and transitions the workflow to
   `VALIDATED`, then `PENDING`.
5. The Capability Registry selects one healthy, available Agent compatible
   with the requested capability and contract version.
6. The Orchestrator creates `task_id`, records the selected Agent and attempt,
   and atomically adds an `ExecuteWordCountTask` command to its outbox while
   moving the workflow to `DISPATCHED`.
7. The outbox publisher publishes the command to the Event Bus with
   `partition_key = workflow_id`.
8. The Event Bus delivers the command to the Test Agent at least once.
9. The Test Agent validates the envelope, contract version, capability,
   authorization placeholder, and payload.
10. The Test Agent checks its durable receipt ledger using `task_id`. If a
    completed result already exists, it republishes the stored result with its
    original result `message_id`.
11. For first processing, the Test Agent records `TaskStarted`, computes the
    deterministic word count, captures one processing timestamp, and atomically
    stores the result and result-outbox entry.
12. The Test Agent publishes `TaskStarted` and either `TaskCompleted` or
    `TaskFailed`.
13. The Orchestrator deduplicates each message, validates its correlation and
    task ownership, and applies the permitted workflow transition.
14. On success, it persists the result and transitions to `COMPLETED`. On a
    terminal or exhausted failure, it transitions to `FAILED`.
15. The Orchestrator publishes `WorkflowCompleted` or `WorkflowFailed` from
    its outbox for audit and future consumers.
16. The caller queries the Workflow API and receives the durable workflow
    status, result or failure, and correlation identifier.

## 7. Component Responsibilities

### Workflow API

- Accept a local workflow-submission request.
- Enforce request shape, text size, and supported capability syntax.
- Return a nonblocking acknowledgement containing `workflow_id`,
  `correlation_id`, and initial state.
- Return a durable workflow snapshot by `workflow_id`.
- Map domain errors to stable API errors without leaking internals.
- Propagate request and correlation context to logs.
- Expose authorization hooks that deny nonlocal or unauthorized access when
  future external access is introduced.

Provisional logical operations:

| Operation | Request | Response |
| --- | --- | --- |
| `SubmitWorkflow` | text, capability name, capability version, optional caller request ID | workflow ID, correlation ID, current state |
| `GetWorkflow` | workflow ID | state, task summary, result or failure, timestamps, correlation ID |

An HTTP-style implementation may map these to `POST /workflows` and
`GET /workflows/{workflow_id}`, but that mapping is not accepted until the API
contract decision is made.

### Orchestrator

- Own the workflow and task domain models.
- Generate and validate stable identifiers.
- Own every workflow transition.
- Persist workflow state through a versioned state-store port.
- Own the Capability Registry and Agent selection policy.
- Create task attempts and Event Bus commands.
- Maintain durable inbox and outbox records.
- Consume task lifecycle and result messages idempotently.
- Apply retry, stale-task, dead-letter, and terminal-failure policy.
- Recover incomplete workflows after restart.
- Publish terminal workflow facts.

### Workflow State Store

- Provide durable storage through an explicit, versioned port.
- Support atomic writes required for state transitions, inbox entries, and
  outbox entries.
- Support optimistic concurrency or an equivalent lost-update safeguard.
- Support indexed lookup by workflow, task, message, and recovery deadline.
- Preserve data across process and container restarts.
- Keep infrastructure-specific details out of domain contracts.

Infrastructure provisions the capability. The Orchestrator owns workflow
schemas and transitions.

### Event Bus

- Deliver asynchronous commands, facts, results, and lifecycle events.
- Provide at-least-once delivery.
- Preserve stable message identity on transport redelivery.
- Partition workflow messages by `workflow_id`.
- Support bounded consumer retries and dead-letter handling.
- Expose acknowledgements and delivery metadata through the platform port.
- Retain enough durable state for local restart and recovery tests.
- Make delivery attempts, lag or backlog, and dead-letter outcomes observable.

### Capability Registry

- Live inside the Orchestrator boundary for this slice.
- Validate and store versioned Agent manifests.
- Track instance availability, health, and last-seen time.
- Select one compatible Agent deterministically.
- Mark stale registrations unavailable.
- Reject incompatible or unauthorized announcements.
- Rebuild its active view from durable registrations and fresh announcements
  after restart.

When multiple compatible Agents exist in tests, selection uses a stable
ordering by `agent_id` and then `instance_id`. Load balancing is out of scope.

### Test Agent

- Publish its capability manifest and availability at startup.
- Renew availability with a heartbeat.
- Consume only compatible `ExecuteWordCountTask` commands.
- Validate all untrusted envelope and payload fields.
- Keep a durable receipt/result record keyed by `task_id`.
- Compute word count deterministically.
- Store the first processing timestamp and reuse it for duplicate commands.
- Publish `TaskStarted` and one stable success or failure result.
- Never call an LLM or the AI Router.
- Support a test-only, local configuration mode for deterministic failure
  injection without accepting a failure instruction from workflow input.

### Shared Contracts

- Define API requests and responses.
- Define the event envelope and each message payload.
- Define capability manifests.
- Define workflow and task identifiers and state values.
- Define compatibility and validation rules.
- Remain independent from transport, persistence, and web frameworks.

### Configuration and Logging

- Load environment-specific values outside domain code.
- Validate required settings at startup.
- Provide committed example configuration with nonfunctional placeholders.
- Keep secrets outside source control and logs.
- Emit structured logs using the common fields in this plan.

## 8. Workflow State Model

### States

| State | Meaning |
| --- | --- |
| `RECEIVED` | The request and identifiers have been durably created. |
| `VALIDATED` | Domain validation has succeeded. |
| `PENDING` | The workflow is waiting for a compatible Agent or dispatch attempt. |
| `DISPATCHED` | A task command is durably recorded in the outbox. |
| `RUNNING` | The selected Agent has reported that task processing started. |
| `COMPLETED` | A valid success result has been durably accepted. |
| `FAILED` | Validation, dispatch, processing, or retry policy ended terminally. |
| `CANCELLED` | The Orchestrator has applied an authorized cancellation. |

`COMPLETED`, `FAILED`, and `CANCELLED` are terminal.

### Transition Ownership

Only the Orchestrator applies workflow transitions. The Workflow API requests
creation or query operations; Agent messages provide facts and results that the
Orchestrator evaluates.

| From | To | Trigger | Owner |
| --- | --- | --- | --- |
| none | `RECEIVED` | Valid API request shape and durable creation | Orchestrator |
| `RECEIVED` | `VALIDATED` | Domain validation succeeds | Orchestrator |
| `RECEIVED` | `FAILED` | Domain validation fails | Orchestrator |
| `VALIDATED` | `PENDING` | Task requirement is created | Orchestrator |
| `PENDING` | `DISPATCHED` | Agent selected and command stored in outbox | Orchestrator |
| `DISPATCHED` | `RUNNING` | Valid `TaskStarted` fact | Orchestrator |
| `DISPATCHED` or `RUNNING` | `PENDING` | Retryable failure or stale attempt with budget remaining | Orchestrator |
| `DISPATCHED` or `RUNNING` | `COMPLETED` | Valid `TaskCompleted` result | Orchestrator |
| Any nonterminal state | `FAILED` | Terminal error or retry exhaustion | Orchestrator |
| Any nonterminal state | `CANCELLED` | Authorized cancellation | Orchestrator |

A late or duplicate message cannot move a terminal workflow. It is recorded as
duplicate or stale processing evidence.

### Task Attempts

The workflow has one stable `task_id`. Each application-level retry creates a
new task-attempt record and a new dispatch command `message_id`, while retaining
the same `workflow_id`, `task_id`, and `correlation_id`.

Transport redelivery is not a new task attempt. It reuses the original
`message_id`.

## 9. Commands and Events

### Classification

- A **command** asks one eligible consumer to perform work.
- A **fact** states that something has already happened.
- A **result** reports the outcome of a command.
- A **lifecycle event** reports platform availability or delivery state.

### Minimum Message Set

| Message | Kind | Producer | Consumer | Purpose |
| --- | --- | --- | --- | --- |
| `AgentCapabilityAnnounced` | Lifecycle event | Test Agent | Orchestrator | Upsert the versioned manifest and current availability. |
| `AgentHeartbeat` | Lifecycle event | Test Agent | Orchestrator | Refresh availability and health before the registration becomes stale. |
| `WorkflowRequested` | Fact | Orchestrator | Audit/future consumers | Record that a workflow was durably accepted. |
| `ExecuteWordCountTask` | Command | Orchestrator | Compatible Test Agent | Request deterministic word-count processing. |
| `TaskStarted` | Fact | Test Agent | Orchestrator | Record that processing began and establish the attempt lease. |
| `TaskCompleted` | Result | Test Agent | Orchestrator | Return original text, word count, and stable processing timestamp. |
| `TaskFailed` | Result | Test Agent | Orchestrator | Return a safe error code, retryability, and failure timestamp. |
| `MessageDeadLettered` | Lifecycle event | Event Bus adapter | Orchestrator | Report exhausted message processing for reconciliation. |
| `WorkflowCompleted` | Fact | Orchestrator | Audit/future consumers | Record terminal successful workflow state. |
| `WorkflowFailed` | Fact | Orchestrator | Audit/future consumers | Record terminal failed workflow state. |

`TaskAccepted` is omitted because `TaskStarted` is sufficient to move the
single task to `RUNNING`. It can be introduced later only if queueing and
processing acceptance need separate semantics.

### Task Payloads

`ExecuteWordCountTask` contains:

- capability name and version;
- original text;
- task-attempt number;
- selected Agent identifier and instance identifier; and
- a processing deadline.

`TaskCompleted` contains:

- original text;
- word count;
- processing timestamp captured once;
- Agent identifier and version;
- capability name and version; and
- task-attempt number.

`TaskFailed` contains:

- stable safe error code;
- sanitized error summary;
- retryable flag;
- failure timestamp;
- Agent identifier and version; and
- task-attempt number.

Stack traces and secrets are excluded from shared messages.

## 10. Event-Envelope Proposal

The event envelope is a versioned platform contract independent of the Event
Bus implementation.

| Field | Required | Purpose and lifecycle |
| --- | --- | --- |
| `message_id` | Yes | Globally unique identity created once by the producer. It remains unchanged during transport redelivery. |
| `event_type` | Yes | Stable contract name such as `TaskCompleted`. It applies to commands, facts, results, and lifecycle events. |
| `message_kind` | Yes | One of `command`, `fact`, `result`, or `lifecycle`. |
| `contract_version` | Yes | Version of the envelope and payload contract used for compatibility validation. |
| `occurred_at` | Yes | UTC timestamp when the producer created the message. |
| `producer` | Yes | Logical producing component and instance identity. |
| `workflow_id` | Workflow messages | Stable identity of the workflow from creation through retention expiry. |
| `task_id` | Task messages | Stable identity of the logical task across application retries. |
| `correlation_id` | Yes | End-to-end trace identity. For the slice it is generated at submission and normally equals the workflow correlation context. |
| `causation_id` | Except root facts | `message_id` of the message that directly caused this message. The initial API-created fact references a request ID or is null. |
| `partition_key` | Workflow messages | Set to `workflow_id` to provide workflow-scoped ordering. |
| `capability_name` | Capability/task messages | Stable semantic capability name, initially `text.word-count`. |
| `capability_version` | Capability/task messages | Requested or executed capability version. |
| `payload` | Yes | Contract-specific validated data. |

### Identifier Rules

- `workflow_id` is generated once by the Orchestrator and never reused.
- `task_id` is generated once for the workflow's logical task and remains
  stable across retries.
- `message_id` is generated for one logical publication and remains stable
  across transport retries and Agent result republication.
- `correlation_id` spans the API request, workflow, task, all messages, logs,
  and query result.
- `causation_id` changes at each causal step and forms an auditable chain.
- Capability name and version identify behavior independently from Agent
  identity.
- Contract version identifies message representation independently from
  capability version.

Identifiers are opaque strings at module boundaries. Their concrete generation
and encoding require a contract decision. Logs and APIs must not require
callers to infer meaning from their format.

The provisional contract version is `1.0`, with major changes reserved for
breaking compatibility and minor changes limited to documented additive
evolution. This convention must be confirmed in the contract ADR.

## 11. Capability Manifest Proposal

The Test Agent announces this logical manifest at startup and renews its
availability separately.

| Field | Required | Initial meaning |
| --- | --- | --- |
| `manifest_version` | Yes | Version of the manifest contract. |
| `agent_id` | Yes | Stable logical Agent identity across deployments. |
| `instance_id` | Yes | Identity of the current running instance. |
| `agent_version` | Yes | Version of the Agent implementation. |
| `capabilities` | Yes | List of supported capability names and versions. |
| `accepted_contract_versions` | Yes | Command envelope and payload versions the Agent can consume. |
| `produced_contract_versions` | Yes | Result and lifecycle versions the Agent can produce. |
| `availability` | Yes | `AVAILABLE`, `DRAINING`, or `UNAVAILABLE`. |
| `health_status` | Yes | `HEALTHY`, `DEGRADED`, `UNHEALTHY`, or `UNKNOWN`. |
| `announced_at` | Yes | UTC time of this announcement. |
| `fresh_until` | Yes | Time after which the Registry treats availability as stale. |

The initial capability entry contains:

- capability name `text.word-count`;
- capability version `1.0`;
- accepted command `ExecuteWordCountTask` contract version `1.0`; and
- produced `TaskStarted`, `TaskCompleted`, and `TaskFailed` contract versions
  `1.0`.

Registration is descriptive, not authorization. The Orchestrator separately
checks whether the Agent identity is allowed to register and whether it is
eligible for selection.

## 12. Persistence Model

The durable state capability is the source of truth for workflow execution
state. Events provide communication, audit evidence, and recovery inputs; they
do not replace the authoritative workflow snapshot in this slice.

### Logical Records

| Record | Owner | Purpose |
| --- | --- | --- |
| Workflow | Orchestrator | Input, required capability, state, result or failure, timestamps, revision, and correlation ID. |
| Task | Orchestrator | Stable task ID, selected Agent, current attempt, deadline, and outcome reference. |
| Task attempt | Orchestrator | Attempt number, dispatch message ID, status, timestamps, failure, and retry decision. |
| Workflow transition | Orchestrator | Append-only audit of previous state, new state, cause, actor, and timestamp. |
| Orchestrator inbox | Orchestrator | Processed message ID, outcome, and retention deadline for deduplication. |
| Orchestrator outbox | Orchestrator | Message envelope, publication status, attempts, and timestamps. |
| Capability registration | Orchestrator | Manifest, instance availability, health, and freshness deadline. |
| Agent task receipt | Test Agent | Task ID, command message ID, first processing timestamp, stable result, and result message ID. |
| Agent outbox | Test Agent | Stable lifecycle or result message awaiting publication. |
| Dead-letter metadata | Responsible consumer/operations | Original message reference, attempts, safe error context, disposition, and timestamps. |

Workflow records and Agent receipt records may share one physical store in the
slice only if access is logically isolated and least-privilege credentials
prevent the Agent from reading or changing workflow records.

### Consistency

- Workflow transition, inbox acknowledgement, and resulting outbox messages are
  committed atomically from the Orchestrator's perspective.
- Agent receipt/result and Agent result-outbox entry are committed atomically
  from the Test Agent's perspective.
- An outbox worker may publish the same envelope more than once; stable
  `message_id` and inbox deduplication make this safe.
- Optimistic concurrency or an equivalent revision check prevents two recovery
  workers from advancing the same workflow concurrently.

The selected state technology must prove these properties before Phase 2.

### Audit Retention

The slice retains:

- current workflow and task snapshots;
- workflow transition history;
- task-attempt history;
- inbox deduplication records for at least the maximum redelivery and recovery
  window;
- outbox publication history;
- capability announcements used for selection;
- dead-letter metadata and disposition; and
- structured logs for the documented local retention window.

The final durations and treatment of raw workflow text remain open. Test data
must be synthetic, and retention must be configurable.

## 13. Retry, Deduplication, and Recovery Behavior

### Transport Delivery

- Delivery is at least once.
- Transport redelivery retains the original `message_id`.
- Each consumer validates before processing.
- A consumer records a durable inbox or receipt before acknowledging success.
- The working default is three bounded processing attempts with bounded delay.
- Exhaustion moves the original message and safe failure context to
  dead-letter handling.
- The exact retry delays and dead-letter representation require the Event Bus
  ADR.

### Workflow Task Retry

- The working default is two total task attempts: one initial attempt and one
  application-level retry.
- A retryable `TaskFailed`, dead-lettered task command, or stale task consumes
  one attempt from this budget.
- A new application attempt uses the same `workflow_id`, `task_id`, and
  `correlation_id`, but a new dispatch `message_id`.
- A nonretryable failure or exhausted task budget transitions the workflow to
  `FAILED`.
- Retry policy is configuration, validated at startup, and recorded with the
  task attempt.

Transport attempts and application-level task attempts are separate counters.

### Duplicate Detection

- The Orchestrator inbox deduplicates by consumer identity and `message_id`.
- The Test Agent receipt ledger deduplicates by `task_id` and verifies that a
  duplicate command is contract-compatible with the original.
- A duplicate command after completion republishes the stored result with the
  original result `message_id` and processing timestamp.
- A second valid result for an already terminal task cannot create another
  workflow result or transition.
- Conflicting duplicates are rejected, logged, and dead-lettered or quarantined
  according to the accepted bus policy.

### Ordering

- `workflow_id` is the partition key for all workflow and task messages.
- Ordering is assumed only inside that partition.
- Consumers still validate current state and version because late messages can
  arrive after retries or recovery.
- No component assumes a global order across workflows.

### Restart Recovery

On platform-service restart, the Orchestrator:

1. reloads nonterminal workflows and outbox backlog;
2. resumes unpublished outbox records;
3. rehydrates the Capability Registry from durable records;
4. waits for fresh Agent availability before new selection;
5. scans `DISPATCHED` and `RUNNING` attempts for stale deadlines; and
6. retries or fails each stale attempt according to the recorded budget.

On Test Agent restart, the Agent:

1. reloads unacknowledged task receipts and result-outbox records;
2. republishes stored results that may not have been delivered;
3. resumes consuming after its state and Event Bus dependencies are ready; and
4. announces a fresh manifest and availability.

### Stale Tasks

- `DISPATCHED` tasks have a configurable start deadline.
- `RUNNING` tasks have a configurable completion lease.
- The Orchestrator recovery worker uses durable deadlines, not process-local
  timers, as the source of truth.
- A stale attempt is closed once through revision-checked transition logic.
- A remaining task budget returns the workflow to `PENDING`; otherwise it
  becomes `FAILED`.

### Replay Safety

The word-count task is deterministic and has no external irreversible side
effect. Even so:

- generic command replay is not implemented;
- fact replay, if introduced for rebuilding a projection, is separate from
  command dispatch;
- terminal workflow transitions remain idempotent; and
- future side-effecting Agents require explicit replay guards and human
  approval where mandated by `SECURITY.md`.

## 14. Security Considerations

### Input and Contract Validation

- Limit workflow text length and reject missing, malformed, or unsupported
  input before dispatch.
- Validate every API payload, event envelope, capability manifest, and result
  against its versioned contract.
- Treat API input, event payloads, logs, and Agent output as untrusted.
- Reject unknown required fields, unsupported contract versions, invalid
  identifiers, and mismatched workflow/task relationships according to the
  contract policy.
- Return stable safe error codes; keep internal exceptions out of API and event
  payloads.

### Configuration and Secrets

- Keep environment configuration outside domain logic.
- Commit only example configuration with nonfunctional placeholder values.
- Do not commit credentials, tokens, passwords, private keys, or machine-local
  Unraid configuration.
- Do not place secrets in workflow input, event payloads, logs, test fixtures,
  images, or state snapshots.
- The slice requires no external AI provider credential.

### Least Privilege

- The Workflow API can request Orchestrator operations but cannot write the
  state store directly.
- The Orchestrator can access workflow, registry, inbox, and outbox records.
- The Test Agent can access only its own receipt and outbox records.
- Event Bus publishers and consumers receive only the subjects or routes needed
  for their contracts.
- Local containers run without elevated privilege unless a separately
  documented requirement proves it necessary.

### Authorization Placeholders

- The API boundary exposes an authorization interface with a local-development
  policy.
- Agent registration and task consumption verify configured logical identities.
- A manifest announcement does not grant Agent authorization.
- External authentication infrastructure is deferred and must replace, not
  bypass, the authorization interface.

### Prompt Injection and Untrusted Content

No LLM is present, but text and event payloads remain untrusted data:

- the Test Agent treats text only as text and never as instructions;
- input is never evaluated as code or a command;
- logs encode fields rather than interpolate executable content;
- test fixtures include malicious-looking text to prove it remains inert; and
- model-oriented prompt-injection controls remain out of scope until an AI
  boundary is introduced.

The slice performs no destructive or irreversible action. Any future such
action requires explicit human approval immediately before execution.

## 15. Observability Requirements

### Structured Logging

Every component log entry uses structured fields. Required common fields are:

| Field | Requirement |
| --- | --- |
| `timestamp` | UTC event time |
| `level` | Log severity |
| `component` | Logical component name |
| `instance_id` | Running instance identity |
| `environment` | Local environment name |
| `workflow_id` | Present for workflow-related activity |
| `task_id` | Present for task-related activity |
| `message_id` | Present for message publication or processing |
| `correlation_id` | Present across the complete workflow |
| `causation_id` | Present when activity was caused by a message |
| `event_type` | Message or lifecycle contract name |
| `contract_version` | Contract version used |
| `processing_outcome` | `started`, `succeeded`, `failed`, `retried`, `duplicate`, `dead_lettered`, or `ignored` |
| `duration_ms` | Present for completed operations |
| `attempt` | Transport or task-attempt context, explicitly labeled |
| `error_code` | Safe stable code for failures |

Logs must not contain secrets or unsanitized full exception payloads. Logging
the original workflow text is disabled by default.

### Health Checks

Minimum checks are:

- **Platform service liveness** — process event loop is responsive.
- **Platform service readiness** — configuration valid, state contract
  reachable, Event Bus publisher/consumer ready, and recovery worker started.
- **Test Agent liveness** — process event loop is responsive.
- **Test Agent readiness** — configuration and manifest valid, receipt state
  reachable, Event Bus consumer ready, and current availability announced.
- **Event Bus health** — local deployment confirms the service is accepting
  connections and durable operations.
- **State health** — local deployment confirms read/write capability without
  exposing stored data.

No readiness check claims that an entire external dependency ecosystem is
healthy.

### Minimum Metrics

Logical metrics required for the slice:

- workflows submitted, completed, failed, and currently nonterminal;
- workflow end-to-end duration;
- tasks dispatched, started, completed, failed, retried, and stale;
- task processing duration;
- messages published, consumed, duplicated, retried, and dead-lettered;
- inbox and outbox backlog;
- available and stale Agent registrations;
- recovery scans and recovered workflows; and
- API requests by operation, outcome, and duration.

Metric names, export format, and monitoring backend are not selected. The
implementation must expose or log these measurements in a testable way without
adding a monitoring service to the slice.

## 16. Proposed Repository Structure

No directories are created by this planning task. The smallest proposed
implementation layout uses one source root and reuses existing top-level
documentation and infrastructure boundaries:

```text
.
├── src/
│   └── platform/
│       ├── api/
│       ├── orchestrator/
│       │   ├── workflow/
│       │   └── capability_registry/
│       ├── agents/
│       │   └── test_agent/
│       ├── contracts/
│       │   ├── api/
│       │   ├── events/
│       │   └── capabilities/
│       ├── ports/
│       │   ├── event_bus/
│       │   └── state_store/
│       ├── adapters/
│       │   ├── event_bus/
│       │   └── state_store/
│       └── shared/
│           ├── configuration/
│           └── logging/
├── tests/
│   ├── unit/
│   ├── component/
│   ├── contract/
│   ├── workflow/
│   ├── integration/
│   ├── resilience/
│   ├── security/
│   ├── end_to_end/
│   └── infrastructure/
├── infrastructure/
│   └── local/
└── docs/
    └── implementation/
        └── vertical-slice-01.md
```

The language ADR determines package metadata and concrete filenames.
Executable source does not go into new top-level `api/`, `orchestrator/`, or
`event-bus/` directories.

The existing top-level `agents/` directory remains reserved for durable Agent
definitions and metadata. The executable Test Agent belongs under the common
source root; a reusable manifest may later be published under `agents/` when
its format is accepted.

## Technology Evaluation

Only Docker-based deployment is currently accepted. The following evaluations
do not select the other technologies.

| Technology | Accepted? | Potential role | Realistic alternatives | ADR recommendation |
| --- | --- | --- | --- | --- |
| Python | No | Primary service language, domain models, adapters, and tests | TypeScript; Go | Required before Phase 1 because it determines packaging, tooling, runtime, and source conventions. |
| LangGraph | No | Orchestration graph and state-transition implementation | Explicit application state machine; durable workflow engine | Defer for this slice. An ADR is required before adoption because it would become a core Orchestrator dependency. Omitting it does not require introducing another framework. |
| Kafka | No | Durable partitioned Event Bus with retry and dead-letter topology | RabbitMQ; NATS JetStream | Required before the real Event Bus adapter and local infrastructure phases. |
| Redis | No | Candidate durable state, deduplication, outbox, and Capability Registry backing capability | PostgreSQL; a document-oriented database | Required before persistence implementation. The decision must prove durability, atomicity, concurrency, query, retention, and recovery requirements. |
| Docker | Yes, in ADR-0001 | Package deployable components and support Unraid operation | Not reevaluated in this slice | No new ADR for the container principle; topology and image strategy remain unresolved. |
| Docker Compose | No | Start the local multi-container stack, networks, volumes, configuration, and health checks | Plain Docker scripts; Podman Compose | Required before local deployment because ADR-0001 explicitly defers detailed topology and lifecycle choices. |

Additional decisions not tied to the listed technologies:

- API protocol and representation;
- event and API schema representation and compatibility tooling;
- identifier format;
- structured-log and metric export formats; and
- the exact consistency mechanism between workflow state and event publication.

No additional infrastructure service is justified until its responsibility
cannot be met by the accepted minimum components.

## 17. Testing Strategy

The slice follows the repository [test strategy](../testing/README.md).

### No-Infrastructure Local Tests

These tests run without Docker or separately running services:

- workflow state-transition unit tests, including invalid and terminal
  transitions;
- word-count determinism and input-boundary tests;
- identifier propagation tests;
- event-envelope validation tests;
- capability-manifest validation and compatibility tests;
- producer and consumer contract fixture tests;
- Orchestrator selection-policy unit tests;
- duplicate-message and terminal-result idempotency tests using controlled
  ports;
- retry-budget and stale-deadline unit tests;
- dead-letter policy unit tests;
- outbox and inbox state-machine tests using an isolated fake;
- workflow happy and failure paths using in-process ports;
- authorization-placeholder and least-privilege policy tests;
- malicious-looking input and log-redaction tests; and
- configuration validation tests.

### Local-Infrastructure Tests

These tests start and own the selected local Docker services:

- Event Bus adapter publication, consumption, acknowledgement, partition, and
  at-least-once tests;
- state adapter durability, atomicity, revision, and query tests;
- producer and consumer contract tests across the real bus adapter;
- duplicate delivery against the real Event Bus;
- bounded processing retry and dead-letter behavior;
- outbox publication across platform-service restart;
- Test Agent receipt/result republication across Agent restart;
- stale `DISPATCHED` and `RUNNING` workflow recovery;
- capability reannouncement and stale-registration recovery;
- component integration among API, Orchestrator, store, and bus;
- end-to-end happy path;
- end-to-end terminal Agent failure path;
- end-to-end retry exhaustion path;
- complete-stack health checks;
- structured-log correlation across all components; and
- local infrastructure startup, persistence, restart, and cleanup validation.

### External-Service Tests

No shared, hosted, third-party, production, or external AI service is required
for this slice. If an implementation choice introduces such a dependency, the
scope and ADRs must be revisited before the test is added.

### Required End-to-End Assertions

The happy-path test submits known text and asserts:

- a unique workflow and correlation ID are returned;
- the selected Agent is compatible and available;
- the workflow reaches `COMPLETED`;
- the original text is unchanged;
- word count matches the documented algorithm;
- processing timestamp is present and stable across duplicate delivery;
- the query API returns the durable result; and
- one correlation ID joins API, Orchestrator, Event Bus, and Agent logs.

The failure-path test uses the Test Agent's local test-only failure mode and
asserts either a retry followed by success or terminal `FAILED`, depending on
configuration. Workflow input cannot enable failure mode.

## 18. Implementation Phases

Blocking ADRs must be accepted before the corresponding implementation phase.
Each phase should produce one reviewable commit unless its tests require a
separate immediately following commit.

### Phase 1: Contracts and Shared Models

- **Goal:** Define identifiers, API contracts, event envelope, message payloads,
  capability manifest, validation rules, and compatibility fixtures.
- **Modules affected:** `src/platform/contracts/`,
  `src/platform/shared/`, `tests/unit/`, and `tests/contract/`.
- **Dependencies:** Accepted runtime/language and contract-format decisions;
  ADR-0001 and ADR-0002.
- **Tests:** Envelope validation, identifier propagation, capability
  compatibility, producer/consumer fixtures, invalid payloads, and version
  rejection.
- **Completion criteria:** Contracts are transport-neutral, versioned,
  documented, and pass all no-infrastructure contract tests.
- **Suggested commit:** `Define vertical slice contracts`

### Phase 2: Workflow State Model and Persistence Abstraction

- **Goal:** Implement Orchestrator-owned workflow/task models, transition rules,
  state-store port, inbox/outbox models, and concurrency rules.
- **Modules affected:** `src/platform/orchestrator/workflow/`,
  `src/platform/ports/state_store/`, and related unit tests.
- **Dependencies:** Phase 1 and accepted durable-state/consistency ADR.
- **Tests:** State transitions, terminal-state protection, task attempts,
  optimistic concurrency, inbox deduplication, outbox behavior, and recovery
  queries using a controlled port.
- **Completion criteria:** The domain model advances only through valid
  Orchestrator-owned transitions and is independent of storage technology.
- **Suggested commit:** `Add workflow state model and persistence port`

### Phase 3: Capability Registry

- **Goal:** Implement manifest validation, durable registration, freshness,
  health, compatibility, and deterministic Agent selection.
- **Modules affected:** `src/platform/orchestrator/capability_registry/`,
  capability contracts, and unit/component tests.
- **Dependencies:** Phases 1 and 2.
- **Tests:** Registration upsert, incompatible versions, unauthorized identity,
  stale availability, restart hydration, and deterministic selection.
- **Completion criteria:** One compatible fresh Agent can be selected without
  coupling the Orchestrator to Agent internals.
- **Suggested commit:** `Add orchestrator capability registry`

### Phase 4: Event Bus Abstraction

- **Goal:** Implement the transport-neutral Event Bus port, message handlers,
  acknowledgement model, retry/dead-letter abstractions, and outbox publisher
  interfaces.
- **Modules affected:** `src/platform/ports/event_bus/`,
  `src/platform/orchestrator/`, and contract/component tests.
- **Dependencies:** Phases 1 and 2 and accepted Event Bus ADR.
- **Tests:** Publish/consume contracts, stable redelivery identity,
  partition-key propagation, bounded retries, dead-letter callbacks, and outbox
  duplicate safety using a controlled bus.
- **Completion criteria:** Orchestrator and Agent code can exchange contracts
  without importing a concrete Event Bus implementation.
- **Suggested commit:** `Add event bus port and delivery semantics`

### Phase 5: Test Agent

- **Goal:** Implement startup capability announcements, heartbeat, deterministic
  word count, durable receipt/result handling, and success/failure publishing.
- **Modules affected:** `src/platform/agents/test_agent/`, Agent-side state
  port usage, configuration, logging, and tests.
- **Dependencies:** Phases 1 and 4, plus the Phase 2 state port or an explicitly
  separated Agent receipt port.
- **Tests:** Word count, input validation, duplicate commands, stable timestamp
  and result ID, retryable and terminal failure modes, manifest announcement,
  heartbeat, and restart result republication with controlled dependencies.
- **Completion criteria:** The Agent handles its command idempotently, publishes
  a stable result, and contains no AI Router or LLM dependency.
- **Suggested commit:** `Add deterministic word count test agent`

### Phase 6: Orchestrator

- **Goal:** Connect validation, workflow transitions, Capability Registry,
  command dispatch, result handling, retries, stale-task recovery, and terminal
  workflow facts.
- **Modules affected:** `src/platform/orchestrator/`,
  `src/platform/shared/logging/`, and workflow/component tests.
- **Dependencies:** Phases 1 through 5.
- **Tests:** Happy and failure workflows with controlled ports, duplicate and
  late results, stale attempts, task retry budget, dead-letter reconciliation,
  recovery scan, and complete correlation propagation.
- **Completion criteria:** A workflow can run from durable creation to a
  queryable terminal state using only logical ports.
- **Suggested commit:** `Implement single-task workflow orchestration`

### Phase 7: Workflow API

- **Goal:** Expose local submit and query operations with validation, stable
  errors, authorization placeholders, and structured request logging.
- **Modules affected:** `src/platform/api/`, API contracts, platform-service
  startup, and component/security tests.
- **Dependencies:** Phase 6 and accepted API protocol/representation decision.
- **Tests:** Valid submit, invalid input, unsupported capability, query found
  and not found, error sanitization, authorization placeholder, and correlation
  response.
- **Completion criteria:** A local caller can submit and query without direct
  store or Event Bus access.
- **Suggested commit:** `Add workflow submission and query API`

### Phase 8: Local Infrastructure

- **Goal:** Add concrete Event Bus and state adapters, container images, local
  orchestration, example configuration, durable volumes, health checks, and
  documented start/stop commands.
- **Modules affected:** `src/platform/adapters/`,
  `infrastructure/local/`, configuration documentation, and infrastructure
  tests.
- **Dependencies:** Phases 1 through 7 and accepted Event Bus, state, runtime,
  and local container-orchestration ADRs.
- **Tests:** Adapter integration, configuration validation, image build,
  startup/readiness, persistence across restart, least privilege, and cleanup.
- **Completion criteria:** The complete local stack starts from documented
  Docker commands with no secret committed and survives component restarts.
- **Suggested commit:** `Add local vertical slice deployment`

### Phase 9: Integration Tests

- **Goal:** Verify real adapters and component boundaries against the local
  infrastructure.
- **Modules affected:** `tests/integration/`, contract fixtures, and local test
  configuration.
- **Dependencies:** Phase 8.
- **Tests:** API/store integration, Event Bus contracts, Agent registration,
  at-least-once duplicate delivery, partition ordering, state concurrency,
  outbox/inbox behavior, and dead-letter handling.
- **Completion criteria:** Each real boundary satisfies the same conformance
  contract as its controlled test implementation.
- **Suggested commit:** `Add vertical slice integration tests`

### Phase 10: End-to-End and Recovery Tests

- **Goal:** Prove happy path, failure path, deduplication, restart recovery,
  stale-task recovery, and traceability across the local stack.
- **Modules affected:** `tests/end_to_end/`, `tests/resilience/`, test fixtures,
  and local deployment controls.
- **Dependencies:** Phase 9.
- **Tests:** All required end-to-end and recovery scenarios in Section 17.
- **Completion criteria:** Acceptance criteria are exercised automatically
  against a clean, isolated local stack and produce diagnostic evidence on
  failure.
- **Suggested commit:** `Add end-to-end workflow recovery tests`

### Phase 11: Documentation and Operational Validation

- **Goal:** Finalize local operation, troubleshooting, recovery, test, contract,
  and architecture documentation based on verified behavior.
- **Modules affected:** root and directory README files, `docs/`,
  `infrastructure/local/`, and operational validation records.
- **Dependencies:** Phases 1 through 10.
- **Tests:** Markdown links, documented-command execution, clean startup,
  health/readiness, restart, recovery, shutdown, volume cleanup, and secret
  checks.
- **Completion criteria:** Documentation describes only verified behavior and a
  new contributor can reproduce the slice from a clean checkout.
- **Suggested commit:** `Document vertical slice operation and recovery`

## 19. Acceptance Criteria

The vertical slice is accepted only when:

- a workflow can be submitted through the documented API;
- the API returns a unique `workflow_id` and `correlation_id`;
- workflow state and transition history are durably persisted;
- the Orchestrator selects one healthy, available, contract-compatible Agent;
- one task command is dispatched asynchronously through the Event Bus;
- the Test Agent returns original text, correct word count, and a stable
  processing timestamp without calling an LLM;
- at-least-once duplicate delivery does not create a duplicate result or
  terminal transition;
- a retryable failure follows the bounded task policy;
- terminal Agent failure and retry exhaustion produce a queryable `FAILED`
  workflow;
- exhausted message processing reaches dead-letter handling;
- restarted platform-service and Test Agent processes resume or recover
  incomplete work;
- stale `DISPATCHED` and `RUNNING` attempts are detected and resolved;
- a completed or failed workflow can be queried after restart;
- logs trace the flow using workflow, task, message, correlation, and causation
  identifiers;
- required health checks and logical metrics are available and tested;
- all required no-infrastructure and local-infrastructure automated tests pass;
- the local stack starts and stops through documented Docker commands;
- local persistent state survives the documented restart scenario;
- no credential or secret is committed or emitted in test evidence;
- all implementation technologies and cross-cutting choices are covered by
  Accepted ADRs; and
- documentation matches verified behavior.

## 20. Risks and Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Technology is selected before its ADR | Core coupling and rework | Block corresponding phases until the decision is Accepted. |
| Workflow state and event publication diverge | Lost or duplicate work | Require atomic state/outbox writes, stable IDs, inbox deduplication, and recovery tests. |
| At-least-once delivery duplicates results | Incorrect terminal state | Persist consumer receipts and stable results; make terminal transitions idempotent. |
| Agent availability is stale | Work is dispatched to a dead instance | Use `fresh_until`, heartbeats, readiness, and stale-registration exclusion. |
| Retry layers multiply unexpectedly | Retry storms and delayed failure | Separate transport and task attempts, bound both, and log each counter explicitly. |
| Dead-letter messages are ignored | Workflows remain stuck | Emit dead-letter evidence, monitor counts, and reconcile through stale-task recovery. |
| Process restart loses in-flight work | Workflow never completes | Durable state, inbox/outbox, Agent receipt ledger, and restart tests. |
| Test-only failure behavior becomes externally controllable | Security and correctness issue | Configure it only in isolated test deployment; never accept it from workflow input. |
| Raw text leaks through logs or events | Data exposure | Use synthetic data, validate payloads, disable text logging, and test redaction. |
| Local deployment differs from Unraid | False portability confidence | Use portable volumes/configuration and perform a later documented Unraid validation. |
| Word-count semantics differ across runtimes | Nondeterministic contract | Specify Unicode-whitespace behavior and share contract fixtures. |
| Scope expands into AI routing or production operations | Delayed proof of architecture | Enforce the out-of-scope list and require a new plan or ADR for expansion. |

## 21. Open Questions

The following questions remain unresolved:

1. Which implementation language and package tooling will be accepted?
2. Which API protocol and representation will implement submit and query?
3. Which schema representation and compatibility process will govern API and
   event contracts?
4. What opaque identifier encoding will be used?
5. Which Event Bus technology and local topology satisfy durability,
   workflow partitioning, retries, and dead-letter handling?
6. Which durable state technology satisfies atomic outbox/inbox, optimistic
   concurrency, Agent receipt isolation, query, and restart requirements?
7. What exact pattern keeps state transitions and outbox publication
   consistent for the chosen store?
8. Will LangGraph be omitted in favor of a small explicit state machine, or
   will a framework be justified by an ADR?
9. Which local Docker orchestration mechanism and image strategy will be used?
10. What are the final transport retry delays, task-attempt limit, start
    deadline, and completion lease?
11. How long are workflow input, transitions, inbox records, outbox records,
    capability history, dead-letter metadata, and logs retained?
12. How is dead-letter redelivery authorized and recorded?
13. What availability heartbeat interval and freshness window are appropriate?
14. Which structured-log and metric export formats will be used without adding
    an observability service?
15. Is the Test Agent's receipt ledger physically colocated with workflow state
    or provisioned separately?
16. What local authorization placeholder is sufficient without implying
    external security?
17. What maximum text size and API request limits apply?
18. Does `processing_timestamp` mean first task start or first successful task
    completion? This plan proposes first successful completion.

## 22. Required ADRs

ADR-0001 and ADR-0002 are already Accepted. The following decisions are
required before their affected implementation phases:

| Proposed decision | Scope | Blocks |
| --- | --- | --- |
| Runtime language and package conventions | Select the primary language, dependency/lockfile policy, package layout, supported runtime, formatting, linting, typing, and test command conventions. | Phase 1 |
| API and contract representation | Select API protocol, data representation, schema definition, compatibility rules, error model, identifier encoding, and contract-generation policy. | Phases 1 and 7 |
| Event Bus implementation and topology | Select the bus, workflow partition mapping, acknowledgement, retry, dead-letter, retention, local durability, and adapter boundaries. | Phases 4, 8, 9, and 10 |
| Durable state and consistency model | Select the store, transaction/concurrency guarantees, workflow and Agent namespace isolation, inbox/outbox pattern, retention, backup, and restart behavior. | Phases 2, 5, 8, 9, and 10 |
| Local container topology | Select Docker orchestration, deployment units, networks, volumes, health dependencies, image strategy, configuration injection, and Unraid portability. | Phase 8 |

LangGraph requires its own ADR or explicit inclusion in the runtime and
Orchestrator implementation decision before adoption. It is not required for
this slice and should remain absent unless its benefits exceed the additional
dependency and abstraction cost.

These ADRs must begin as Proposed. This plan does not accept them.

## 23. Definition of Done

The vertical slice is done when:

- every blocking ADR is Accepted through the repository process;
- Phases 1 through 11 are complete in focused, reviewed commits;
- the implementation contains only the scoped logical components;
- all API, event, state, and capability contracts are versioned and documented;
- the state model and component boundaries conform to ADR-0001 and ADR-0002;
- the AI Router, LLM calls, frontend, and external identity infrastructure are
  absent;
- all acceptance criteria in Section 19 have automated or documented
  verification evidence;
- all no-infrastructure tests pass;
- all required local-infrastructure tests pass from a clean environment;
- the local Docker deployment and restart/recovery procedure are reproducible;
- logs demonstrate complete correlation and causation across one success and
  one failure workflow;
- security and secret-handling expectations are verified;
- dead-letter records and stale workflows have a documented recovery path;
- no exactly-once or production-readiness claim is made;
- documentation describes only behavior demonstrated by the slice; and
- the repository is clean after the final validation.
