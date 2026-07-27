# ADR-0009: Observability, Telemetry, and Audit Correlation

- **Status:** Proposed
- **Date:** 2026-07-27
- **Supersedes:** None
- **Superseded by:** None

## Context

ADR-0004 defines portable request, workflow, task, attempt, message,
correlation, and causation identities. ADR-0005 selects at-least-once delivery.
ADR-0006 defines authoritative workflow, inbox, outbox, receipt, outcome, and
transition records. ADR-0007 defines Agent lifecycle evidence. ADR-0008 makes
Registry selection evidence atomic with workflow acceptance.

The platform needs coherent diagnosis without making a log service, trace
backend, or dashboard part of business correctness. Ordinary telemetry is
necessarily lossy through sampling, outage, restart, bounded buffering, and
retention. Correctness-critical audit must remain in authoritative component
persistence.

### Existing Documentation Alignments and Ambiguities

- ADR-0004 gives root `ExecuteTask` `causation_id = null` because HTTP is not a
  message. Workflow acceptance still causes command creation in durable
  transition/selection audit and tracing; this ADR does not invent a message
  cause.
- `correlation_id`, `workflow_id`, and trace ID are sometimes described
  informally as equivalent. They are distinct identities with different
  lifetimes and trust rules.
- ADR-0005 broker acknowledgment and ADR-0006 database commit are sometimes
  called "success" in operational text. Neither alone proves workflow
  completion.
- ADR-0007 and ADR-0008 define several readiness layers. A single health metric
  must not collapse process, Registry, API, capability, and deployment states.
- Existing documents require structured logs but select no exporter, storage,
  retention period, or monitoring backend. This ADR preserves that boundary.

## Decision Drivers

The decision prioritizes end-to-end asynchronous diagnosis, durable
explainability, privacy, low cardinality, bounded cost, crash/restart evidence,
multi-instance correlation, backend portability, local operation, testability,
and explicit ownership without exactly-once, global-order, or perfect-telemetry
claims.

## Decision

### 1. Observability Definition

Observability is the platform's ability to infer and diagnose internal behavior
from emitted operational signals and authoritative durable evidence. It is not
synonymous with logging, monitoring, tracing, metrics, audit, dashboards,
alerts, OpenTelemetry, Prometheus, Grafana, Elastic, Loki, Jaeger, Tempo,
Application Insights, Splunk, a table, or an Event Bus topic.

### 2. Signal Categories

| Signal | Purpose | Authority |
| --- | --- | --- |
| Structured operational logs | Discrete runtime diagnosis | Nonauthoritative and lossy |
| Metrics | Aggregate rate, latency, saturation, backlog, and failure | Nonauthoritative and aggregated |
| Distributed traces | Sampled causal execution paths | Nonauthoritative and lossy |
| Durable business audit | Explain accepted requests, selections, transitions, outcomes, and dispositions | Authoritative companion to business state |
| Security audit | Explain privileged, policy, destructive, and administrative actions | Required durable evidence where policy demands |
| Diagnostic persistence metadata | Recover transport, retry, claims, inboxes, outboxes, and failures | Authoritative for its recovery scope |

One occurrence may create several signals, but they retain separate ownership,
retention, privacy, and failure behavior. There is no generic telemetry event
stream.

### 3. Source-of-Truth Boundaries

Authoritative evidence remains:

- Orchestrator workflow current state and append-only transition history;
- accepted-request mapping for API idempotency;
- task/attempt and ADR-0008 selection intent;
- Agent completed receipt and accepted outcome;
- inbox, outbox, rejection, quarantine, and claim records for recovery; and
- required durable security/operator audit.

Logs, metrics, traces, dashboards, and external telemetry stores never decide
workflow state, idempotency, deduplication, selection, or transaction outcome.
Telemetry loss cannot change workflow correctness. A log or span is never proof
of commit; absence is never proof that work did not occur.

### 4. Correlation Identity Model

