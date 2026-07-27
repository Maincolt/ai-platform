# ADR-0008: Capability Registry and Agent Discovery

- **Status:** Accepted
- **Date:** 2026-07-27
- **Supersedes:** None
- **Superseded by:** None

## Context

ADR-0002 assigns capability discovery to an Orchestrator-owned logical
Capability Registry. ADR-0004 defines the capability manifest as a versioned
configuration contract and defines exact message-contract compatibility.
ADR-0006 requires Agent readiness before a new workflow is created but lets an
equivalent accepted-request replay bypass current readiness. ADR-0007 defines
the Agent as a deployable capability executor and keeps first-slice capability
declaration configuration-backed.

Vertical Slice 01 needs one deterministic `text.word-count` Agent. It must not
gain a distributed registry, scheduler, heartbeat protocol, or service
discovery dependency merely to locate one configured deployment. The design
must nevertheless distinguish durable declaration from volatile readiness and
leave a safe evolution path to multiple deployments.

### Existing Documentation Alignments and Ambiguities

- ADR-0002 says Agents register manifests and availability information. Later
  documents define configuration as registration for Vertical Slice 01 and
  observe readiness separately. This is an unresolved mechanism ambiguity, not
  an ownership conflict. This ADR constrains the first slice to trusted
  configuration and defers Agent self-registration.
- ADR-0002's word "available" can mean declared, compatible, or currently
  ready. This ADR separates those meanings.
- ADR-0004's current manifest fields do not include every logical registry
  attribute requested here. Registry snapshot metadata and availability
  observations may supply those attributes; changing the portable manifest
  requires an explicit versioned contract change.
- ADR-0006 already requires durable selected-Agent information. This ADR adds
  the registry revision and compatibility evidence needed to explain that
  selection; it does not change workflow-state ownership.
- ADR-0007 permits one logical deployment to have multiple process instances.
  Process and consumer-group membership therefore cannot be registry
  deployment identity.
- Vertical Slice 01 contains older proposal/status wording for decisions that
  are now Accepted. That is a documentation alignment issue, not a registry
  architecture conflict.

## Decision Drivers

The decision prioritizes:

- deterministic, explicit capability and contract compatibility;
- prevention of dispatch to unsupported or untrusted deployments;
- fail-closed declaration, readiness, and staleness behavior;
- safe restarts, rolling deployments, and multiple Orchestrators;
- simple Docker, Windows, Linux, Unraid, and one- or two-machine operation;
- immutable revisions, provenance, auditability, and rollback;
- separation of declaration, discovery, availability, selection, scheduling,
  transport routing, and execution;
- bounded observations rather than unverifiable health claims;
- future multiple-deployment and dynamic-discovery evolution;
- least privilege and environment isolation;
- technology-neutral ports and no provider, framework, broker, or cloud
  lock-in; and
- tests that expose every freshness and compatibility failure window.

Correctness, simplicity, and explainability take priority over automatic
infrastructure discovery and load optimization.

## Decision

### 1. Capability Registry Definition

The Capability Registry is the Orchestrator-owned logical source used to
determine which logical Agent deployments are declared, compatible, permitted,
and sufficiently available candidates for a requested capability.

It is not architecturally a service-discovery platform, scheduler, load
balancer, health backend, configuration-management system, Agent runtime,
Event Bus topic, database table, Kubernetes resource, Python dictionary,
plugin directory, package index, or AI model registry. An adapter may use such
a mechanism after a future decision without changing the definition.

### 2. Registry Responsibilities

The Registry owns:

- loading or obtaining trusted capability declarations;
- capability, command-contract, and terminal-event compatibility evaluation;
- logical Agent deployment identity and declaration provenance;
- administrative enablement and derived dispatch eligibility;
- bounded availability observations and stale-state detection;
- complete declaration validation and conflict rejection;
- immutable configuration revision and generation tracking;
- deterministic compatible-candidate lookup;
- atomic snapshot activation, safe refresh, and rollback behavior;
- safe audit evidence and observability; and
- fail-closed behavior for missing, invalid, ambiguous, stale, or untrusted
  data.

It does not execute tasks, own workflow state, retry applications, route broker
partitions, own runtime work, autoscale resources, globally schedule work, load
code, select AI models/providers, or process task outcomes.

### 3. Capability Definition

A capability is a stable semantic unit of work. Its identity describes what
the platform asks to be done, not which implementation performs it.

A logical registry binding identifies at least:

- capability name and version;
- accepted command contract name and supported exact versions;
- produced terminal-event contract names and supported exact versions;
- logical Agent deployment `agent_id`;
- Agent implementation identity and version;
- deployment declaration revision or digest;
- complete Registry revision;
- trusted provenance and environment;
- administrative policy status;
- availability observation and observation time when applicable.

Optional, versioned metadata may describe input/output schema identity,
execution-risk class, concurrency or timeout guidance, resource profile,
side-effect and idempotency classification, dependencies, deprecation,
security/data classification, and locality. Optional metadata cannot grant
authorization, silently change portable contracts, or become a correctness
dependency without an accepted versioned decision.

Its initial treatment is:

| Metadata | Value and risk | Decision |
| --- | --- | --- |
| Input/output schema identity | Strengthens compatibility evidence but duplicates contract data if copied carelessly | Derive from accepted contracts initially |
| Risk, side-effect, and idempotency class | Useful for security review and future policy | Review metadata only; ADR-0007 remains authoritative |
| Concurrency, timeout, resource, and dependency guidance | Helps operations but varies by deployment and can become stale | Keep in validated deployment/Agent configuration, not candidate correctness |
| Deprecation and security/data classification | Directly affects permission and selection | Permit as trusted Registry policy metadata |
| Locality or placement | Enables optimization but risks becoming a scheduler and exposing topology | Deferred |

The identities remain distinct:

| Identity | Meaning |
| --- | --- |
| Capability | Stable semantic work and its independent version |
| Agent implementation | A software release that implements capabilities |
| Agent deployment | Stable logical target in one environment |
| Registry revision | Orchestrator-owned identity of one complete immutable Registry snapshot |
| Deployment declaration revision/digest | Identity of one trusted Agent deployment declaration and environment binding |
| Agent-loaded declaration identity | Proof of which deployment declaration the Agent process loaded |
| Process instance | Ephemeral runtime member of a deployment |
| Consumer group | Event Bus transport identity |

The complete Registry revision covers every declaration, deployment binding,
administrative policy, compatibility entry, and applicable selection-policy
configuration. An Agent neither loads nor interprets that global revision. It
loads its own trusted deployment declaration and reports or proves the
corresponding deployment declaration revision/digest through readiness. A
change elsewhere in the Registry can therefore change the Registry revision
without changing this deployment's declaration identity or readiness.
Process-instance identity remains telemetry only.

### 4. Capability Naming and Versioning

Capability names are lowercase, machine-readable, dot-separated semantic names
such as `text.word-count`. They do not embed repository, module, deployment,
vendor, model, or transport names.

Capability versions use `MAJOR.MINOR`:

- a major increment changes required semantics or compatibility;
- a minor increment is backward-compatible for the documented semantic
  contract; and
- implementation-only fixes change the Agent implementation version, not the
  capability version.

Compatibility is always declared and validated; syntax alone never proves it.
Aliases are absent initially. A rename creates a new capability identity, with
both identities declared during an explicit migration. Deprecation prevents
new selection only according to policy and does not erase historical support.
The capability owner approves semantic version changes; contract owners
independently version command and event contracts; implementation owners
version releases. These versions need not change together.

