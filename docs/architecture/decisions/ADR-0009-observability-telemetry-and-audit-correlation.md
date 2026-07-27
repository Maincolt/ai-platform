# ADR-0009: Observability, Telemetry, and Audit Correlation

- **Status:** Accepted
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
  informally as equivalent. `workflow_id` is the durable identity and primary
  lookup key for one accepted workflow. `correlation_id` is an optional
  broader durable logical-operation grouping. Trace ID identifies one
  operational trace. They have different owners, lifetimes, and trust rules.
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
| Business-state-coupled audit | Explain accepted requests, selections, transitions, outcomes, dispositions, and repairs | Authoritative evidence committed with the affected business or recovery state |
| Administrative security audit | Explain privileged, policy, deployment, configuration, and external administrative actions | Required durable evidence at an administrative trust boundary |
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
- business-state-coupled audit committed with those records; and
- required durable administrative security audit, including uncertain
  outcomes awaiting reconciliation.

Logs, metrics, traces, dashboards, and external telemetry stores never decide
workflow state, idempotency, deduplication, selection, or transaction outcome.
Telemetry loss cannot change workflow correctness. A log or span is never proof
of commit; absence is never proof that work did not occur.

### 4. Correlation Identity Model

| Identity | Owner/stability | Propagation and signal use | Metric label |
| --- | --- | --- | --- |
| `request_id` | Client/API; stable after acceptance | API, workflow audit, logs/traces | No |
| `workflow_id` | Orchestrator after acceptance; durable and stable across attempts | Primary lookup for one workflow and all workflow/task evidence and messages | No |
| `task_id` | Orchestrator; durable | Task audit/messages/logs/traces | No |
| `task_attempt_id` | Orchestrator per application attempt | Commands, outcomes, retry audit | No |
| command/event `message_id` | Producer per immutable logical message | Message, inbox/outbox, logs/traces | No |
| `correlation_id` | API validates a client value; Orchestrator generates it when absent and persists it at acceptance | Optional broader logical grouping across related interactions/workflows; commands, terminal events, logs/traces/audit | No |
| `causation_id` | Message producer; immediate prior message ID or null | Portable message/audit | No |
| capability/version | Capability owner; versioned | Messages, selection, logs/traces | Yes, when bounded |
| selected `agent_id` | Deployment owner/Orchestrator selection | Command, selection audit, logs/traces | No; only a reviewed controlled deployment class may label metrics |
| Registry/deployment revisions | Deployment configuration | Selection audit/logs/traces | Not raw revision |
| implementation version | Release owner | Resource context/logs/traces | Yes, bounded |
| process instance | Runtime; ephemeral | Logs/traces/diagnostics | No |
| consumer identity | Adapter configuration | Inbox/transport diagnostics | Bounded logical consumer only |
| transaction classification | Persistence adapter | Logs/metrics/traces | Yes |
| inbox/outbox identity | Record owner; durable operational | Recovery audit/logs/traces | No |

Internal database keys, host IDs, and offsets are never portable identifiers.
`workflow_id` is generated only after acceptance, remains stable across task
attempts, and is the primary operator search key for workflow-specific
diagnosis.

Clients may supply `Correlation-Id` as the lowercase UUIDv7 selected by
ADR-0004. The Workflow API owns syntax, size, and trust-boundary validation.
Malformed or disallowed client values are discarded rather than making an
otherwise valid business request fail. The API replaces them with a
server-generated transient transport correlation for request diagnosis. If no
valid client correlation reaches acceptance, the Orchestrator generates the
durable UUIDv7, preserving ADR-0004 ownership. A supplied value carries no
authorization or integrity authority merely because it is well formed.
Multiple workflows may intentionally share one `correlation_id`; it is not
unique and grouping is allowed only within the authorized environment and
security context.

Before acceptance, a validated client value or server-generated replacement is
transient API transport correlation and may appear in safe logs and problem
responses. Rejected or temporarily unavailable submissions create no durable
workflow correlation. Acceptance stores the valid client value or
Orchestrator-generated `correlation_id` atomically with the workflow and
accepted-request mapping. Equivalent `request_id` replay returns the stored
correlation and workflow identifiers, even if the replay carries another
correlation value. Application retries within the workflow preserve it.
Commands and terminal events propagate it.