| Identity | Owner/stability | Propagation and signal use | Metric label |
| --- | --- | --- | --- |
| `request_id` | Client/API; stable after acceptance | API, workflow audit, logs/traces | No |
| `workflow_id` | Orchestrator; durable after acceptance | All workflow/task evidence and messages | No |
| `task_id` | Orchestrator; durable | Task audit/messages/logs/traces | No |
| `task_attempt_id` | Orchestrator per application attempt | Commands, outcomes, retry audit | No |
| command/event `message_id` | Producer per immutable logical message | Message, inbox/outbox, logs/traces | No |
| `correlation_id` | Validated or created by Orchestrator; stable logical correlation | Command/event chain, logs/traces/audit | No |
| `causation_id` | Message producer; immediate prior message ID or null | Portable message/audit | No |
| capability/version | Capability owner; versioned | Messages, selection, logs/traces | Yes, when bounded |
| selected `agent_id` | Deployment owner/Orchestrator selection | Command, selection audit, logs/traces | Only bounded deployment class, not arbitrary ID |
| Registry/deployment revisions | Deployment configuration | Selection audit/logs/traces | Not raw revision |
| implementation version | Release owner | Resource context/logs/traces | Yes, bounded |
| process instance | Runtime; ephemeral | Logs/traces/diagnostics | No |
| consumer identity | Adapter configuration | Inbox/transport diagnostics | Bounded logical consumer only |
| transaction classification | Persistence adapter | Logs/metrics/traces | Yes |
| inbox/outbox identity | Record owner; durable operational | Recovery audit/logs/traces | No |

Internal database keys, host IDs, and offsets are never portable identifiers.
Retry preserves identities unless ADR-0004 defines a new application attempt.

### 5. Correlation Versus Causation

Correlation groups a broader logical operation; causation names the immediate
predecessor. API acceptance creates the workflow and durable audit relationship.
The root command has no message cause. `TaskCompleted`/`TaskFailed` causation is
the command `message_id`; the terminal transition cites the accepted event or
deadline decision.

Broker republication/redelivery preserves message, correlation, causation, and
attempt identities. It creates new operational attempts, not new business
causes. Application retry creates a new `task_attempt_id` and command
`message_id` while retaining workflow correlation. Accepted API replay creates
no workflow. Correlation implies neither total order nor successful completion.

### 6. API Correlation

Before workflow creation, valid `request_id`, validated incoming trace context,
and server request/trace identity may exist. Invalid input uses only safe
transport context and any safely parsed request ID. Unavailable-Agent rejection
creates no workflow.

Acceptance atomically creates durable workflow/task/selection identities.
Equivalent replay returns stored identities and creates only a new HTTP
processing span/log. Conflict records safe request/trace context and the stable
error. Response loss after commit is resolved through `request_id`; retry
returns the existing workflow.

### 7. Message Correlation

Event Bus telemetry includes logical channel, message/contract type,
`message_id`, `correlation_id`, `causation_id`, workflow/task/attempt,
capability, target `agent_id`, producer, logical consumer, and duplicate,
redelivery, or rejection classification.

Adapters may add partition, offset, group member, delivery attempt, and broker
diagnostics to internal logs/traces. Trace context may travel in broker headers.
Headers never redefine ADR-0004 identity or enter domain payload validation.

### 8. Trace Context Propagation

The architecture adopts W3C Trace Context semantics at trusted API and
messaging adapters. Valid `traceparent` and bounded `tracestate` may propagate;
untrusted or invalid values are rejected or replaced according to adapter
policy. Baggage is not propagated initially.

Spans cover API handling, Registry/readiness, persistence, outbox publication,
message production/consumption, Agent execution, dependencies, outcome commit,
and terminal processing. Messaging producer and consumer/process spans use
links where asynchronous or repeated processing is not a strict synchronous
parent-child relationship. Domain interfaces receive only technology-neutral
diagnostic context, never SDK objects. Trace retention is not durable causality.

### 9. Trace and Domain Identity Relationship

Trace ID, span ID, `correlation_id`, `workflow_id`, `request_id`, `message_id`,
and `causation_id` remain distinct. `correlation_id` does not equal
`workflow_id`; both are durable attributes after acceptance. Before acceptance,
HTTP trace/request context supplies operational correlation.

Every publish attempt and redelivery may create a new span linked to the same
logical message context. Duplicates create distinct processing spans with the
same message/attempt attributes. Internal retries are child or sibling attempt
spans as appropriate. Restart can break trace continuity; durable identifiers
restore investigation continuity.

### 10. Structured Logging Model

Logs use machine-readable structured fields with stable event classification,
UTC timestamp, severity, component, environment, logical deployment, software
and process instance, operation, relevant durable IDs, safe error/retry class,
duration, and disposition.

Deployed components emit one structured JSON record per event to standard
output, as accepted by ADR-0003. Readable local formatting is an explicit
development option. The logical field model remains backend-neutral; exact
encoder details are implementation policy. Human text is supplementary and
never parsed as a contract. Python standard logging is the application facade;
structure/redaction is applied behind a platform boundary.

### 11. Log Event Taxonomy

Stable categories cover API acceptance/rejection/replay/conflict; workflow
transition; Registry lookup/selection; outbox lifecycle; message
receive/validate/duplicate/reject/quarantine/acknowledge; Agent
admit/start/timeout/confirmed execution cancellation/lifecycle
interruption/complete/fail; outcome/inbox commit; transaction retry/exhaustion;
readiness/drain/shutdown; schema/migration/backup/restore/cleanup; and
security/administrative action. Exact event names are deferred.