Full Semantic Versioning was rejected for capability identity because patch
releases describe implementation evolution, not semantic work. Major-only
integers cannot express compatible semantic additions. Declared ranges are
more flexible but add boundary and overlap ambiguity not needed by the first
slice. The bounded `MAJOR.MINOR` scheme aligns with repository contract
terminology while remaining independently governed.

### 5. Compatibility Model

Vertical Slice 01 requires:

- exact capability name and version `text.word-count` `1.0`;
- the requested command contract to be in the declaration's exact supported
  set;
- required terminal event contracts to be in the declared produced set;
- ADR-0004 exact-schema validation and conservative minor-version selection;
- a valid enabled declaration for the current environment;
- a sufficiently fresh ready availability observation; and
- satisfaction of security and local policy.

Capability major/minor compatibility is not inferred. Declared ranges may be
added in a later manifest version; the first slice uses exact capability
matching. A newer Agent processes an older command only when it explicitly
declares that exact contract version. An older Orchestrator uses a newer Agent
declaration only when it understands the manifest contract and finds an exact
compatible intersection. Unknown manifest fields or versions never grant
eligibility. Deprecated support may interpret existing work but is excluded
from new selection when policy says so.

### 6. Registry Source Models

| Model | Authority and strengths | Failure, scale, and decision |
| --- | --- | --- |
| Static configuration | Release/deployment configuration; simple revision, Git audit, startup validation, local operation | Restart-based freshness; selected initially |
| Database-backed | Durable shared queries and history | Creates another authority and bootstrap dependency; deferred |
| Event-driven registration | Agent publications can update many deployments | At-least-once, ordering, spoofing, bootstrap, expiry, and replay complexity; rejected initially |
| Direct self-registration API | Immediate explicit updates | Requires authentication, leases, conflict resolution, and API operation; rejected initially |
| Infrastructure discovery | Useful for network endpoints and process membership | Does not prove semantic capability, contracts, or authorization; adapter input only in future |
| Hybrid declaration/observation | Trusted static permission plus dynamic readiness | Selected conceptually: static declaration authority with bounded readiness observation |

Static configuration has no runtime bootstrap beyond trusted artifact delivery,
starts deterministically on every host, and is easy to reproduce and audit in
Git. Its staleness is revision staleness, handled by restart and rollout
coordination. Security follows release/configuration permissions. Multiple
instances converge by receiving identical bytes; future migration can replace
the loader port.

A database would centralize multi-instance reads, revision transactions, and
history, but startup would depend on that store and outages could block new
selection. It requires schema, ownership, backup, credential, and authority
rules. PostgreSQL already exists in the planned topology, but reuse alone does
not justify making Registry state database-authoritative.

Event registration and direct self-registration offer faster change and
natural multi-instance dissemination, but both need authenticated issuers,
leases/expiry, conflict arbitration, idempotency, revision assembly, audit,
restart reconstruction, and protection from partial views. Event delivery also
adds replay/order/bootstrap concerns. These costs exceed the first slice.

Infrastructure discovery can find changing endpoints across multiple hosts,
but infrastructure health and membership neither authorize semantic capability
nor prove contract support. A hybrid future model may use it only as an
observation/routing input beneath trusted declarations.

The first slice uses the hybrid concept without a dynamic registration system:
trusted versioned configuration declares permission and compatibility; a
technology-neutral readiness port supplies volatile availability.

### 7. First-Slice Configuration-Backed Registry

The deployment/release configuration is the authoritative source. The
Orchestrator owns loading, validation, indexing, and use of the complete
Registry revision. The capability and Agent implementation owners provide
reviewed declaration metadata; the deployment owner binds it to an environment
and `agent_id`, producing a deployment declaration revision/digest.

At startup the Orchestrator:

1. loads one complete trusted Registry revision;
2. validates its contract version, provenance, identities, bindings, and
   compatibility;
3. rejects duplicates and conflicts;
4. creates one immutable in-process snapshot; and
5. makes the Registry ready only when the snapshot is valid.

The snapshot is derived cache, not long-term authority. It is immutable for one
Orchestrator process. First-slice changes require restart. Every Orchestrator
instance receives the same immutable artifact and expected revision. Missing,
partial, conflicting, mismatched, or invalid configuration makes that instance
ineligible for new submissions. It may still serve persistence-backed query,
accepted-replay, conflict-resolution, and administrative operations when their
own dependencies are healthy, although the overall full-service readiness
signal may remain false. No partially valid subset is activated.

The Agent loads only its trusted deployment declaration and independently
validates that its code-owned capability metadata and deployment configuration
agree. It exposes the loaded declaration identity through the readiness
boundary. This check can make the Agent unready but cannot add or widen a
trusted Registry declaration. An unrelated declaration change does not make
the Agent unready when its own declaration digest and routing binding are
unchanged.

### 8. Declaration Ownership and Provenance

Responsibilities are:

| Actor | Responsibility |
| --- | --- |
| Capability owner | Semantic identity, behavior, and version evolution |
| Agent implementation owner | Supported implementation and contract evidence |
| Deployment owner/operator | Environment binding, `agent_id`, enable/disable, and trusted delivery |
| Orchestrator | Registry validation, compatibility, eligibility, and lookup |
| Release/deployment pipeline | Reproducible artifact revision and promotion evidence |

Provenance includes the complete Registry revision, each deployment declaration
revision/digest, release or source identity, deployment environment,
issuer/owner classification, and validation time.
Production distribution must be authenticated or otherwise trusted and
tamper-evident according to deployment policy; this ADR selects no signing
technology. An Agent cannot self-assert a new capability or make itself
eligible merely by being reachable.

### 9. Agent Deployment Identity

`agent_id` is unique within a platform environment and stable across process,
container, host, and Orchestrator restarts. Environment forms part of the trust
scope, not necessarily the portable identifier string. Development, test,
acceptance, and production bindings are distinct and cannot cross-register.

One deployment may expose several explicitly bound capabilities. Several
deployments may expose the same capability but use distinct `agent_id` values.
Multiple process instances of one deployment share its `agent_id`. Instances
that consume the same logical Event Bus subscription use that deployment
subscription's configured consumer-group identity. A deployment may support
multiple logical subscriptions in the future, each with separate transport
configuration. Hostname, container ID, process ID, IP address, Kafka member ID,
pod name, consumer-group name, and consumer-group member are never portable
deployment or capability identity.

### 10. Registry Data Model

The technology-neutral model contains logical records equivalent to:

- capability definition;
- Agent implementation declaration;
- Agent deployment declaration;
- capability-to-deployment binding;
- command/event contract compatibility;
- immutable registry revision;
- deployment declaration revision/digest and Agent-loaded declaration identity;
- trusted readiness-routing binding;
- volatile availability observation; and
- deprecation, disablement, and security-policy status.

Trusted configuration is authoritative for definitions, bindings, provenance,
and administrative policy. Runtime checks produce observations. Compatibility
and eligibility are derived. Lookup indexes and caches are disposable.
Operational timestamps and failure detail are metadata. Durable workflow/task
selection records provide historical audit. Static declaration and volatile
availability are never collapsed into one field.

The readiness-routing binding is trusted, environment-specific deployment
configuration associated with one `agent_id` and deployment declaration
digest. It contains adapter-owned target information plus indirect credential
and trust references, never raw secrets. It is validated before use, hidden
from workflow/domain logic, replaceable behind the availability adapter, and
grants neither capability permission nor contract compatibility.

### 11. Static Declaration Versus Dynamic Availability

Static declaration says what a deployment is intended, permitted, and
compatible to execute. Dynamic availability says whether it was recently
observed able to accept new work.

