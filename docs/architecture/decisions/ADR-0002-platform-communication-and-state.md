# ADR-0002: Platform Communication and State

- **Status:** Accepted
- **Date:** 2026-07-26
- **Supersedes:** None
- **Superseded by:** None

## Context

ADR-0001 establishes modular, event-driven communication as a core platform
principle. The platform architecture also defines the Orchestrator, AI Router,
Event Bus, Agents, Skills, and Infrastructure as separate logical
responsibilities.

Those documents intentionally leave several communication and state-management
questions unresolved:

- whether every cross-component interaction must use the Event Bus;
- how latency-sensitive AI requests are performed;
- which component owns workflow state and transitions;
- what delivery, ordering, retry, and replay semantics asynchronous messages
  provide; and
- how the Orchestrator discovers Agent capabilities without coupling itself to
  specific Agent implementations.

These choices affect component contracts, failure handling, recovery,
observability, and testability. They must be defined before an implementation
technology is selected.

## Decision

The following decisions are proposed as a single communication and state model.

### 1. Asynchronous Component Collaboration

The Event Bus is used for asynchronous commands, facts, results, and lifecycle
events exchanged between loosely coupled components.

Producers publish against explicit message contracts and do not depend on the
location, instance count, or implementation of consumers. Consumers subscribe
to contracts they support and communicate outcomes through further messages
rather than through knowledge of producer internals.

### 2. Synchronous AI Router Contract

The AI Router exposes a synchronous request-response contract. It may be
invoked by the Orchestrator and by authorized Agents.

The contract must define request and response models, authorization,
validation, timeouts, cancellation, error semantics, and version compatibility.
Callers depend on the platform contract rather than on any external AI
provider's interface.

### 3. Exceptional Direct Component Communication

Direct component communication is exceptional but permitted for platform
services where a request-response interaction or immediate state access is
required. Examples include:

- the AI Router;
- the workflow state store; and
- the secrets provider.

Every direct interaction must use an explicit, versioned contract. It must also
define authorization, timeout, failure, compatibility, and observability
behavior. A component must not use direct communication to bypass event
contracts for ordinary asynchronous collaboration.

### 4. Workflow State Ownership

The Orchestrator owns workflow execution state. It defines the workflow state
model, valid transitions, concurrency rules, and lifecycle from creation
through completion, failure, or cancellation.

No other component may mutate workflow execution state except through a
contract owned by the Orchestrator.

### 5. Durable External Workflow State

Workflow state is persisted in a durable state store external to the
Orchestrator's execution process.

Infrastructure provisions and operates the state capability. The Orchestrator
owns the stored workflow model and all state transitions. Infrastructure must
not embed workflow semantics, and persistence-specific details must not leak
into Agent or event contracts.

### 6. At-Least-Once Delivery

The initial delivery model for asynchronous messages is at-least-once. A
message may therefore be delivered or processed more than once.

Successful processing must be acknowledged according to the eventual Event Bus
contract. A missing acknowledgement may result in redelivery.

### 7. Idempotency, Deduplication, and Correlation

Consumers must be idempotent for the message contracts they handle.

Messages must contain stable identifiers that support deduplication and
correlation. The common message metadata must include at least:

- a stable message identifier;
- a correlation identifier for the wider workflow or request;
- a causation identifier linking a message to its direct cause;
- a contract name and version; and
- the workflow or aggregate identifier when one applies.

The required deduplication scope and retention period must be defined by the
message contract or platform policy.

### 8. Partition-Scoped Ordering

Ordering is guaranteed only within an explicitly defined workflow or aggregate
partition key.

No global ordering guarantee is provided. Contracts that depend on ordering
must identify their partition key and describe how consumers handle missing,
late, or out-of-order messages.

### 9. Bounded Retries and Dead-Letter Handling

Failed asynchronous processing must support bounded retries. After the retry
policy is exhausted, the message and relevant failure context must move to
dead-letter handling.

Retry policies must define the attempt limit, delay behavior, retryable failure
categories, and observability requirements. Dead-letter handling must support
diagnosis and an explicit disposition such as correction and redelivery,
compensation, or abandonment. It must not create an unbounded automatic retry
loop.

### 10. Audit, Recovery, and Safe Replay

Events support audit and recovery by preserving durable facts about workflow
execution. Replay may be used to rebuild derived state or recover processing
when the relevant contracts permit it.

Replay must not blindly repeat irreversible side effects. A replay mechanism
must distinguish state reconstruction from command execution and must apply
idempotency, side-effect guards, compensation, or explicit operator approval
where necessary.

### 11. Capability Registry Ownership

Capability discovery is initially owned by the Orchestrator through a logical
Capability Registry.

The Registry represents available capabilities and their compatibility without
requiring the Orchestrator to know Agent internals or deployment locations. It
is a logical responsibility; this ADR does not prescribe its deployment or
storage model.

### 12. Agent Capability Registration

Agents register versioned capability manifests and availability information
with the Capability Registry.

A capability manifest must identify the Agent, supported capability and
contract versions, relevant constraints, and compatibility metadata.
Availability information must allow the Orchestrator to exclude Agents that
cannot currently accept work. Registration does not grant authorization by
itself.

## Alternatives Considered

### Use the Event Bus for Every Interaction