### 12. Log Severity Model

- **Debug:** bounded development detail, disabled or sampled normally.
- **Information:** expected acceptance, replay, transition, publication, normal
  duplicate resolution, and lifecycle milestones.
- **Warning:** bounded retry, stale/unavailable state, quarantine, degradation,
  or approaching capacity that needs attention.
- **Error:** failed operation, exhausted retry, persistence failure, integrity
  conflict, or lost required capability with contained scope.
- **Critical:** systemic loss of correctness, unrecoverable corruption, or
  required audit/security failure needing immediate intervention.

Severity is operational impact, not business outcome. Expected duplicates and
task failures are not automatically errors.

### 13. Metrics Model

Metrics cover API count/latency/disposition; workflows by state/age/terminal
latency; transitions; command/event production/consumption; duplicate,
redelivery, quarantine; inbox/outbox backlog and oldest age; publication
certainty; transaction latency/retry/deadlock/exhaustion; Agent concurrency,
admission, saturation, execution and dependency outcomes; Registry revision
activation, candidate/availability/staleness; pools/storage/cleanup;
liveness/readiness/drain; and backup/restore where available.

Metric names follow one reviewed platform convention; exact names and backend
are deferred.

### 14. Metric Cardinality

Request, workflow, task, attempt, message, raw `agent_id`, revision, endpoint,
process, exception, input, provider ID, and SQL values are prohibited ordinary
labels. They belong in logs, traces, and audit.

Bounded labels may include component, environment, capability/version, outcome
or error class, logical channel/message type, contract major, deployment class,
readiness class, and retry class. Every new label needs cardinality/privacy
review. Unknown/unbounded values collapse to a safe bounded classification.

### 15. Histogram and Latency Model

Distributions, not averages alone, measure API, acceptance transaction,
Registry/readiness, outbox age, transport, message processing, Agent admission
and execution, outcome commit, workflow terminal, persistence, dependency, and
shutdown-drain durations. In-process duration uses monotonic time. UTC
timestamps support cross-system diagnosis but not perfect ordering. Exact
buckets require measurement.

### 16. Workflow Observability

One workflow is reconstructed from accepted request, workflow/task/attempt and
selection records, transition history, command outbox, publication disposition,
Agent receipt/outcome/outbox, Orchestrator inbox, and final state. Logs and
traces add runtime attempts, durations, process context, and crash boundaries;
metrics show aggregate context.

Operators can explain acceptance/replay, selection, command creation and
publication, delivery/duplicate/conflict, admission/execution, outcome,
terminal processing, deadlines/late events, and recovery without one universal
telemetry store.

### 17. Persistence Observability

Observe pool utilization/wait, classified transaction duration, deadlock,
serialization/constraint/revision conflict, commit uncertainty, retry/exhaustion,
lock wait, migration/schema state, outbox claim/expiry, inbox growth, cleanup,
backup, and restore. SQL text and bind values are excluded by default.
Database-native metrics supplement but never define portable contracts.

### 18. Event Bus Observability

Observe publication attempt, broker acceptance/uncertainty, duplicate
publication, delivery/redelivery, assignment/revoke, offset acknowledgment,
lag, quarantine/poison/retry exhaustion, channel availability, group health,
rebalance, and blocked partition.

Offsets are adapter diagnostics. Lag is not workflow backlog, broker acceptance
is not domain completion, delivery is not transition, and duplicate delivery
is expected under at-least-once semantics.

### 19. Outbox and Inbox Observability

Outbox signals include backlog/oldest age, claim/age/expiry, attempts,
acknowledged/unknown publication, republication, retries, terminal operator
disposition, poison ordering, and workflow/channel blockage.

Inbox signals include receive/new/duplicate/late/reject/quarantine/conflict
disposition, commit latency, deduplication age, and cleanup eligibility.
Payloads are excluded by default.

### 20. Agent Observability

Observe command/validation/target/capability, admission/backpressure,
concurrency/partition occupancy, start/finish, deterministic recomputation,
timeout, confirmed execution-policy cancellation, lifecycle interruption,
outcome commit, stale assignment fencing, dependency/retry, drain/shutdown, and
resource-limit classification. Cancellation telemetry never claims an external
operation stopped without adapter evidence.

### 21. Registry Observability

Observe complete Registry and deployment declaration revisions, load/validation
and conflicts, Agent-loaded digest comparison, readiness route validation,
candidate count, selection intent, availability/age/staleness, revision
divergence, drain/disable/deprecation, and atomic workflow-selection commit.
Routes and credentials remain redacted.