`correlation_id` is not proof of ordering, authorization, idempotency,
deduplication, or transaction outcome. Retry preserves identities unless
ADR-0004 defines a new application attempt. Deployment class is a separate
controlled vocabulary, never a derivation of an arbitrary identifier.

### 5. Correlation Versus Causation

Correlation optionally groups a broader logical operation and may span
multiple explicitly related workflows; causation names the immediate
predecessor message. `workflow_id` identifies one workflow regardless of that
grouping. API acceptance creates the workflow and durable audit relationship.
The root command has no message cause. `TaskCompleted`/`TaskFailed` causation is
the command `message_id`; the terminal transition cites the accepted event or
deadline decision.

Broker republication/redelivery preserves message, correlation, causation, and
attempt identities. It creates new operational attempts, not new business
causes. Application retry creates a new `task_attempt_id` and command
`message_id` while retaining workflow and correlation identities. Accepted API
replay creates no workflow and returns the stored correlation. Correlation
implies neither total order nor successful completion.

### 6. API Correlation

Before workflow creation, valid `request_id`, validated or generated transport
`correlation_id`, sanitized incoming trace context, and server request/trace
identity may exist. Invalid input uses only safe transport context and any
safely parsed request ID. Invalid and unavailable-Agent submissions may return
the transport correlation required by ADR-0004, but create neither a durable
workflow correlation nor a workflow.

Acceptance atomically creates durable workflow/task/selection identities and
stores the valid client or Orchestrator-generated `correlation_id` with the
accepted-request mapping. Equivalent replay returns stored identities, stored
correlation, and current state, and creates only a new HTTP processing
span/log. A different request under the same `request_id` returns the stable
conflict without changing the stored correlation. Response loss after commit
is resolved through `request_id`; retry returns the existing workflow.

### 7. Message Correlation

Event Bus telemetry includes logical channel, message/contract type,
`message_id`, `correlation_id`, `causation_id`, workflow/task/attempt,
capability, target `agent_id`, producer, logical consumer, and duplicate,
redelivery, or rejection classification.

Adapters may add partition, offset, group member, delivery attempt, and broker
diagnostics to internal logs/traces. Trace context may travel in broker headers.
Headers never redefine ADR-0004 identity or enter domain payload validation.
Trace headers are accepted only from authenticated and authorized platform
producers. Invalid or excessive trace headers are ignored while an otherwise
valid domain message continues through normal envelope and payload validation.
Trace propagation failure cannot invalidate the business message or alter
message identity, correlation, causation, contract validation, or disposition.

Redelivery creates a new processing span linked to the same immutable
`message_id` and durable domain identifiers. A process restart may begin a new
trace while retaining those identifiers.

### 8. Trace Context Propagation

The architecture adopts W3C Trace Context semantics at trusted API and
messaging adapters. Syntax validity does not establish trust. Baggage is not
propagated initially.

At the external API boundary, malformed `traceparent` or `tracestate` is
ignored or replaced and never becomes a business-validation failure. Incoming
sampling flags are advisory; platform sampling policy is authoritative.
`tracestate` has strict size, entry-count, and allowlist limits, and unknown or
unsafe vendor entries may be removed. The boundary may start a new internal
root and link to sanitized accepted external context instead of continuing it.
Cross-tenant, cross-environment, or cross-security-context linking is
prohibited.

At the internal Event Bus boundary, trace headers are considered only after
producer authentication and authorization. Invalid, excessive, spoofed, or
cross-environment context is ignored without invalidating a valid message.
Trace context cannot influence authorization, request idempotency, workflow or
message identity, Registry selection, ordering, retries, or transaction
outcome.

Spans cover API handling, Registry/readiness, persistence, outbox publication,
message production/consumption, Agent execution, dependencies, outcome commit,
and terminal processing. Messaging producer and consumer/process spans use
links where asynchronous or repeated processing is not a strict synchronous
parent-child relationship. Domain interfaces receive only technology-neutral
diagnostic context, never SDK objects. Trace retention is not durable causality.