A healthy process cannot advertise an undeclared capability. A valid
declaration does not prove present readiness. Eligibility is derived from:

`valid declaration ∩ compatibility ∩ enabled policy ∩ environment/security
policy ∩ fresh readiness`.

Capacity may influence readiness only through the bounded rules below.
Transient health never changes capability identity or version.

### 12. Availability Model

The first-slice model separates:

- **Process liveness:** the Orchestrator process, event loop, and runtime are
  responsive.
- **Registry readiness:** one complete active Registry snapshot is loaded,
  valid, and queryable.
- **Core/API readiness:** required API and persistence dependencies plus a
  valid Registry snapshot support the full documented API. A Registry failure
  may make this full readiness signal false while safe persistence-backed
  retrieval, accepted replay, conflict resolution, health, and administration
  remain operational in a degraded mode.
- **New-submission capability eligibility:** candidate lookup finds at least
  one compatible, enabled, policy-permitted, fresh-enough deployment.
- **Deployment availability:** a bounded recent observation for one logical
  Agent deployment; it reserves no capacity and guarantees no execution.
- **Administrative status:** `enabled`, `disabled`, or `deprecated`, from
  trusted configuration.
- **Observed availability:** `ready`, `unavailable`, `draining`, `stale`, or
  `unknown`.
- **Derived eligibility:** `eligible` or `ineligible` for new dispatch.

Invalid declarations never enter an active snapshot. Disabled status is manual
and persists for its revision. Deprecated is release policy. Ready,
unavailable, draining, stale, and unknown are temporary observations.
Stale/unknown are ineligible. These are Registry operational concepts, not
public workflow states.

One unavailable Agent or ordinary short saturation does not make the
Orchestrator process dead or necessarily make the full API unready. Workflow
retrieval never depends on Agent readiness, and accepted replay never repeats
selection. Capability-level ineligibility is exposed independently from
process, Registry, and core/API readiness.

### 13. Availability Inputs

| Input | What it proves | What it does not prove | Initial use |
| --- | --- | --- | --- |
| Orchestrator readiness check | Configured target recently answered with compatible readiness | Future availability or capacity reservation | Selected |
| Agent health endpoint/port | Declared dependencies and execution service report ready | Trust, authorization, or successful next task | Selected behind a port |
| Event heartbeat | Recent publication | Capability correctness or consumer ownership | Not selected |
| Database heartbeat/lease | Writer recently updated state | End-to-end Agent readiness | Not selected |
| Deployment configuration | Permission and intended support | Runtime availability | Selected declaration authority |
| Readiness-routing binding | Where the availability adapter should observe one declared deployment | Capability permission, compatibility, or successful execution | Selected adapter configuration |
| Operator override | Administrative enable/disable intent | Process health | Selected configuration policy |
| Recent execution | Past success | Present readiness | Observability only |
| Consumer-group membership | Transport member exists | Correct capability, capacity, or permission | Not eligibility evidence |
| Outbox backlog | Publication pressure | Execution impossibility by itself | Diagnostic only |
| Dependency readiness | Required dependency was recently usable | Future call success | Included in Agent readiness |

No single signal proves liveness, readiness, capacity, compatibility,
authorization, and permission at once.

### 14. First-Slice Readiness Check

For a new submission, the Orchestrator initiates a bounded call through a
technology-neutral availability port to the configured logical `agent_id`.
The adapter may use an operational endpoint, but no HTTP framework or payload
shape is selected here.

The availability adapter resolves `agent_id` through its trusted
environment-specific readiness-routing binding. That binding is tied to the
expected deployment declaration digest and contains opaque adapter target
information and indirect credential/trust references. URLs, hosts, ports,
certificates, credential values, and protocol objects remain inside deployment
configuration and the adapter; they never enter portable commands, events,
workflow models, or capability code.

The check verifies the expected `agent_id`, Agent-loaded deployment declaration
identity, capability name/version, command support, terminal-event support,
non-draining state, and required Agent dependencies from ADR-0007. It does not
require the Agent to know the complete Registry revision. A missing or invalid
route, credential failure, identity/digest mismatch, wrong-environment target,
stale replacement route, unsupported declaration, timeout, invalid response,
or connection failure yields an unavailable/unknown observation and fails
closed. Reachability cannot create a Registry binding, widen capability or
contract support, or make an undeclared deployment eligible.

Results may be cached for a short configured TTL. The cache key includes
deployment, deployment declaration digest, readiness-routing identity,
capability/contract set, and environment. An unrelated Registry revision change
does not invalidate the observation when all of those values remain unchanged.
Equivalent accepted `request_id` replay bypasses readiness and current
selection. New requests with no eligible candidate return
`AGENT_TEMPORARILY_UNAVAILABLE` before workflow creation. Workflow retrieval
never checks Agent readiness. Already-dispatched work is resolved through
Event Bus, Agent recovery, and `task_result_deadline`, not Registry mutation.

### 15. Staleness and Expiry

Availability stores an observation time and uses local monotonic age for TTL
decisions. Wall-clock UTC may be retained for audit but does not establish
distributed order. A changed deployment declaration digest, environment
binding, readiness-routing identity, or reported Agent-loaded declaration
identity invalidates that deployment's observation immediately. A change to an
unrelated declaration changes the complete Registry revision but does not
invalidate this observation.

Orchestrator restart begins with no trusted availability cache. Agent restart,
crash, or network partition can produce a false-positive window no longer than
the TTL plus detection/clock margin. A failed refresh marks the observation
unknown or stale; it does not extend the old result indefinitely. A changed
deployment declaration/routing identity, process drain response, Agent-loaded
identity mismatch, or explicit disable invalidates cached readiness
immediately. An unrelated Registry revision change does not. Stale and unknown
fail closed for new dispatch.

### 16. Registration and Refresh Lifecycle

The lifecycle is:

1. load the complete trusted Registry revision and its deployment declarations;
2. validate structure, semantics, provenance, identity, environment, and every
   readiness-routing binding without exposing adapter details to domain logic;
3. reject duplicate, conflicting, unknown, or ambiguous declarations;
4. derive an immutable compatibility index;
5. initialize candidate availability as unknown and optionally start a
   nonblocking readiness observation;
6. expose Registry readiness and allow workflow queries independently of Agent
   readiness;
7. refresh an absent or stale observation on demand before a new submission;
8. invalidate observations by age, failure, deployment declaration/routing
   identity change, drain, or disablement;
9. apply configuration changes by process restart in the first slice;
10. stop new selection before safe declaration removal; and
11. construct one stable selection intent before workflow acceptance and
    record safe supplementary load, validation, observation, and change
    evidence.

Steps 1–6 are startup work, but Step 5 never blocks platform/API readiness on
the Agent. Steps 7–8 are runtime work. Optional background prewarming may
reduce latency but cannot extend TTL or change fail-closed semantics. Step 9 is
operator/restart based. Dynamic registration, leases, and push refresh are
future behavior. No partial revision becomes visible.

Selection is not complete at logging. Before entering the ADR-0006 workflow
submission transaction, the Orchestrator freezes the candidate, compatibility,
active Registry revision, deployment declaration digest, policy, and bounded
availability evidence into one stable selection intent. Section 26 defines its
atomic durability boundary.

### 17. Atomic Registry Revision

One validated immutable snapshot is activated atomically per revision. All
declarations validate before activation. Candidate lookup captures one
snapshot reference and cannot observe a mixture.