### 22. Health and Readiness Observability

Expose process liveness, Registry readiness, core/API readiness, capability
eligibility, deployment availability, dependency health, capacity, and
draining separately. One Agent outage or ordinary saturation does not become a
global API outage. Health detail is bounded and authenticated where necessary.

### 23. Error Classification

Stable safe classes distinguish validation, compatibility, authorization,
dependency, capacity, timeout, confirmed cancellation, lifecycle interruption,
persistence, messaging, integrity, configuration, and internal defects.
Portable errors use ADR-0004; telemetry may add sanitized internal class and
stage. Raw exception types/messages and stack traces are restricted diagnostic
data, not portable fields or metric labels.

### 24. Retry Classification

Every retry signal identifies transport redelivery, Agent internal operation,
persistence transaction, outbox publication, API retry, or Orchestrator
application retry. It records stable logical identity, attempt number, safe
reason, delay, exhaustion, and disposition. A metric/log retry count does not
create a new business attempt.

### 25. Sampling

Metrics aggregate without event sampling. Durable business/security audit is
never sampled. Warning/error/critical and integrity/security events are not
probabilistically suppressed, though duplicate-safe rate limiting may protect
sinks while counters retain volume.

Traces and debug/informational logs may be sampled with bounded, observable
policy. Sampling decisions must preserve trace consistency where possible.
Unsampled traces and dropped logs cannot affect correctness; dropped counts are
observable. Exact rates are deployment policy.

### 26. Redaction and Sensitive Data

Telemetry uses allowlisted fields and classification before emission. Secrets,
credentials, tokens, authorization headers, certificates/private keys,
workflow text, prompts, provider responses, full payloads/outcomes, SQL/binds,
raw health bodies, private endpoints, and arbitrary user/tool data are excluded
by default.

Identifiers are treated as potentially sensitive operational data. Hashing is
not automatic anonymization. Restricted diagnostic capture requires explicit
authorization, bounded time/retention, audit, and secure storage. Unsafe fields
are dropped/redacted, not emitted optimistically.

### 27. Security Audit

Durable security audit covers Registry revision activation, production
capability enable/disable/drain, privilege/policy changes, credential rotation
without values, migration, destructive cleanup, restore, manual outbox
disposition, quarantine redrive, repair, retention override, rejection,
spoofing, and environment crossover.

Evidence includes actor classification, action, target, UTC time, environment,
reason, outcome, and approval reference where required. Identity provider and
audit backend remain undecided.

### 28. Durable Business Audit

Durable audit explains accepted-request identity/fingerprint, workflow state
and transitions, selection intent, task/attempt/command, Agent outcome,
permanent message disposition, late/conflict handling, and correctness-affecting
operator action. It is committed in the authoritative transaction that needs
it. Telemetry mirrors may reference but cannot replace it.

### 29. Durable Audit Versus Operational Logging

Business persistence stores only correctness and historical interpretation
evidence, not every debug event. Operational logs can rotate or disappear.
Neither log aggregation nor traces reconstruct authoritative state when durable
records disagree.

### 30. Audit Immutability and Correction

Transition and security/operator audit are append-only at the application
level. Corrections add linked corrective evidence without rewriting the
original. Retention/deletion follows approved policy; mismatch/corruption is an
integrity incident. No blockchain, WORM, or cryptographic ledger is selected.

### 31. Time Semantics

Portable timestamps use UTC. Semantic event time, database commit time, broker
time, observation time, processing start/end, deadline, trace time, and audit
time are distinct. Monotonic durations are process-local. Durable order comes
only from scoped revisions, sequences, partition offsets, transitions, and
causation. There is no global total order; trace display order is diagnostic.

### 32. Instance and Deployment Context

Logs/traces carry component, environment, logical deployment, software version,
ephemeral process instance, safe internal host/container context, active
Registry/declaration revision, schema version, logical consumer/subscription,
and capability. Stable bounded component/environment/version fields may label
metrics. Process/host/revision identifiers do not. Infrastructure identities
remain internal and never enter portable contracts.

### 33. Technology Evaluation