All communication, including AI requests and state access, could be modeled as
asynchronous messages. This would maximize consistency of communication style,
but it would add coordination and latency to request-response services and make
immediate error and cancellation semantics more complex.

### Use Synchronous Calls Between All Components

Components could call one another directly for commands and results. This would
be simple for small workflows but would introduce temporal coupling, reduce
failure isolation, and make independently evolving Agents harder to operate.

### Allow Uncontracted Direct Service Access

Components could use platform services through implementation-specific
interfaces. This was rejected because it would leak infrastructure and provider
details across module boundaries and prevent independent evolution.

### Let Infrastructure Own the Workflow State Model

Infrastructure could define and manage workflow records as part of the state
capability. This was rejected because workflow transitions are orchestration
domain behavior, not an infrastructure responsibility.

### Keep Workflow State Inside the Orchestrator Process

The Orchestrator could retain workflow state only in its own execution memory.
This was rejected because process restarts, relocation, and concurrent
execution would risk losing or diverging workflow state.

### Require Exactly-Once Processing

The platform could require every asynchronous message to be processed exactly
once. This was rejected as an initial contract because it would create a
stronger guarantee than the platform can safely assume across component and
side-effect boundaries. At-least-once delivery with explicit idempotency makes
duplicate handling visible.

### Guarantee Global Message Ordering

All messages could share a single total order. This was rejected because most
workflows require ordering only within their own boundary, while global
ordering would unnecessarily couple unrelated work and constrain scalability.

### Retry Until Processing Succeeds

Failures could be retried indefinitely. This was rejected because permanent
failures would consume resources, obscure incidents, and block controlled
recovery.

### Replay Every Event as Original Work

Recovery could reprocess all historical messages without distinguishing facts
from commands or side effects. This was rejected because irreversible external
actions could be repeated.

### Decentralized Capability Discovery

Agents could discover one another or advertise capabilities without an
Orchestrator-owned registry. This was rejected for the initial model because it
would distribute selection policy and make workflow planning, compatibility,
and availability harder to reason about.

## Consequences

### Positive

- Asynchronous collaboration remains loosely coupled and resilient to
  temporary component unavailability.
- The AI Router supports direct request-response semantics without exposing
  provider-specific interfaces.
- Workflow ownership is clear even though persistence is externally
  provisioned.
- At-least-once delivery makes duplicate handling an explicit and testable
  consumer responsibility.
- Partition-scoped ordering avoids coupling unrelated workflows.
- Bounded retries and dead-letter handling make permanent failures observable
  and recoverable.
- Replay can support audit and state recovery without treating every historical
  message as a new instruction.
- A logical Capability Registry gives the Orchestrator a consistent discovery
  model without defining specific Agents.

### Negative

- The platform must support and operate both asynchronous and synchronous
  communication contracts.
- Consumers require deduplication and idempotency logic.
- Workflow transitions and event publication require a defined consistency
  strategy to avoid lost or duplicated outcomes.
- Partition keys become part of message-contract design and must remain stable.
- Dead-letter operations require retention, diagnosis, access control, and
  redelivery procedures.
- Safe replay requires side-effect classification and additional safeguards.
- The Capability Registry introduces availability, freshness, and version
  negotiation concerns.
- Direct service contracts can become coupling points if exceptions are not
  governed carefully.

## Open Questions

- What common message envelope and schema-governance process will be used?
- What are the default retry limit, delay policy, and retryable failure
  categories?
- How long are deduplication records, workflow events, and dead-letter messages
  retained?
- How are dead-letter messages corrected, authorized for redelivery, or
  permanently disposed?
- How are workflow state transitions and outbound message publication kept
  consistent across partial failures?
- What concurrency control is required when more than one Orchestrator
  execution attempts to advance the same workflow?
- Which workflow or aggregate identifier supplies the partition key for each
  message family?
- What timeout, cancellation, and retry rules apply to synchronous AI Router
  requests?
- How is authorization granted to Agents that invoke the AI Router or other
  direct platform services?
- How does the Capability Registry determine that availability information has
  expired?
- How are incompatible capability-manifest versions negotiated?
- Which side effects require compensation or operator approval before replay?
- What audit data must be retained, redacted, or access-controlled?

## Implementation Implications

- Define a versioned common envelope for asynchronous messages before
  publishing the first event contract.
- Define separate versioned request-response contracts for each permitted
  direct platform service.
- Model workflow state and valid transitions within the Orchestrator boundary,
  independent of the state-store implementation.
- Make state restoration and workflow resumption part of Orchestrator
  validation.
- Provide consumer conformance tests for duplicate delivery, idempotency,
  ordering, retries, and dead-letter outcomes.
- Require producers and consumers to propagate message, correlation, causation,
  contract-version, and partition metadata.
- Make retry attempts, dead-letter transitions, state transitions, capability
  registration, and synchronous service calls observable.
- Define replay modes that separate projection rebuilding from side-effecting
  command execution.
- Define a versioned capability-manifest contract and availability lifecycle.
- Keep Event Bus, state, secrets, and AI provider implementations behind
  configuration and platform-owned contracts.
- Validate failure behavior across state persistence, message publication, and
  process interruption before declaring workflow recovery supported.

## Related Decisions

- [ADR-0001: Core Design Principles](ADR-0001-core-design-principles.md)

## References

- [Platform Architecture](../README.md)
- [Repository guidance](../../../AGENTS.md)