First-slice processes do not hot reload, so old and new snapshots can coexist
only across processes during a controlled rollout. They must not both accept
new submissions unless the rollout explicitly approves a backward-compatible
overlap. Otherwise the deployment coordinator removes the old revision from
submission traffic before activating the new revision. The Registry does not
pretend it can discover this deployment-wide fact by itself.

A submission uses exactly one revision from lookup through
workflow-acceptance intent; if its local revision changes or becomes invalid
before acceptance, it retries lookup or fails closed. A failed new revision
leaves already running processes on their prior valid snapshot, while instances
configured for the failed revision remain unready. Rollback redeploys a prior
trusted revision. The used revision is durably recorded with selection.

A Registry revision change caused only by an unrelated deployment does not
change an Agent's declaration identity or invalidate its readiness. A changed
binding, declaration digest, readiness route, environment, or applicable
selection policy does invalidate the affected candidate evidence. One
submission transaction uses one captured snapshot and one stable selection
intent; it never combines declarations from two revisions.

### 18. Multi-Orchestrator Consistency

In steady state, all first-slice Orchestrators use the same trusted revision.
Each validates locally and reports its active revision. Deployment readiness
and traffic coordination admit only the intended revision. A controlled
rolling overlap is permitted only when both revisions are explicitly approved
and backward-compatible; otherwise old-revision instances drain before the new
revision accepts submissions. Strong global consensus is unnecessary because
declarations are immutable and workflow acceptance is already transactional.

Availability observations may differ within the bounded TTL. This can change
whether an otherwise compatible new request is temporarily accepted, but
cannot permit an incompatible deployment. Concurrent submissions remain
protected by ADR-0004/ADR-0006 request idempotency. Each accepted selection
atomically records `agent_id`, complete Registry revision, deployment
declaration digest, and the same stable selection intent. Revision divergence
is observable; an unapproved old instance is drained through deployment
coordination rather than assumed to detect the new artifact. Cache warm-up
begins unknown.

### 19. Candidate Lookup

Lookup inputs are capability name/version, required command and event
contracts, environment, security/data policy, and required fresh availability.
It returns a deterministic canonically ordered set of compatible logical
deployments plus declaration, implementation, revision, policy, and
availability metadata.

The Registry does not publish commands, choose partitions, create workflows,
mutate workflow state, or execute tasks. Ordering makes results reproducible;
it is not the selection policy.

Lookup is evaluated against one captured Registry snapshot. Its result includes
the deployment declaration digest and readiness-routing identity needed to
validate availability evidence. Lookup does not create durable selection
evidence by itself.

### 20. Selection Policy Boundary

The Registry answers which candidates are declared, compatible, enabled,
policy-permitted, and sufficiently available. A separate Orchestrator selection
policy chooses one.

Vertical Slice 01 requires exactly one configured Test Agent candidate. Zero
candidates fails before workflow creation; more than one candidate is a
configuration error until a separate deterministic policy is configured and
versioned. Stable priority is the preferred first extension. Round-robin,
weighted, least-loaded, and locality-aware policies are not selected. The
selected target is logical `agent_id`, never a process instance.

After choosing the candidate, the Orchestrator constructs one stable selection
intent. If no workflow transaction committed, it may discard that intent,
re-evaluate current candidates, and construct a new intent as an explicit new
selection attempt. It must first resolve any unknown transaction outcome and
must not change the candidate or evidence inside a database transaction retry.

### 21. Multiple Deployments for One Capability

The model permits distinct `agent_id` bindings for equivalent implementations,
different implementation/contract versions, canaries, security/data policies,
and deprecation states. Capability-name equality alone does not make them
interchangeable. Environment boundaries are applied before candidate return.

Different deployments require distinct `agent_id` values. Multiple replicas of
one deployment share its `agent_id`. Instances consuming the same logical
subscription use that subscription's configured consumer-group identity; a
future deployment may have multiple logical subscriptions and transport group
identities. Registry ordering is deterministic, but a future selection policy
must explicitly choose among multiple eligible deployments.

### 22. Capacity and Load Information

Configured concurrency, active work, queue pressure, saturation, estimated
completion, and dependency limits are useful operational signals but are
stale, noisy, potentially sensitive, and prone to feedback oscillation.

Vertical Slice 01 uses no load-based selection and no capacity reservation.
ADR-0007 readiness/backpressure may mark sustained inability to serve new work
as unavailable, but ordinary saturation remains broker backpressure. Static
capacity guidance may be reviewed later; correctness never depends on volatile
load ranking.

### 23. Draining and Removal

Draining first makes a deployment ineligible for new selection. Existing
accepted workflows, commands, outcomes, and outboxes retain their recorded
`agent_id` and continue under ADR-0005 through ADR-0007. Declaration removal
does not cancel or mutate them, re-evaluate accepted request replay, suppress
late outcomes, or erase application-retry history.

Safe removal separates:

1. disable new selection;
2. let dispatched work and recovery horizons drain;
3. deprecate contract support;
4. stop processes; and
5. remove active declaration only after audit, retention, replay, and rollback
   requirements are satisfied.

Forced disable still preserves historical identity and may cause existing work
to reach its deadline. Invalid declarations never activate.

### 24. Version Upgrade and Rolling Deployment

Upgrades use expand-and-contract:

1. deploy backward-compatible implementation support;
2. publish a trusted declaration revision containing both old and new support;
3. verify new readiness;
4. permit selection under an explicit policy;
5. stop new selection of the old version;
6. drain existing work and replay horizons; and
7. remove old support in a later revision.

Implementation releases can change without capability changes when semantics
and contracts remain compatible. Capability minor/major and message contract
versions evolve independently. Dual-version declarations are explicit. Agent
and Orchestrator rolling upgrades need not be synchronized; every combination
must pass manifest-contract and compatibility checks. Rollback restores a
previous trusted revision without rewriting in-flight audit.

### 25. Registry Persistence

| Persistence form | Survival and audit | Authority decision |
| --- | --- | --- |
| Versioned configuration plus memory snapshot | Configuration survives process loss; availability is rebuilt | Selected authority/cache model |
| Durable database copy | Can query current/old revisions centrally | Optional derived diagnostic only; never authority initially |
| Append-only Registry history | Strong revision audit and reconstruction | Deferred until retention and privacy requirements justify it |
| Audit log only | Captures changes but cannot answer compatibility alone | Optional supplement to workflow audit |
| Volatile cache only | Simple but cannot restore declaration authority | Rejected as the sole source |

For Vertical Slice 01:

- versioned deployment configuration is authoritative;
- the validated in-memory snapshot and lookup indexes are derived caches;
- availability observations are transient and rebuilt after restart;
- no database-backed Registry authority or required Registry copy exists; and
- workflow/task selection records provide durable decision evidence.

An optional diagnostic copy must be clearly derived, include its source
revision, and never override configuration. A future durable registry or
append-only history requires a new ADR defining precedence, transactions,
retention, and recovery. Disaster recovery restores version-controlled
configuration plus workflow audit; it does not restore readiness cache.

### 26. Workflow Audit Integration

The accepted task/attempt selection durably retains:

- selected `agent_id`;
- capability name/version;
- Agent implementation identity/version;
- selected command and terminal-event contract versions;
- complete Registry revision;
- selected deployment declaration revision/digest;
- selection-policy identity/version;
- availability classification and observation time or evidence reference; and
- selection timestamp.

Before the ADR-0006 workflow submission transaction, the Orchestrator
constructs one immutable selection intent containing those values. The same
transaction atomically commits that intent with the accepted-request mapping,
workflow, task, task attempt, transition history, immutable selected command,
and Orchestrator outbox. A workflow, task, attempt, or command outbox record
must never exist without complete selection evidence.