| Option | Fit | Decision |
| --- | --- | --- |
| Python standard logging | Portable facade, handlers/formatters, offline use | Selected facade |
| Structured logging library | Better context/event APIs | May implement boundary later; no library selected |
| OpenTelemetry API/SDK | Portable trace/metric semantics and exporters | Selected semantic compatibility behind ports |
| OpenTelemetry Collector | Vendor-neutral processing/export | Optional deployment component, not required |
| Prometheus-style metrics | Strong aggregate/scrape and local model | Compatible option; backend deferred |
| Grafana | Dashboard/query UI | Deferred |
| Loki/Tempo/Jaeger | Log/trace storage and query | Deferred |
| Elastic/OpenSearch | Searchable logs/audit copies | Deferred; cost/security/operation exceed first slice |
| Application Insights/vendor APM | Integrated hosted telemetry | Adapter option; vendor types cannot cross boundary |
| Direct audit tables | Transactional authoritative audit | Selected logical persistence under ADR-0006; schema deferred |
| Event Bus telemetry topic | Decoupled signal stream | Rejected initially; adds retention, consumers, and failure coupling |

Python standard logging and local console output work without an external
service and do not impose telemetry storage or licensing costs. Structured
logging libraries can improve context binding, but selecting one would add a
dependency before the platform has implementation evidence that the standard
library facade is insufficient.

OpenTelemetry-compatible semantics provide portability across backends and
deployment sizes without requiring a Collector. Any eventual Python telemetry
package and version must demonstrate compatibility with the CPython 3.14
baseline established by ADR-0003 before adoption. A Collector can later
centralize export, buffering, and policy, but it adds another service,
configuration surface, and security boundary.

Prometheus-compatible metrics and optional visualization tools can run locally
or on one- and two-machine deployments. They remain replaceable because the
application contract is the metric model, not a specific server. Backend
families such as Loki, Tempo, Jaeger, Elastic/OpenSearch, Application Insights,
and other vendor APM products differ materially in storage, cost, operational
complexity, offline behavior, and lock-in; none is necessary to define the
initial contracts.

Direct durable audit persistence aligns with the existing authoritative state
boundary and works without a separate telemetry backend. Sending audit records
only through the Event Bus would add asynchronous failure and recovery
dependencies to an authoritative write and is therefore rejected for this
slice.

### 34. OpenTelemetry Boundary

OpenTelemetry-compatible trace and metric semantics are selected, not a
mandatory SDK deployment. Domain code depends on platform diagnostic ports or
thin infrastructure helpers, never OTel SDK objects. Exporters, SDK providers,
auto-instrumentation, and Collector are deployment concerns. No-op operation is
required. Propagation cannot alter domain identity. OTel logging is optional;
semantic conventions and vendor extensions are reviewed and adapter-local.

### 35. Telemetry Failure Behavior

Log, metric, trace, collector, exporter, serialization, or queue failure must
not block workflow correctness. Buffers are bounded; failure/drop counters and
local safe fallback are used where possible. Invalid/sensitive telemetry is
dropped or redacted.

Correctness-required business audit failure aborts its authoritative
transaction. Required security-audit failure fails closed for the privileged
action. Invalid clock data is classified and excluded from ordering claims.

### 36. Buffering and Backpressure

Logs and trace export use bounded queues and timeouts; metrics aggregate in
bounded instruments. Shutdown attempts a bounded flush, then records/drops
ordinary telemetry rather than delaying safe component shutdown indefinitely.
Telemetry cannot block broker polling, database transactions, or Agent work.

No durable local telemetry disk buffer or Event Bus buffer is required in the
first slice. Console logging is the local fallback. Authoritative audit uses
business persistence, not telemetry buffers.

### 37. Retention

Separate policies govern operational logs, traces, metrics, workflow audit,
security audit, inbox/outbox diagnostics, quarantine, backup/restore evidence,
and debug telemetry. Periods reflect troubleshooting, broker replay,
idempotency, workflow interpretation, privacy, incident/legal policy, and cost.
Debug is shortest; sensitive data is never retained merely because space exists.
Exact periods are deferred.

### 38. Query and Investigation Model

Operators can correlate by request/workflow/task/attempt/message/correlation ID,
capability, `agent_id`, Registry/declaration revision, safe error class, time,
component, deployment, and outcome. High-cardinality lookup belongs in
authorized logs, traces, and durable audit—not metrics. No UI is selected.

### 39. Alerting Boundary

Alertable conditions include authoritative persistence/schema failure, old or
operator-blocked outbox, inbox/quarantine growth, retry exhaustion, Event Bus
loss, workflow-impacting lag, Agent/Registry unavailability, no candidate,
deadline-failure rate, integrity conflict, backup/restore failure, telemetry
pipeline/storage pressure, security-audit failure, and spoof/environment
incident.

Alerts distinguish symptom, cause, capacity, correctness, and security.
Individual expected task failure does not page by default. Product and routing
are deferred.

### 40. Service Objectives Boundary

The architecture defines measurable indicators: workflow acceptance
availability, terminal latency, command publication and outcome-processing
delay, outbox oldest age, Agent/capability availability, Registry/readiness
latency, audit completeness, and backup success. Exact SLO targets require
measured product/deployment policy and are not invented here.