### 9. Trace and Domain Identity Relationship

Trace ID, span ID, `correlation_id`, `workflow_id`, `request_id`, `message_id`,
and `causation_id` remain distinct. `workflow_id` is the primary durable
identity for one workflow. `correlation_id` is durable after acceptance and may
group explicitly related workflows, but does not equal `workflow_id`. Trace ID
identifies one sampled operational trace and never becomes a domain ID. Before
acceptance, API request, transient correlation, and sanitized trace context
supply operational diagnosis.

Every publish attempt and redelivery may create a new span linked to the same
logical message context. Duplicates create distinct processing spans with the
same message/attempt attributes. Internal retries are child or sibling attempt
spans as appropriate. Restart can break trace continuity or intentionally
start a new trace; stable workflow/correlation/message identifiers restore
investigation continuity.

### 10. Structured Logging Model

Logs use machine-readable structured fields with stable event classification,
UTC timestamp, severity, component, environment, logical deployment, software
and process instance, operation, relevant durable IDs, safe error/retry class,
duration, and disposition.

The production and container default emits one structured JSON-compatible
record per standard-output event, as accepted by ADR-0003. Interactive local
development may render the same structured event model in human-readable form.
Field names, classification, redaction, and severity are identical before
either renderer; local readability cannot restore or introduce a field removed
by production redaction. Tests target the structured event record before
rendering.

The logical field model remains backend-neutral; exact encoder details are
implementation policy. Human text is supplementary and never parsed as a
contract. Python standard logging is the application facade;
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
task failures are not automatically errors. A correctly enforced
security-policy rejection may be an information or warning log, a durable
security-audit event, and an alert input based on rate, actor, target, or
pattern; it is not automatically an application error. Repeated, systemic,
privileged, spoofing, or environment-crossover behavior may raise alert
severity independently from the per-request log severity.

Deterministic rate limiting may aggregate ordinary repeated operational
emissions. The first occurrence in a bounded interval, any change in
classification, scope, disposition, or severity, and recovery or state
transition are emitted.
Suppressed repeats increment a bounded counter, and periodic summary events
report the count and interval. The aggregation fingerprint contains only
bounded component, operation, safe error code, affected scope, and disposition
values. It never uses raw exception text, user input, arbitrary identifiers, or
secrets.

Durable business and security audit is never suppressed. Unique integrity
conflicts are not merged when aggregation would lose required evidence.
Aggregated security events retain bounded actor classification, target class,
environment, and action class.

### 13. Metrics Model

Metrics cover API count/latency/disposition; workflows by state/age/terminal
latency; transitions; command/event production/consumption; duplicate,
redelivery, quarantine; inbox/outbox backlog and oldest age; publication
certainty; transaction latency/retry/deadlock/exhaustion; Agent concurrency,
admission, saturation, execution and dependency outcomes; Registry revision
activation, candidate/availability/staleness; pools/storage/cleanup;
liveness/readiness/drain; and backup/restore where available.

Operational observability also measures telemetry drops, rate-limited
repetitions, summary emissions, exporter failures, and bounded-buffer pressure
using controlled classifications.

Metric names follow one reviewed platform convention; exact names and backend
are deferred.

### 14. Metric Cardinality

Request, workflow, task, attempt, message, raw `agent_id`, revision, endpoint,
process, exception, input, provider ID, and SQL values are prohibited ordinary
labels. They belong in logs, traces, and audit.

Bounded labels may include component, environment, capability/version, outcome
or error class, logical channel/message type, contract major, deployment class,
readiness class, and retry class. Deployment class is an explicit controlled
vocabulary. It is never automatically derived from `agent_id`, hostname,
namespace, container, user configuration, or another arbitrary value. Adding a
deployment-class value requires cardinality and privacy review; unknown values
map to a bounded fallback. High-cardinality deployment diagnosis remains in
authorized logs, traces, and audit.

Every new label needs cardinality/privacy review. Unknown or unbounded values
collapse to a safe bounded classification.

### 15. Histogram and Latency Model