Database transaction retry preserves the exact selection intent, including its
semantic selection time and readiness observation, even when that observation
ages during retry. The bounded retry is the same acceptance attempt.
Reselection is allowed only after a definitively uncommitted attempt is
abandoned, any unknown commit outcome is resolved, current candidates are
re-evaluated, and a new stable intent is created. Commit success followed by
API response loss resolves through the accepted-request mapping and returns the
stored selection without rerunning readiness or selection.

Volatile endpoint, hostname, process, consumer-member, partition, and raw
health detail are excluded. This evidence explains why the selection was
compatible without reconstructing a lost in-memory Registry. It does not make
the observation a guarantee that execution subsequently succeeded.
Logs and any optional Registry audit sink are supplementary; this atomic
workflow selection record is authoritative.

### 27. Event Bus Routing Relationship

Registry selection produces logical `agent_id` plus capability/contract
identity. The Event Bus adapter maps that target to deployment-owned transport
routing under ADR-0005.

Readiness routing is different: the availability adapter maps `agent_id` plus
deployment declaration digest to the trusted operational target used to
observe that deployment. Event Bus routing delivers `ExecuteTask`; readiness
routing performs a bounded observation. They may both be indexed by
`agent_id`, but have different protocols, credentials, failure behavior, and
adapter ownership.

Topic, partition, consumer-group name, broker host, and process membership are
adapter configuration and never domain identity. Routing may be configured by
deployment and indexed internally by `agent_id`, but portable contracts and
Registry domain queries do not expose broker topology. Readiness URLs, hosts,
ports, certificates, and trust material likewise remain adapter configuration.
Neither routing mapping grants a capability declaration or eligibility.

### 28. Failure Behavior

| Failure | New submission | Existing/recovery behavior |
| --- | --- | --- |
| Missing/invalid/partial configuration | Instance unready; fail closed | Queries and accepted replay remain available when persistence/API are usable |
| Duplicate/conflicting declaration or ambiguous compatibility | Reject entire revision | Prior valid process snapshot may continue during controlled rollback |
| Missing/invalid readiness route, credential failure, or wrong environment | Candidate unavailable/unknown; create nothing | Audit safe classification; correct trusted deployment configuration |
| Agent-loaded declaration identity mismatch or stale replacement route | Candidate ineligible; invalidate cached observation | Existing commands keep their recorded logical target and recover normally |
| Readiness timeout, stale result, or all unavailable | `AGENT_TEMPORARILY_UNAVAILABLE`; create nothing | Already-dispatched work continues to deadline/recovery |
| Revision changes during selection before transaction intent | Re-evaluate against one snapshot or reject | Never record a mixed revision |
| Observation ages during database transaction retry | Preserve the same stable selection intent | If committed, audit the original semantic selection time; reselection only after definitive noncommit |
| Crash after selection before transaction | Create no workflow records; select again on retry | No log or transient intent is authoritative |
| Commit succeeds but API response is lost | Resolve accepted `request_id` and return stored workflow/selection | Never rerun readiness or selection |
| Stale Orchestrator revision | Remove instance from submission readiness | It must not silently dispatch under old policy |
| Selected Agent fails after acceptance | No reselection of the same attempt | Event Bus recovery and `task_result_deadline` apply |
| Refresh failure | Mark observation unknown/stale | Do not extend readiness indefinitely |
| Dynamic observation contradicts declaration | Static permission wins; fail closed | Audit mismatch; operator action |

Equivalent accepted `request_id` replay returns the existing workflow without
Registry lookup. Conflicting replay still returns `REQUEST_ID_CONFLICT`.
Workflow retrieval remains available. Registry failure does not mutate
workflows or create application retries. Process liveness can remain healthy
and persistence-backed retrieval/replay can remain operational while Registry
or full core/API readiness is false. One unavailable deployment affects
capability eligibility, not process liveness. Ordinary short Agent saturation
does not flap the whole Orchestrator readiness signal.

### 29. Security and Trust

The Registry requires:

- trusted, authenticated or tamper-evident declaration delivery;
- least-privilege read and separate administrative change authority;
- exact manifest, provenance, identity, environment, and contract validation;
- no unauthorized Agent self-registration or capability widening;
- stable deployment identity and anti-spoofing checks on readiness;
- trusted readiness-routing bindings associated with `agent_id`, declaration
  digest, and environment;
- indirect credential/trust references with no raw secrets in routes;
- environment separation and explicit production enablement approval;
- restricted readiness endpoints and authenticated transport as appropriate;
- no secrets, credentials, private endpoints, or sensitive topology in
  portable declarations;
- audit of revision, enable, disable, deprecate, rollback, and selection; and
- protected access to operational availability and policy metadata.

Reachability, health response, consumer membership, or possession of an
`agent_id` does not establish trust or eligibility. This ADR selects no PKI,
signing service, identity provider, or secrets manager.

### 30. Observability

Without selecting a backend, signals include:

- Registry load, validation, activation, rollback, and active complete
  Registry revision;
- deployment declaration digest, Agent-loaded identity match, and
  readiness-routing validation;
- declaration, deployment, capability, and compatible-candidate counts;
- invalid, duplicate, conflicting, and deprecated declarations;
- availability classification, age, stale count, refresh latency, and failure;
- candidate lookup input classification, outcome, and no-candidate reason;
- selected deployment and selection-policy version;
- selection-intent construction and atomic workflow-acceptance disposition;
- revision mismatch and cache warm-up across Orchestrators;
- drain, disable, removal, and deprecated-version use; and
- readiness false-positive/negative evidence discovered later.

Safe context may include capability/version, `agent_id`, implementation
version, Registry revision, deployment declaration digest, selection-policy
version, availability class, and workflow/task identifiers. Process, Registry,
core/API, capability-eligibility, and deployment-availability signals are
reported separately. Credentials, routing targets, raw health bodies, private
endpoints, and sensitive topology are excluded by default. Logs never replace
the durable atomic selection record.

### 31. Local Development

Local operation supports one configuration-backed Test Agent declaration, one
or multiple Orchestrators on the same revision, and multiple Test Agent process
instances under one logical deployment. It supports controlled invalid,
unavailable, stale, mismatch, restart, and revision scenarios on Windows,
Linux, Docker, and Unraid.

Local deployment configuration supplies a readiness-routing binding for the
Test Agent without placing its host, port, or credentials in portable
contracts. Tests can replace the availability adapter target independently of
Event Bus routing.

Unit/component tests may use direct Registry domain objects, in-memory
configuration, controlled clocks, and fake availability ports. Contract tests
use real manifest fixtures. Process/integration tests use real Orchestrator and
Agent processes; Event Bus and persistence are included only when proving
selection-to-dispatch and durable audit behavior. No external discovery service
is required.

### 32. Testing Strategy

Tests align with `docs/testing/README.md` and cover:

- **Declaration:** valid, duplicate binding/identity, unsupported contract,
  malformed version, unknown capability, invalid environment, missing
  provenance, conflicting revision, and secret rejection.
- **Compatibility:** exact capability, compatible declared message minor,
  incompatible major, multiple contracts, deprecation, implementation upgrade,
  old Orchestrator/new Agent, and new Orchestrator/old Agent.
- **Loading:** success, missing/partial/invalid input, failed activation,
  immutable atomic replacement, rollback, and multi-Orchestrator mismatch.
- **Availability:** ready, unavailable, timeout, stale, restart, network
  partition, drain, saturation, dependency failure, declaration-digest change,
  unchanged digest across unrelated Registry revision, cache invalidation, and
  recovery.