### 41. Local Development

Vertical Slice 01 defaults to readable structured console logs with durable
identifier correlation. Local metrics and trace exporters are optional; no
Collector, SaaS, dashboard, or full stack is required. Multiple processes,
restart/crash, and deterministic failure injection work on Windows/Linux,
Docker, and Unraid.

### 42. Testing Strategy

Tests cover:

- API→workflow→command→Agent outcome→terminal transition correlation,
  duplicates, replay, new attempt, late outcome, selection, crash/restart;
- structured fields, taxonomy, severity, process/deployment context,
  serialization failure, redaction, and no payload/secret leakage;
- metric increments, bounded labels, histograms, backlog, retry/readiness/drop;
- API/persistence/producer/consumer/execution/dependency spans, asynchronous
  links, duplicate spans, no-op providers, and exporter isolation;
- transition/selection/outcome/rejection/operator/security audit, additive
  correction, and audit failure rolling back authoritative work;
- exporter/collector/queue/shutdown/sensitive-field failure; and
- monotonic duration, skew, event/processing/retry/deadline time without global
  ordering inference.

Deterministic clocks support unit tests. Real exporters, collectors, storage,
process/network loss, and clock skew require integration or resilience tests.

### 43. Initial Vertical Slice Decision

Vertical Slice 01 uses structured JSON standard-output logs, stable event
classes, authoritative PostgreSQL workflow/task/transition/selection/outcome
evidence, and all ADR-0004 identifiers. W3C trace context propagates at API and
Event Bus adapters. OpenTelemetry-compatible trace/metric semantics sit behind
infrastructure boundaries with no-op support.

Local metric/trace export is optional. No Collector, telemetry Event Bus,
dashboard, alert backend, or SaaS is required. Export is bounded and
nonblocking; high-cardinality labels are prohibited; allowlist/redaction is
mandatory; authoritative audit remains in business persistence.

### 44. Coherent Observability Architecture

The decision is:

- observability combines lossy operational signals with authoritative durable
  evidence;
- logs, metrics, traces, business audit, security audit, and recovery metadata
  remain distinct;
- ADR-0004 durable identities connect every boundary without equating trace
  and workflow identity;
- W3C trace propagation and asynchronous span links are selected at adapters;
- structured JSON logging, bounded taxonomy, and consistent
  severity are selected;
- aggregate metrics use bounded labels and distribution-based latency;
- persistence, messaging, outbox/inbox, Agent, Registry, and readiness signals
  retain their accepted semantics;
- retry/error classification, sampling, redaction, and privacy are explicit;
- business/security audit is durable and additive;
- UTC semantics and process-local monotonic durations make no global-order
  claim;
- Python logging plus OpenTelemetry-compatible trace/metric semantics are
  selected behind ports, with backend/Collector deferred;
- ordinary telemetry failure is bounded and nonblocking, while required audit
  failure fails its correctness action;
- retention, investigation, alerting, and service indicators are defined
  without products or targets; and
- local operation and tests require no external observability stack.

### 45. Guarantee and Evidence Table

| Guarantee | Authoritative evidence | Telemetry/IDs | Loss/privacy/failure boundary | Proof |
| --- | --- | --- | --- | --- |
| Accepted request explainable | Accepted mapping + workflow transaction | Logs/traces; request/workflow/correlation | Telemetry may vanish; input redacted; audit failure rolls back | Commit/lost-response/replay tests |
| Transition auditable | Current state + transition history | Transition log/span; workflow/event IDs | Sampled trace cannot prove commit | Atomic transition tests |
| Agent selection explainable | Atomic ADR-0008 selection intent | Lookup logs/span; workflow/agent/revisions | Routes redacted; logs supplementary | Selection completeness tests |
| Command publication diagnosable | Command outbox + certainty state | Publish spans/metrics; message/attempt | Ack loss duplicates spans; payload excluded | Every outbox failure-window test |
| Duplicate delivery identifiable | Inbox/receipt + stable message ID | Redelivery metric and processing spans | Logs sampled; duplicate is expected | Redelivery/dedup tests |
| One Agent outcome provable | Completed receipt/outcome/event/outbox | Execution logs/spans; attempt/message | Execution telemetry can be lost | Competing outcome/crash tests |
| Late outcome correlated | Agent outcome + Orchestrator inbox/transition | Deadline/event spans; workflow/attempt | Clock skew; terminal state authoritative | Deadline-race tests |
| Transaction retry diagnosable | Final transaction result and durable records | Retry metric/log/span; transaction class | Attempts may be sampled; no SQL/binds | Retry/uncertainty tests |
| Registry staleness observable | Active revision + atomic selection evidence | Age/readiness metrics; agent/revisions | TTL false window; route redacted | Clock/mismatch tests |
| Telemetry loss cannot change correctness | Authoritative component persistence | Drop/failure counters | Ordinary buffers may lose data; processing continues | Exporter/queue outage tests |
| Security action auditable | Required security/operator audit | Sanitized security log; actor/action | Never sampled; secret excluded; fail closed | Privileged audit-failure tests |