Distributions, not averages alone, measure API, acceptance transaction,
Registry/readiness, outbox age, transport, message processing, Agent admission
and execution, outcome commit, workflow terminal, persistence, dependency, and
shutdown-drain durations. In-process duration uses monotonic time. UTC
timestamps support cross-system diagnosis but not perfect ordering. Exact
buckets require measurement.

### 16. Workflow Observability

One workflow is reconstructed primarily by `workflow_id` from accepted request,
workflow/task/attempt and selection records, transition history, command
outbox, publication disposition, Agent receipt/outcome/outbox, Orchestrator
inbox, and final state. `correlation_id` optionally finds related interactions
or workflows; trace ID finds one sampled operational trace. Logs and traces add
runtime attempts, durations, process context, and crash boundaries; metrics
show aggregate context.

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

A correctly enforced security-policy rejection is a security outcome, not
automatically an application defect. Its operational severity follows actual
service impact, while its security-audit and alert classifications follow
actor, target, privilege, rate, pattern, and environment-crossing risk.

### 24. Retry Classification

Every retry signal identifies transport redelivery, Agent internal operation,
persistence transaction, outbox publication, API retry, or Orchestrator
application retry. It records stable logical identity, attempt number, safe
reason, delay, exhaustion, and disposition. A metric/log retry count does not
create a new business attempt.

### 25. Sampling

Metrics aggregate without event sampling. Durable business/security audit is
never sampled. Warning/error/critical and integrity/security events are not
probabilistically suppressed. Incoming trace sampling flags are advisory and
cannot force platform sampling; the platform policy is authoritative.

Traces and debug/informational logs may be sampled with bounded, observable
policy. Sampling decisions must preserve trace consistency where possible.
Unsampled traces and dropped logs cannot affect correctness; dropped counts are
observable. Exact rates are deployment policy.

Probabilistic sampling and deterministic rate limiting are separate.
Sampling may omit otherwise independent successful traces or informational
events according to policy. Rate limiting only aggregates repeated operational
emissions under a stable bounded fingerprint while retaining the first
occurrence, material changes, recovery/state transitions, suppressed counts,
and periodic summaries. Neither mechanism suppresses authoritative audit or
required unique integrity evidence.

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

External and broker trace context is untrusted metadata until adapter policy
accepts it. Bounded allowlists and environment/security-context checks prevent
trace spoofing, amplification, forced sampling, unbounded `tracestate`, and
cross-tenant or cross-environment correlation. Baggage remains disabled.

### 27. Security Audit

Administrative security audit covers Registry revision activation, production
capability enablement, deployment drain/disablement, schema migration
initiation, credential rotation without values, retention-policy change,
configuration promotion, privilege/policy change, restore, rejection,
spoofing, and environment crossover. Manual outbox disposition, quarantine
redrive, workflow/data repair, and other actions that directly mutate
authoritative business or recovery state instead use the coupled transaction
defined below.

An administrative action may occur outside a workflow transaction. Its durable
security-audit boundary records actor classification, authenticated source,
action, target, UTC time, environment, previous and resulting revision where
applicable, reason, approval reference, start, outcome, uncertainty
classification, and reconciliation owner or responsibility.

Required audit evidence must be durable before configuration activation is
reported successful. Audit storage failure prevents a privileged action where
it is still safe to stop. If an external effect may have occurred before its
audit outcome becomes certain, the record remains an unknown administrative
outcome and requires reconciliation. Irreversible external administrative
actions require an explicit prepare/apply/audit or reconciliation protocol.
This ADR selects no identity provider or administrative audit backend.

A correctly enforced security rejection may have information or warning
operational severity while remaining a security-audit event. Repeated,
systemic, privileged, spoofed, or environment-crossing patterns independently
affect alert severity.

### 28. Durable Business Audit

Business-state-coupled audit explains accepted-request identity/fingerprint,
workflow state and transitions, task selection, task/attempt/command, Agent
outcome, permanent message disposition, manual outbox disposition, quarantine
redrive, workflow/data repair, late/conflict handling, and any other
correctness-affecting operator action.