- **Readiness routing:** missing/invalid route, credential failure, identity
  mismatch, wrong environment, stale replacement route, secret rejection, and
  separation from Event Bus routing.
- **Selection:** zero/one/multiple candidates, deterministic set, stable
  priority extension, unavailable/disabled candidate, and durable selected
  `agent_id` plus revision.
- **Failure:** configuration loss, all unavailable, post-dispatch failure,
  accepted replay and retrieval during Registry outage, rolling deployment,
  stale instance, and no partially accepted workflow.
- **Atomic selection:** crash after selection before transaction, commit then
  API-response loss, retry preserving identical evidence, observation becoming
  stale during retry, Registry rollout during concurrent submission, and no
  workflow/task/attempt/outbox without complete selection intent.
- **Readiness layers:** process live with unavailable capability, Registry
  invalid with safe query/replay degradation, one unavailable Agent, ordinary
  saturation, and independent Registry/core/capability/deployment signals.
- **Security:** unauthorized declaration, spoofed identity, untrusted readiness,
  environment crossover, restricted administration, and audit evidence.

Controlled clocks and immutable snapshots prove local age and atomic visibility.
Real process/network tests are required for restarts, network partitions,
multi-instance divergence, rolling deployment, and readiness false windows.
Unit tests do not prove those behaviors.

### 33. Technology Evaluation

| Option | Authority, consistency, and operation | Decision |
| --- | --- | --- |
| Versioned YAML or JSON configuration | Human/release managed, Git auditable, atomic artifact replacement, no service dependency | Selected technology category; exact serialization remains bounded implementation policy |
| Python configuration objects | Typed derived representation | Not authority; couples declaration to runtime and is unsuitable cross-component configuration |
| PostgreSQL Registry | Shared durable queries and transactional history | Existing infrastructure but would duplicate configuration authority and add migrations; deferred |
| Redis | Fast volatile/shared structures | Adds a service and authority/retention/security decisions without first-slice need; rejected |
| Consul | Service catalog, health checking, DNS, and distributed operation | Useful at larger dynamic scale but overlaps only runtime discovery and exceeds one/two-machine need |
| etcd | Consistent revisions, watches, leases, and coordination | Strong primitives but requires operating a distributed coordination store and designing the Registry atop it |
| Kubernetes API | Service/endpoint discovery and declarative objects | Couples the platform to Kubernetes and discovers runtime endpoints, not semantic permission |
| Event Bus compacted topic | Replicated revision stream and consumer reconstruction | ADR-0005 excludes this capability and it adds bootstrap, ordering, replay, and authorization complexity |
| Service mesh or DNS | Runtime reachability and endpoint abstraction | Does not prove capability, contracts, provenance, or permission |

Versioned YAML/JSON configuration has the smallest bootstrap and operational
surface for local Docker and Unraid. Whole-artifact replacement provides the
atomic boundary, Git/release history provides version and audit evidence, and
the same artifact can initialize multiple Orchestrators. Availability remains
a separate runtime observation, so file staleness is detected by revision
rather than health leases. Migration is through the Registry loader port.
The same trusted environment configuration category supplies readiness-routing
bindings, but their opaque targets and credential/trust references are consumed
only by the availability adapter and do not become Registry domain data or
portable contracts.

Python objects are useful validated runtime representations but cannot be the
cross-component or Git-owned authority. PostgreSQL could provide transactional
revision storage and multi-instance queries, but would introduce a second
authority unless configuration precedence were removed through a future ADR.
Redis provides shared low-latency data structures but adds durability,
replication, security, and revision semantics the Registry would still need to
design.

Consul combines a catalog, health checking, and distributed service discovery;
etcd supplies consistent revisions, watches, leases, and coordination. Both are
credible future substrates for dynamic observation, but each introduces a
cluster/bootstrap dependency, credentials, backup/upgrade operation, and a
mapping from infrastructure records to platform semantics. Their features
exceed the initial one- or two-machine requirement.

The Kubernetes API, service mesh, and DNS describe endpoints and runtime
membership but couple discovery to deployment topology and do not establish
capability permission or contract compatibility. An Event Bus compacted topic
could distribute revisions, but ADR-0005 does not select compacted Registry
state; reconstruction, ordering, authorization, and bootstrap would add another
consumer lifecycle. All rejected technologies could be adopted behind ports
after authority, consistency, and migration are decided.

No dedicated Registry service is selected. A versioned deployment-configuration
artifact is loaded through a technology-neutral port. YAML and JSON are both
viable serializations; choosing between them does not change authority,
revision, or validation and remains an implementation detail until the
manifest schema is introduced.

### 34. Registry Port Boundary

Technology-neutral capabilities remain explicit for:

- loading one trusted immutable Registry snapshot and revision;
- validating declarations, provenance, conflicts, and compatibility;
- finding deterministic compatible candidates;
- resolving and validating an adapter-owned readiness route for one declared
  `agent_id` and deployment declaration digest;
- observing one deployment's availability without exposing its route;
- invalidating stale observations;
- exposing the active revision and Registry readiness; and
- recording safe Registry and selection audit evidence.

These are not hidden behind a generic key-value interface because validation,
compatibility, staleness, and candidate semantics are domain behavior.
Workflow/domain logic never depends on YAML/JSON parsers, rows, HTTP clients,
health payloads, Kafka metadata, Kubernetes objects, Consul sessions, Redis
keys, or file paths.

### 35. Initial Vertical Slice Decision

Vertical Slice 01 uses:

- a versioned trusted configuration-backed Registry;
- one immutable fully validated snapshot per Orchestrator process;
- one declared Test Agent deployment and `text.word-count` `1.0`;
- distinct complete Registry revision, deployment declaration digest, and
  ephemeral process identity;
- exact capability matching and ADR-0004 exact declared contract support;
- restart-based Registry revision changes;
- one trusted readiness-routing binding behind a technology-neutral Agent
  readiness check with a bounded cache TTL;
- `ready`, `unavailable`, `draining`, `stale`, and `unknown` observations;
- fail-closed eligibility for new submissions;
- accepted-request replay and workflow queries independent of readiness;
- atomic selection intent committed with the accepted workflow, task, attempt,
  command, transition history, and Orchestrator outbox;
- distinct process, Registry, core/API, capability-eligibility, and
  deployment-availability signals;
- no database Registry authority, dynamic registration, heartbeat topic,
  service-discovery platform, load-based selection, or hot reload; and
- durable `agent_id`, capability/contract versions, implementation version,
  Registry revision, deployment declaration digest, selection-policy version,
  and bounded readiness evidence.

### 36. Coherent Capability Registry Architecture

The decision is:

- the Registry is the Orchestrator-owned compatibility and eligibility source,
  not a scheduler or service-discovery product;
- capability `MAJOR.MINOR`, message-contract, and implementation versions are
  independent and compatibility is explicitly declared;
- trusted deployment configuration is the initial authority;
- stable `agent_id` represents a logical environment-scoped deployment;
- the complete Registry revision and per-deployment declaration digests are
  distinct, and Agents report only their loaded declaration identity;
- one complete immutable Registry revision is validated and activated
  atomically;
- static permission and dynamic readiness are separate;
- trusted adapter-owned readiness routing enables bounded direct observation;
  reachability grants no permission and stale/unknown fails closed;
- steady-state Orchestrators use the same complete Registry revision, with only
  explicitly approved rolling overlap and bounded observation differences
  without consensus;
- Registry lookup returns a deterministic candidate set; the Orchestrator
  selection policy selects;