### 46. Consequences

#### Positive Consequences

- Durable truth and operational diagnosis cannot be confused.
- Async duplicates, uncertainty, deadlines, and restarts are explainable.
- Backend-neutral standards allow incremental adoption.
- Privacy and cardinality controls bound risk and cost.

#### Negative Consequences

- Consistent instrumentation and classification require discipline.
- Traces/logs remain incomplete and multiple stores may be consulted.
- Durable audit adds transactional and retention responsibility.
- Bounded telemetry intentionally loses some diagnostic detail.

#### Migration Impact

No implementation exists. Future instrumentation must preserve ports,
identities, redaction, and source-of-truth boundaries.

#### Developer Impact

Developers add stable classifications and safe context at boundaries, never log
payloads by convenience, and test telemetry failure independently of business
failure.

#### CI Impact

Fast tests use in-memory/no-op sinks; exporter, process, network, storage, and
clock behavior needs integration/resilience environments. No CI is assumed.

#### Operational Impact

Operators correlate durable records with several optional signal stores and
manage volume, drops, retention, and partial readiness.

#### Security Impact

Telemetry administration, routing, and security audit require least privilege,
protected configuration, and fail-closed handling for required evidence.

#### Privacy Impact

Telemetry becomes a protected data surface. Allowlists, redaction, restricted
diagnostics, identifier handling, and bounded retention are mandatory.

#### Cost Impact

Cardinality, sampling, retention, and optional backends control CPU, memory,
network, and storage cost. No commercial spend is assumed.

#### Future Review Triggers

Review when production backend/Collector/SIEM, tail sampling, mandatory durable
telemetry buffer, regulated retention/WORM, prompt/model tracing, exact SLOs,
or cross-site investigation becomes required.

### 47. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Telemetry becomes truth | Authoritative-boundary tests and documentation |
| Missing async correlation | Mandatory durable IDs and adapter trace context |
| Trace ID confused with workflow | Keep identity fields distinct |
| Redelivery creates misleading traces | New processing span linked to stable message context |
| Metric cardinality explosion | Label allowlist and review |
| Sensitive leakage | Classification, allowlist, redaction, restricted capture |
| Excessive volume/cost | Sampling, severity, bounded queues, retention |
| Exporter blocks work | Timeouts, no-op/fallback, nonblocking bounded export |
| Queue exhausts memory | Hard bounds and drop counters |
| Sampling hides failure | Durable audit plus unsampled critical classes |
| Mutable audit | Additive corrections and integrity incident |
| Clock skew implies order | Scoped durable order and monotonic duration |
| Severity/alert inflation | Stable impact rules and aggregate alerts |
| One health signal hides outage | Separate readiness layers |
| SDK types leak | Platform ports and adapter-local extensions |
| Backend lock-in | W3C/OTel-compatible semantics and replaceable exporters |
| Public operational IDs | Keep infrastructure context internal |
| SQL/payload leakage | Disabled by default and redaction tests |
| Audit failure ignored | Roll back correctness action or fail privileged action |
| Local stack too heavy | Console/no-op defaults; all backends optional |
| Restart loses only evidence | Durable business/recovery records |
| Duplicate publish seems duplicate work | Stable message/outcome identities and classifications |
| Signals disagree | Durable evidence wins; mismatch becomes diagnostic incident |

### 48. Assumptions

- ADR-0001 through ADR-0008 remain Accepted.
- Component persistence provides the accepted durable evidence.
- W3C context can be carried by API and Event Bus adapters without contract
  changes.
- Telemetry can operate as no-op or local console output.
- Monitoring/log/trace backend, Collector, dashboard, alerts, SLO values,
  retention periods, identity provider, and SIEM remain unresolved.

### 49. Open Questions

1. What exact structured-log serialization and event naming convention apply?
2. Which exact OpenTelemetry packages/versions and metric prefix are used?
3. What histogram buckets and sampling rates fit measured workloads?
4. Which local exporters and future Collector topology are selected?
5. Which log, metric, trace, and security-audit backends are adopted?
6. What retention periods, alert thresholds, and SLO targets apply?
7. Which investigation UI and deployment-resource attributes are exposed?
8. What complete sensitive-data classification catalogue governs restricted
   diagnostics?