When an action changes authoritative business or recovery state, its audit
evidence is committed in the same database transaction: action and audit both
commit or neither commits. Audit failure aborts and rolls back the action.
Corrections are additive. Telemetry mirrors may reference but cannot replace
this evidence.

### 29. Durable Audit Versus Operational Logging

Business persistence stores only correctness and historical interpretation
evidence, not every debug event. Operational logs can rotate or disappear and
are insufficient as business or administrative audit. Pipeline logs alone are
also insufficient unless policy explicitly designates their durable system as
the authoritative administrative audit boundary and it satisfies this ADR's
required fields, durability, failure, and reconciliation behavior.

Neither log aggregation nor traces reconstruct authoritative state when
durable records disagree.

### 30. Audit Immutability and Correction

Business and administrative security audit are append-only at the application
level. Corrections add linked corrective evidence without rewriting the
original. An uncertain administrative effect retains its original unknown
outcome and receives linked reconciliation evidence. Retention/deletion follows
approved policy; mismatch/corruption is an integrity incident. No blockchain,
WORM, cryptographic ledger, or specific audit backend is selected.

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
metrics. A metric deployment class comes only from an explicit controlled
vocabulary; it is not derived from arbitrary Agent, host, namespace, container,
or user-configured values. New values require cardinality and privacy review,
and unknown values map to a bounded fallback. Process/host/revision identifiers
do not label metrics. Infrastructure identities remain internal and never enter
portable contracts; high-cardinality diagnosis stays in authorized logs,
traces, and audit.

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
| Direct business-audit persistence | Transactional authoritative audit coupled to business/recovery state | Selected logical persistence under ADR-0006; schema deferred |
| Administrative security-audit backend | Durable evidence for actions outside a workflow transaction | Deferred; must satisfy the trust, failure, uncertainty, and reconciliation boundary |
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

Direct durable business-audit persistence aligns with the existing
authoritative state boundary and works without a separate telemetry backend.
Sending coupled business audit only through the Event Bus would add
asynchronous failure and recovery dependencies to an authoritative write and
is therefore rejected. Administrative security-audit technology remains
deferred; its required semantics do not select storage.

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
dropped or redacted. Invalid external or internal trace context is ignored or
replaced at the adapter and cannot invalidate an otherwise valid API request or
business message.

Correctness-required business audit failure aborts its authoritative
transaction. Required administrative security-audit failure fails closed for
the privileged action where it is still safe to stop. If an external
administrative effect may already have occurred, the outcome is recorded as
unknown and enters mandatory reconciliation rather than being reported as
successful. Invalid clock data is classified and excluded from ordering
claims.

Rate-limiter failure degrades to safe bounded emission or dropping with an
observable counter; it never suppresses durable audit. Operational aggregation
preserves the first event, material changes, recovery/state transitions, and
periodic counts.

### 36. Buffering and Backpressure

Logs and trace export use bounded queues and timeouts; metrics aggregate in
bounded instruments. Shutdown attempts a bounded flush, then records/drops
ordinary telemetry rather than delaying safe component shutdown indefinitely.
Telemetry cannot block broker polling, database transactions, or Agent work.
Operational rate-limit fingerprints and counters are bounded. Periodic summary
events report suppressed repeats and interval without expanding keys from raw
input or identifiers.

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

For one-workflow diagnosis, operators start with `workflow_id`. They may use
`correlation_id` to discover explicitly grouped interactions or workflows and
trace ID to inspect one sampled operational trace. Additional searches include
request/task/attempt/message ID, capability, `agent_id`, Registry/declaration
revision, safe error class, time, component, deployment, and outcome.
High-cardinality lookup belongs in authorized logs, traces, and durable
audit—not metrics. No UI is selected.

### 39. Alerting Boundary

Alertable conditions include authoritative persistence/schema failure, old or
operator-blocked outbox, inbox/quarantine growth, retry exhaustion, Event Bus
loss, workflow-impacting lag, Agent/Registry unavailability, no candidate,
deadline-failure rate, integrity conflict, backup/restore failure, telemetry
pipeline/storage pressure, security-audit failure, and spoof/environment
incident.