- the first policy requires exactly one configured eligible candidate;
- multiple deployments use distinct `agent_id` values; replicas share one;
- volatile load is not a selection input;
- drain stops new selection without rewriting accepted work;
- upgrades use expand-and-contract;
- configuration is authoritative, memory is cache, and the stable selection
  intent commits atomically with workflow acceptance;
- readiness routing and Event Bus routing are separate adapter concerns;
- equivalent request replay and workflow retrieval do not depend on Registry
  availability;
- process liveness, Registry readiness, core/API readiness, capability
  eligibility, and deployment availability remain distinct;
- declarations and readiness are least-privilege trust boundaries;
- observability and tests expose revision, compatibility, and freshness
  failures; and
- no dedicated Registry technology is required.

#### Guarantee and Failure-Window Evidence

| Guarantee | Authority and validator | Revision/identity | Failure window and fail-closed behavior | Durable evidence and proof |
| --- | --- | --- | --- | --- |
| Only declared capability is selectable | Trusted configuration; Registry validator | Registry revision, deployment declaration digest, capability, `agent_id` | Invalid/ambiguous revision never activates | Atomic selection record; declaration/conflict tests |
| Contract-compatible dispatch | Manifest support plus ADR-0004; Registry and command producer | Capability and exact command/event versions | Unknown version yields no candidate | Task contract fields and revision; cross-version tests |
| Atomic Registry view | Complete artifact; Orchestrator loader | Immutable revision | Partial/failed load exposes no new snapshot | Active-revision audit; partial/reload/rollback tests |
| Fresh-enough availability | Trusted readiness route, Agent-loaded identity, and Registry availability policy | `agent_id`, deployment declaration digest, route identity, observation age | Route/digest mismatch or stale/unknown is ineligible; false-positive bounded by TTL | Atomic selection evidence; controlled-clock, wrong-route, digest, and process/network tests |
| Multi-Orchestrator compatibility | Same deployment artifact; each Orchestrator | Complete Registry revision plus per-deployment digests | Unapproved Registry mismatch makes stale instance submission-unready; unchanged deployment digest can retain readiness | Workflow revision/digest audit; rolling/mismatch tests |
| Deterministic candidates | Active snapshot; Registry lookup | Revision plus lookup criteria | No runtime trial; ambiguity fails closed | Lookup/selection audit; ordering and multiple-candidate tests |
| Replay survives Registry outage | Accepted-request store; Workflow API | `request_id`, workflow identity | No Registry re-evaluation for accepted replay | Accepted-request record; outage replay tests |
| Atomic interpretable selection | ADR-0006 workflow transaction; Orchestrator | Stable intent with `agent_id`, capability/contracts, Registry/deployment/policy revisions | Pretransaction crash creates nothing; retry preserves intent; lost response resolves accepted mapping | Durable workflow/task/attempt/command/outbox evidence; crash/retry/lost-response/completeness tests |
| Reachability cannot grant permission | Trusted declaration and security policy; Registry | Environment and provenance | Spoofed readiness cannot add a binding | Safe security audit; spoof/environment tests |
| Readiness layers remain independent | Orchestrator operations and Registry/capability policies | Process, Registry, core/API, capability, and deployment signals | Agent outage blocks only affected new selection; Registry outage may degrade full readiness while query/replay continue | Operation records and metrics; unavailable-Agent, invalid-Registry, replay/query, and saturation tests |
| Routing boundaries stay separate | Trusted environment configuration; readiness and Event Bus adapters | `agent_id`, deployment digest, independent route identities | A missing readiness route makes the candidate unavailable; neither route changes declaration permission | Adapter boundary, wrong-route, secret, and Event Bus/readiness separation tests |
| Broker topology stays internal | Deployment routing config; Event Bus adapter | Logical `agent_id` | Missing route fails publication/operation, never changes identity | Command target and adapter diagnostics; boundary tests |

### 37. Consequences

#### Positive Consequences

- Compatibility, permission, readiness, selection, and routing are explicit.
- Global Registry identity, deployment declaration identity, and process
  identity cannot be conflated.
- Complete selection evidence cannot diverge from workflow acceptance.
- The first slice remains simple, Git-first, local, and reproducible.
- Immutable revisions make candidate decisions explainable and rollback safe.
- Future dynamic discovery can replace adapters without changing Registry
  semantics.

#### Negative Consequences

- Configuration changes require Orchestrator restart.
- Readiness caches necessarily permit bounded false positives and negatives.
- Multiple Orchestrators may temporarily disagree on availability.
- Operators must coordinate revision promotion and Agent readiness.
- Operators must maintain trusted readiness-routing bindings separately from
  Event Bus routing.
- Multiple-candidate scheduling remains deliberately limited.

#### Migration Impact

There is no Registry implementation to migrate. The initial implementation must
preserve the accepted manifest fields and introduce any richer declaration
metadata through a versioned configuration contract. Future dynamic or durable
sources must preserve authority, revision, audit, and fail-closed semantics.

#### Developer Impact

Developers must keep static declaration separate from observations, distinguish
Registry and deployment declaration revisions, construct stable selection
intent, use exact compatibility, and keep readiness/Event Bus routing types out
of domain code.

#### CI Impact

Fast tests can use immutable snapshots and fake readiness. Process, network,
restart, rolling-revision, and multi-Orchestrator behavior needs isolated
integration tests. No CI system is assumed.

#### Operational Impact

Operators promote one trusted revision, observe readiness age and revision
mismatch, drain before removal, and retain old declarations through replay
horizons.

#### Security Impact

Configuration promotion and readiness identity become security boundaries.
Unauthorized self-registration, environment crossover, and declaration
widening fail closed.

#### Future Review Triggers

Review or supersede this ADR when dynamic registration, multiple selection
policies, load-aware routing, hot reload, a durable Registry, cross-site
discovery, autoscaling, service discovery integration, or a production
declaration-signing policy becomes necessary.

### 38. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Stale Registry/readiness data | Immutable Registry revisions, bounded TTL, deployment-scoped identity invalidation, fail closed |
| Unrelated Registry change makes a healthy Agent unready | Key observations by deployment declaration and routing identity, not the complete Registry revision |
| Agent is required to understand global Registry revision | Compare Agent-loaded declaration identity with only the expected deployment digest |
| Incompatible Agent selection | Exact declared intersections and no syntax-only inference |
| Duplicate/conflicting declarations | Reject the complete revision |
| Unauthorized registration | Trusted source and no first-slice self-registration |
| Readiness false positive/negative | Bound cache window, observe it, and rely on post-dispatch deadline recovery |
| Missing, stale, or wrong-environment readiness route | Validate trusted route binding and declaration digest; fail candidate closed |
| Readiness reachability grants capability permission | Require trusted declaration and compatibility independently |
| Agent unavailable after dispatch | Preserve selected attempt; Event Bus/outcome/deadline recovery |
| Rolling deployment mismatch | Expected revision gate and durable revision audit |
| One stale Orchestrator dispatches | Remove mismatched instance from submission readiness |
| Load feedback oscillation | No load-based selection in the first slice |
| Configuration becomes hidden scheduler | Registry returns candidates; separate versioned policy chooses |
| Broker topology leaks into identity | Keep routing in Event Bus adapter |
| Dual-authoritative Registry | Configuration precedence; copies are explicitly derived |
| Capability and contract versions conflated | Model and record them independently |
| Removal breaks in-flight work | Disable, drain, retain history, then remove |
| Dynamic registration enables spoofing | Defer until authenticated protocol and lease ADR |
| Discovery service exceeds deployment need | Select no dedicated service |
| Registry outage blocks replay | Accepted replay and retrieval bypass Registry |
| Missing audit evidence | Persist `agent_id`, versions, Registry/policy revisions, and selection evidence |
| Selection log exists but workflow evidence does not | Commit one stable selection intent in the ADR-0006 workflow transaction; logs remain supplementary |
| Transaction retry silently changes selection | Preserve intent through retry; reselect only after definitive noncommit and unknown-outcome resolution |
| One Agent outage flaps the entire API | Separate deployment/capability eligibility from process, Registry, and core/API readiness |
| Environment crossover | Environment-scoped trust and validation |
| Stale `agent_id` reused incorrectly | Stable ownership, provenance, and no reassignment without explicit migration |