### 50. Explicitly Out of Scope

Final observability/SaaS backend, dashboards, alert routing/on-call product,
exact SLOs/retention, SIEM, identity/secrets provider, data lake, business/product
analytics, AI/model evaluation, prompt-tracing product, cost allocation,
incident process, IaC, Kubernetes monitoring, and production Collector topology
are out of scope.

### 51. Acceptance Checklist

- [ ] Observability and all six signal categories are distinct.
- [ ] Authoritative persistence wins over logs, metrics, and traces.
- [ ] Correlation identities have owners, propagation, and cardinality rules.
- [ ] Correlation, message causation, and global ordering are distinct.
- [ ] API rejection, acceptance, replay, conflict, and response loss correlate.
- [ ] Event Bus context and adapter-only broker diagnostics are separated.
- [ ] W3C trace context and trace/domain identity separation are approved.
- [ ] Async publication, redelivery, duplicates, restart, and links are clear.
- [ ] Structured logging fields, taxonomy, serialization boundary, and severity
      are approved.
- [ ] Metrics, label cardinality review, distributions, and latency semantics
      are approved.
- [ ] Workflow diagnosis identifies durable and lossy evidence.
- [ ] Persistence, Event Bus, outbox/inbox, Agent, Registry, and readiness
      signals preserve prior ADR semantics.
- [ ] Error and every retry category remain distinct.
- [ ] Sampling never applies to durable audit.
- [ ] Redaction, classification, restricted capture, and identifier privacy are
      explicit.
- [ ] Security audit fields and fail-closed behavior are approved.
- [ ] Durable audit, additive correction, and corruption handling are approved.
- [ ] UTC, semantic/commit/processing time, monotonic duration, and scoped order
      are distinct.
- [ ] Deployment/process context remains internal where required.
- [ ] Technology evaluation selects standards without a backend.
- [ ] OpenTelemetry-compatible semantics remain behind no-op-capable ports.
- [ ] Ordinary telemetry failure cannot break business correctness.
- [ ] Required audit failure aborts its authoritative action.
- [ ] Buffers, flush, drop, and local fallback are bounded.
- [ ] No first-slice disk or Event Bus telemetry buffer is required.
- [ ] Retention categories and high-cardinality investigation are explicit.
- [ ] Alerting categories and measurable indicators have no invented targets.
- [ ] Local development requires only structured console/no-op telemetry.
- [ ] Tests distinguish unit evidence from exporter/process/network proof.
- [ ] Reviewers confirm consistency with ADR-0001 through ADR-0008, Vertical
      Slice 01, testing guidance, `SECURITY.md`, and `AGENTS.md`.
- [ ] Every open question is bounded implementation/deployment policy.

## Related Decisions

- [ADR-0001: Core Design Principles](ADR-0001-core-design-principles.md)
- [ADR-0002: Platform Communication and State](ADR-0002-platform-communication-and-state.md)
- [ADR-0003: Runtime and Development Tooling](ADR-0003-runtime-and-development-tooling.md)
- [ADR-0004: API and Contract Standards](ADR-0004-api-and-contract-standards.md)
- [ADR-0005: Event Bus and Messaging Infrastructure](ADR-0005-event-bus-and-messaging-infrastructure.md)
- [ADR-0006: Persistence, State, and Recovery](ADR-0006-persistence-state-and-recovery.md)
- [ADR-0007: Agent Execution Model and Lifecycle](ADR-0007-agent-execution-model-and-lifecycle.md)
- [ADR-0008: Capability Registry and Agent Discovery](ADR-0008-capability-registry-and-agent-discovery.md)

## References

- [Platform Architecture](../README.md)
- [Vertical Slice 01](../../implementation/vertical-slice-01.md)
- [Platform test strategy](../../testing/README.md)
- [Repository security policy](../../../SECURITY.md)
- [Repository Agent guidance](../../../AGENTS.md)
- [W3C Trace Context](https://www.w3.org/TR/trace-context/)
- [OpenTelemetry overview](https://opentelemetry.io/docs/specs/otel/overview/)
- [OpenTelemetry tracing API](https://opentelemetry.io/docs/specs/otel/trace/api/)
- [OpenTelemetry messaging span conventions](https://opentelemetry.io/docs/specs/semconv/messaging/messaging-spans/)
- [Python logging](https://docs.python.org/3.14/library/logging.html)
- [Prometheus instrumentation guidance](https://prometheus.io/docs/practices/instrumentation/)
- [Prometheus metric and label naming](https://prometheus.io/docs/practices/naming/)