Alerts distinguish symptom, cause, capacity, correctness, and security.
Individual expected task failure or correctly enforced policy rejection does
not page by default. Rejection rate, actor/target pattern, privilege, spoofing,
systemic failure, and environment crossover may raise alert severity
independently from each event's operational log severity. Rate-limited
operational events feed alerts through retained counts and periodic summaries.
Product and routing are deferred.

### 40. Service Objectives Boundary

The architecture defines measurable indicators: workflow acceptance
availability, terminal latency, command publication and outcome-processing
delay, outbox oldest age, Agent/capability availability, Registry/readiness
latency, audit completeness, and backup success. Exact SLO targets require
measured product/deployment policy and are not invented here.

### 41. Local Development

Vertical Slice 01 uses the same structured event model in every environment.
Production and containers default to one JSON-compatible standard-output
record per event. Interactive local development may select a human-readable
renderer without changing fields, classification, redaction, or severity.
Local metrics and trace exporters are optional; no Collector, SaaS, dashboard,
or full stack is required. Multiple processes, restart/crash, and deterministic
failure injection work on Windows/Linux, Docker, and Unraid.

### 42. Testing Strategy

Tests cover:

- API→workflow→command→Agent outcome→terminal transition correlation,
  duplicates, replay, new attempt, late outcome, selection, crash/restart;
- valid client correlation, malformed/untrusted replacement, accepted-request
  replay, application retry, two intentionally correlated workflows,
  pre-creation rejection, and trace restart with durable correlation intact;
- external malformed/excessive/spoofed/forced-sampling/cross-environment trace
  context and internal unauthorized or invalid trace headers, proving domain
  validation and identifiers remain independent;
- structured fields, taxonomy, severity, process/deployment context,
  serialization failure, pre-render event records, equivalent local/production
  fields, redaction, and no payload/secret leakage;
- metric increments, controlled deployment-class vocabulary, unknown fallback,
  bounded labels and aggregation keys, histograms, backlog,
  retry/readiness/drop;
- first error occurrence, repeated-failure summary, suppressed count, recovery,
  severity/disposition change, unique integrity evidence, and bounded security
  aggregation dimensions;
- API/persistence/producer/consumer/execution/dependency spans, asynchronous
  links, duplicate spans, no-op providers, and exporter isolation;
- transition/selection/outcome/rejection/operator/security audit, additive
  correction, business mutation and manual disposition rollback on coupled
  audit failure, privileged configuration fail-closed behavior, unknown
  external administrative outcome/reconciliation, and proof that pipeline logs
  are not silently authoritative;
- exporter/collector/queue/shutdown/sensitive-field failure; and
- monotonic duration, skew, event/processing/retry/deadline time without global
  ordering inference.

Deterministic clocks support unit tests. Real exporters, collectors, storage,
process/network loss, and clock skew require integration or resilience tests.

### 43. Initial Vertical Slice Decision