### 39. Assumptions

- ADR-0001 through ADR-0007 remain Accepted.
- Vertical Slice 01 has one configured Test Agent deployment and capability.
- Deployment configuration can be delivered identically to Orchestrator
  instances and identifies both the complete Registry revision and each
  deployment declaration digest.
- The Agent exposes bounded readiness through a technology-neutral adapter.
- Orchestrator persistence can retain selection audit fields.
- Clocks are sufficient for local age measurement but not distributed order.
- Dynamic registration, global scheduling, autoscaling, final topology,
  service discovery, monitoring, identity provider, and AI-provider routing
  remain unresolved.

### 40. Open Questions

These do not leave the core Registry model undecided:

1. What exact YAML or JSON manifest format and schema are used?
2. What exact digest or release identifier forms the Registry revision and
   each deployment declaration identity?
3. Where is deployment configuration mounted or injected?
4. What readiness timeout, cache TTL, and stale threshold fit measured startup
   and failure detection?
5. What stable priority and selection-policy version format supports the first
   multiple-deployment extension?
6. Which protected audit sink supplements durable workflow selection records?
7. What authenticated protocol eventually supports dynamic registration?
8. When does measured scale justify load-aware selection or durable Registry
   persistence?

### 41. Explicitly Out of Scope

This ADR does not decide global scheduling, autoscaling, dynamic placement,
Kubernetes deployment, service mesh, Agent marketplace, AI model/provider
registry, AI Router, prompt routing, workflow/application retry, task execution
lifecycle, cancellation/progress, broker topic/partition design, dynamic
plugins, secrets manager, monitoring backend, human approval, or side-effect
execution.

### 42. Acceptance Checklist

- [ ] Registry definition and Orchestrator ownership are approved.
- [ ] Registry responsibilities exclude scheduling, routing, and execution.
- [ ] Capability, implementation, deployment, complete Registry revision,
      deployment declaration, Agent-loaded declaration, process, and consumer
      identities remain distinct.
- [ ] Capability naming and independent version ownership are explicit.
- [ ] Exact first-slice compatibility and ADR-0004 contract rules align.
- [ ] Trusted configuration is the first-slice declaration authority.
- [ ] Declaration ownership, provenance, and environment trust are explicit.
- [ ] Stable deployment identity supports replicas and multiple deployments.
- [ ] Instances sharing a logical Event Bus subscription use its configured
      consumer group without making that group deployment identity.
- [ ] Static authority, observations, derived data, cache, and audit are
      separated.
- [ ] Administrative, observed, and derived availability states are distinct.
- [ ] Availability inputs state what they do and do not prove.
- [ ] Readiness checks are bounded, identity-aware, and independent of queries.
- [ ] Readiness routing is trusted adapter configuration associated with
      `agent_id`, deployment declaration digest, and environment, with indirect
      credential/trust references and no portable topology.
- [ ] Accepted-request replay bypasses current Registry selection.
- [ ] Monotonic age, deployment declaration/routing mismatch, and fail-closed
      staleness are approved without invalidating Agents for unrelated Registry
      changes.
- [ ] Load, validation, observation, refresh, invalidation, and audit lifecycle
      is complete.
- [ ] One complete immutable Registry revision activates atomically.
- [ ] Multi-Orchestrator consistency requires the same steady-state complete
      Registry revision, with controlled rolling overlap and no consensus.
- [ ] Candidate lookup is deterministic and does not perform selection.
- [ ] The first selection policy requires exactly one eligible candidate.
- [ ] One stable selection intent commits atomically with accepted request,
      workflow, task, attempt, history, command, and Orchestrator outbox.
- [ ] Transaction retry preserves selection intent; reselection requires
      definitive noncommit and a new explicit selection attempt.
- [ ] Multiple deployments use distinct `agent_id`; replicas share one.
- [ ] Correctness does not depend on volatile load.
- [ ] Drain, disable, removal, and historical identity retention are explicit.
- [ ] Rolling upgrade follows expand-and-contract without synchronized release.
- [ ] Configuration authority and nonpersistent observation/cache are approved.
- [ ] Durable workflow audit captures both Registry and deployment declaration
      identities and is authoritative over supplementary logs.
- [ ] Readiness routing and Event Bus routing remain distinct adapter concerns.
- [ ] Every failure preserves replay/query behavior and fails new selection
      closed where required.
- [ ] Least privilege, anti-spoofing, environment separation, and no secrets
      align with `SECURITY.md`.
- [ ] Observability is sufficient without selecting a backend.
- [ ] Process liveness, Registry readiness, core/API readiness, capability
      eligibility, and deployment availability are distinct.
- [ ] Local development needs no external discovery system.
- [ ] Tests distinguish in-memory proof from real process/network behavior.
- [ ] Dedicated Registry technologies are rejected for the initial scale.
- [ ] Registry ports expose domain semantics without infrastructure types.
- [ ] Reviewers confirm consistency with ADR-0001 through ADR-0007, Vertical
      Slice 01, testing guidance, `SECURITY.md`, and `AGENTS.md`.
- [ ] Every open question is bounded implementation or future-policy work.

## Related Decisions

- [ADR-0001: Core Design Principles](ADR-0001-core-design-principles.md)
- [ADR-0002: Platform Communication and State](ADR-0002-platform-communication-and-state.md)
- [ADR-0003: Runtime and Development Tooling](ADR-0003-runtime-and-development-tooling.md)
- [ADR-0004: API and Contract Standards](ADR-0004-api-and-contract-standards.md)
- [ADR-0005: Event Bus and Messaging Infrastructure](ADR-0005-event-bus-and-messaging-infrastructure.md)
- [ADR-0006: Persistence, State, and Recovery](ADR-0006-persistence-state-and-recovery.md)
- [ADR-0007: Agent Execution Model and Lifecycle](ADR-0007-agent-execution-model-and-lifecycle.md)

## References

- [Platform Architecture](../README.md)
- [Vertical Slice 01](../../implementation/vertical-slice-01.md)
- [Platform test strategy](../../testing/README.md)
- [Repository security policy](../../../SECURITY.md)
- [Repository Agent guidance](../../../AGENTS.md)
- [YAML 1.2.2 specification](https://yaml.org/spec/1.2.2/)
- [Consul service discovery](https://developer.hashicorp.com/consul/docs/discover)
- [etcd distributed key-value store evaluation](https://etcd.io/docs/v3.6/learning/why/)
- [etcd API revisions, watches, leases, and transactions](https://etcd.io/docs/v3.6/learning/api/)
- [Kubernetes Service and discovery](https://kubernetes.io/docs/concepts/services-networking/service/)
- [Redis data types](https://redis.io/docs/latest/develop/data-types/)
- [PostgreSQL JSON support](https://www.postgresql.org/docs/current/datatype-json.html)
- [Apache Kafka documentation](https://kafka.apache.org/documentation/)