Vertical Slice 01 uses structured JSON-compatible standard-output logs in
production/containers and may use a human-readable local renderer over the
same event records. It retains stable event classes, authoritative PostgreSQL
workflow/task/transition/selection/outcome evidence, and all ADR-0004
identifiers. W3C trace context is sanitized at API and Event Bus trust
boundaries. OpenTelemetry-compatible trace/metric semantics sit behind
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
| Accepted request explainable | Accepted mapping + workflow transaction including stored correlation | Logs/traces; request/workflow/correlation | Transient pre-acceptance correlation is not durable; audit failure rolls back | Commit/lost-response/replay/correlation tests |
| Workflow and broader grouping distinct | Workflow record and accepted correlation | `workflow_id` primary; `correlation_id` optional grouping; trace ID sampled path | Correlation proves no order, authority, idempotency, or outcome | Shared-correlation/retry/trace-restart tests |
| Transition auditable | Current state + transition history | Transition log/span; workflow/event IDs | Sampled trace cannot prove commit | Atomic transition tests |
| Agent selection explainable | Atomic ADR-0008 selection intent | Lookup logs/span; workflow/agent/revisions | Routes redacted; logs supplementary | Selection completeness tests |
| Command publication diagnosable | Command outbox + certainty state | Publish spans/metrics; message/attempt | Ack loss duplicates spans; payload excluded | Every outbox failure-window test |
| Duplicate delivery identifiable | Inbox/receipt + stable message ID | Redelivery metric and processing spans | Logs sampled; duplicate is expected | Redelivery/dedup tests |
| One Agent outcome provable | Completed receipt/outcome/event/outbox | Execution logs/spans; attempt/message | Execution telemetry can be lost | Competing outcome/crash tests |
| Late outcome correlated | Agent outcome + Orchestrator inbox/transition | Deadline/event spans; workflow/attempt | Clock skew; terminal state authoritative | Deadline-race tests |
| Transaction retry diagnosable | Final transaction result and durable records | Retry metric/log/span; transaction class | Attempts may be sampled; no SQL/binds | Retry/uncertainty tests |
| Registry staleness observable | Active revision + atomic selection evidence | Age/readiness metrics; agent/revisions | TTL false window; route redacted | Clock/mismatch tests |
| Trace context cannot change business validity | Valid API/message contract and durable domain IDs | Sanitized W3C context, spans, and links | Malformed/untrusted context ignored; platform sampling and trust policy win | External/internal trust-boundary tests |
| Telemetry loss cannot change correctness | Authoritative component persistence | Drop/failure/rate-limit counters and summaries | Ordinary buffers may lose data; first/change/recovery evidence preserved where rate limited | Exporter/queue/rate-limit outage tests |
| Business mutation auditable | Business/recovery state plus coupled audit in one transaction | Sanitized operational mirror | Never sampled or rate limited; audit failure rolls back mutation | Coupled mutation/disposition tests |
| Administrative action auditable | Durable administrative security audit and reconciliation evidence | Sanitized security log; actor/action classes | Never sampled; fail closed where safe; uncertain external effect remains unknown | Privileged failure/unknown-outcome tests |

### 46. Consequences

#### Positive Consequences

- Durable truth and operational diagnosis cannot be confused.
- Async duplicates, uncertainty, deadlines, and restarts are explainable.
- One-workflow lookup, broader logical grouping, and sampled trace diagnosis
  have unambiguous separate identities.
- Business mutations and administrative actions have explicit audit durability
  and uncertainty boundaries.
- Backend-neutral standards allow incremental adoption.
- Privacy and cardinality controls bound risk and cost.

#### Negative Consequences

- Consistent instrumentation and classification require discipline.
- Traces/logs remain incomplete and multiple stores may be consulted.
- Durable audit adds transactional and retention responsibility.
- External administrative effects may require prepare/apply/audit design and
  reconciliation ownership.
- Safe rate limiting and controlled label vocabularies require governance.
- Bounded telemetry intentionally loses some diagnostic detail.

#### Migration Impact

No implementation exists. Future instrumentation must preserve ports,
identities, redaction, and source-of-truth boundaries.

#### Developer Impact

Developers add stable classifications and safe context at boundaries, never log
payloads by convenience, and test telemetry failure independently of business
failure. They must preserve coupled audit transactions, trace-context trust
checks, bounded rate-limit fingerprints, and renderer-independent structured
records.

#### CI Impact

Fast tests use in-memory/no-op sinks; exporter, process, network, storage, and
clock behavior needs integration/resilience environments. No CI is assumed.

#### Operational Impact

Operators correlate durable records with several optional signal stores and
manage volume, drops, suppressed-event summaries, retention, partial readiness,
and unknown administrative outcomes requiring reconciliation.

#### Security Impact

Telemetry administration, routing, and security audit require least privilege,
protected configuration, trace-context trust controls, and fail-closed handling
for required evidence. Operational log severity does not replace security
classification.

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
| Correlation overclaims authority or grouping | `workflow_id` is primary; correlation is validated, scoped, nonunique, and nonauthoritative |
| Trace ID confused with workflow | Keep trace, workflow, and correlation identities distinct |
| Trace spoofing, amplification, forced sampling, or environment crossover | Authenticate internal producers; bound/sanitize external and internal context; platform policy wins |
| Redelivery creates misleading traces | New processing span linked to stable message context |
| Metric cardinality explosion | Label allowlist, controlled deployment vocabulary, bounded unknown fallback, and review |
| Sensitive leakage | Classification, allowlist, redaction, restricted capture |
| Excessive volume/cost | Sampling, deterministic safe rate limiting, bounded queues, and retention |
| Exporter blocks work | Timeouts, no-op/fallback, nonblocking bounded export |
| Queue exhausts memory | Hard bounds and drop counters |
| Sampling or aggregation hides failure | Durable audit, unsampled critical classes, first/change/recovery emission, and summary counts |
| Mutable audit | Additive corrections and integrity incident |
| Clock skew implies order | Scoped durable order and monotonic duration |
| Security rejection treated as application failure | Separate operational severity, durable security classification, and pattern-based alert severity |
| One health signal hides outage | Separate readiness layers |
| SDK types leak | Platform ports and adapter-local extensions |
| Backend lock-in | W3C/OTel-compatible semantics and replaceable exporters |
| Public operational IDs | Keep infrastructure context internal |
| SQL/payload leakage | Disabled by default and redaction tests |
| Business audit failure ignored | Commit mutation and coupled audit atomically or roll both back |
| Administrative audit/effect uncertainty hidden | Fail closed where safe; otherwise record unknown outcome and reconcile |
| Pipeline logs treated as audit | Require explicit policy designation and full authoritative-audit guarantees |
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
- [ ] `workflow_id` is the primary one-workflow key, `correlation_id` is an
      optional durable broader grouping, and trace ID is one operational trace.
- [ ] Client correlation format, validation/replacement, transient rejection
      use, atomic acceptance, replay, retry, propagation, and nonauthority are
      unambiguous.
- [ ] Multiple workflows may intentionally share one scoped correlation without
      making it unique or equating it to workflow identity.
- [ ] Correlation, message causation, authorization, idempotency, transaction
      outcome, and global ordering are distinct.
- [ ] API rejection, acceptance, replay, conflict, and response loss correlate.
- [ ] Event Bus context and adapter-only broker diagnostics are separated.
- [ ] External W3C context is bounded and sanitized; malformed context is not a
      business error, external sampling is advisory, and baggage is disabled.
- [ ] Internal Event Bus trace context requires an authenticated/authorized
      producer and cannot alter valid message/domain semantics.
- [ ] Trace spoofing, amplification, forced sampling, excessive `tracestate`,
      and cross-environment/security-context linking are prevented.
- [ ] Async publication, redelivery, duplicates, restart, and links are clear.
- [ ] Structured logging fields, taxonomy, serialization boundary, and severity
      are approved.
- [ ] Production/container JSON-compatible output and optional readable local
      rendering share the same pre-render fields, redaction, and severity.
- [ ] Metrics, label cardinality review, distributions, and latency semantics
      are approved.
- [ ] Deployment class is controlled, reviewed, never derived from arbitrary
      identities, and has a bounded unknown fallback.
- [ ] Workflow diagnosis identifies durable and lossy evidence.
- [ ] Persistence, Event Bus, outbox/inbox, Agent, Registry, and readiness
      signals preserve prior ADR semantics.
- [ ] Error and every retry category remain distinct; security impact is not
      automatically application-error severity.
- [ ] Sampling and deterministic rate limiting are distinct, and durable audit
      is never sampled, suppressed, or aggregated away.
- [ ] Rate limiting preserves first occurrence, material change, recovery,
      unique integrity evidence, bounded counts, and periodic summaries.
- [ ] Redaction, classification, restricted capture, and identifier privacy are
      explicit.
- [ ] Business-state-coupled audit shares the authoritative mutation transaction
      and rolls the mutation back on audit failure.
- [ ] Administrative security audit has required actor/source/action/target,
      revision, reason/approval, start/outcome/uncertainty, and reconciliation
      evidence without selecting a backend.
- [ ] Privileged actions fail closed where safe; uncertain external effects
      remain unknown until reconciled and are never reported prematurely.
- [ ] Operational and pipeline logs are not silently treated as authoritative
      audit.
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
