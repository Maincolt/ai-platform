# Platform Architecture

## Status

This document describes the intended logical architecture of AI Platform. It
defines responsibilities and boundaries without selecting implementation
technologies. Details will evolve through Architecture Decision Records under
`decisions/`.

## Architectural Goals

The platform coordinates specialized AI agents while keeping orchestration,
model access, communication, reusable capabilities, and operations separate.
The architecture is designed to:

- keep modules independently replaceable and evolvable;
- avoid coupling the platform to a provider or deployment environment;
- coordinate work through explicit, versioned contracts;
- make asynchronous collaboration observable and recoverable;
- allow agents and skills to be added without changing the platform core; and
- keep operational concerns outside domain behavior.

## System Context

At a high level, work enters the platform through the Orchestrator. The
Orchestrator coordinates the work by publishing and consuming events through
the Event Bus. Agents respond to relevant work, use Skills for focused
capabilities, and publish outcomes. AI-dependent operations pass through the AI
Router. Infrastructure provides the foundation on which all of these
components run.

```text
                         External requests
                                 |
                                 v
                    +-------------------------+
                    |      Orchestrator       |
                    +------------+------------+
                                 |
                    commands, facts, results
                                 |
                                 v
                    +-------------------------+
                    |        Event Bus        |
                    +------------+------------+
                                 |
                +----------------+----------------+
                |                |                |
                v                v                v
           +---------+      +---------+      +---------+
           |  Agent  |      |  Agent  |      |  Agent  |
           +----+----+      +----+----+      +----+----+
                |                |                |
                v                v                v
           +---------+      +---------+      +---------+
           | Skills  |      | Skills  |      | Skills  |
           +---------+      +---------+      +---------+

             Orchestrator and Agents request AI capabilities
                                 |
                                 v
                    +-------------------------+
                    |        AI Router        |
                    +-------------------------+
                                 |
                                 v
                    External AI capabilities

    +-----------------------------------------------------------+
    | Infrastructure supports execution, connectivity, state,   |
    | configuration, security, and operational visibility.      |
    +-----------------------------------------------------------+
```

The diagram represents logical relationships. It does not prescribe process
boundaries, network topology, deployment units, or communication technology.

## Core Components

### AI Router

The AI Router is the boundary between the platform and external AI
capabilities. It gives internal components a consistent contract without
exposing provider-specific behavior throughout the system.

Its responsibilities are to:

- accept requests expressed in platform terms;
- match requested capabilities and constraints to an available provider;
- translate requests and responses at the provider boundary;
- apply routing policies without embedding workflow decisions;
- normalize usage, error, and completion information;
- keep provider configuration and credentials isolated; and
- expose enough metadata for auditing and operational visibility.

The AI Router does not coordinate multi-step work or own agent behavior.
Provider selection must remain separate from domain and workflow logic.

### Orchestrator

The Orchestrator owns the lifecycle of collaborative work. It understands the
state of a workflow but delegates specialized execution to Agents.

Its responsibilities are to:

- accept and validate work requests;
- assign identifiers used to trace a workflow;
- represent work as explicit steps and state transitions;
- publish requests for agent capabilities through the Event Bus;
- react to progress, completion, and failure events;
- coordinate dependencies, timeouts, cancellation, and recovery;
- determine when a workflow is complete; and
- expose workflow status without taking ownership of agent internals.

The Orchestrator should contain coordination policy, not the specialized logic
that belongs to Agents or Skills. It must not rely on a particular agent
instance or on the implementation details of event consumers.

### Event Bus

The Event Bus is the communication boundary for asynchronous collaboration. It
allows producers and consumers to evolve independently by relying on documented
event contracts.

Its responsibilities are to:

- carry commands, facts, progress, results, and failure events;
- route events according to declared subscriptions;
- preserve contract metadata needed for correlation and causation;
- make delivery and processing outcomes observable; and
- support documented policies for retries, duplicates, ordering, and failure
  handling.

The Event Bus must not contain workflow or domain logic. Delivery guarantees,
retention, ordering, and recovery policies must be defined explicitly before
implementation.

### Agents

Agents are focused participants that own specialized behavior. Each Agent
responds to documented work contracts and publishes documented outcomes.
Specific Agents are intentionally not defined in this architecture.

An Agent is responsible for:

- declaring the capabilities and event contracts it supports;
- validating incoming work before processing it;
- performing one bounded area of responsibility;
- invoking Skills and AI capabilities through defined boundaries;
- publishing progress, results, and failures;
- handling duplicate delivery safely where the contract requires it; and
- remaining independent of the location and implementation of other Agents.

Agents should collaborate through the Event Bus rather than call one another's
internals. Shared behavior belongs in Skills or another deliberately defined
module, not in copied agent logic.

### Skills

Skills are reusable, focused capabilities that Agents can invoke. They reduce
duplication while keeping agent responsibilities readable.

A Skill is responsible for:

- performing a clearly bounded operation;
- defining its inputs, outputs, errors, and dependencies;
- avoiding hidden workflow state or orchestration decisions;
- remaining reusable across Agents where its contract permits; and
- exposing behavior that can be tested independently.

Skills are not autonomous workflow participants. An Agent owns the decision to
invoke a Skill and remains responsible for interpreting its result and
communicating through the Event Bus.

### Infrastructure

Infrastructure provides the operational foundation for every platform
component while remaining separate from platform behavior.

Its responsibilities include:

- providing execution environments and component connectivity;
- managing configuration and secret boundaries;
- providing state and durable data capabilities where required;
- supporting deployment, scaling, health management, and recovery;
- enabling logs, metrics, traces, and operational diagnostics; and
- expressing environments reproducibly through version-controlled
  definitions.

Infrastructure-specific choices must not leak into domain contracts. Environment
and provider differences should be isolated so that the logical architecture
remains portable.

## Collaboration Flow

A typical unit of work follows this logical sequence:

1. A request enters the Orchestrator and receives workflow and correlation
   identifiers.
2. The Orchestrator validates the request, records its state, and publishes a
   command describing the required capability.
3. An Agent subscribed to that contract accepts and validates the command.
4. The Agent performs its focused work, invoking Skills as needed.
5. If AI capability is required, the Agent or Orchestrator uses the AI Router
   rather than depending directly on an external provider.
6. The Agent publishes progress, completion, or failure facts through the
   Event Bus.
7. The Orchestrator updates workflow state and either requests further work,
   applies recovery policy, or completes the workflow.

Each transition must be traceable. No participant should require knowledge of
another participant's deployment location or internal design.

## Contracts and Event Behavior

Contracts are part of the architecture and must be documented before use.
Every event contract should define:

- a stable name and clear semantic purpose;
- an owner and intended producers and consumers;
- required payload fields and validation rules;
- event, correlation, and causation identifiers;
- creation time and contract version;
- compatibility and evolution rules;
- duplicate, ordering, retry, and timeout expectations; and
- failure and recovery semantics.

Commands express a request to perform work. Facts describe something that has
happened. Results and failures communicate outcomes. These meanings should not
be mixed because they imply different ownership and handling.

Consumers must assume duplicate delivery unless a contract explicitly
guarantees otherwise. Producers must not assume that an event has exactly one
consumer. Sensitive information should be excluded from events unless the
contract and security model explicitly require and protect it.

## Cross-Cutting Concerns

The following concerns apply across all components:

- **Observability** — Work must be traceable across asynchronous boundaries.
- **Security** — Inputs are validated, access is limited, and secrets stay
  outside events and source control.
- **Resilience** — Timeouts, retries, cancellation, and partial failure are
  explicit parts of workflow design.
- **Compatibility** — Contracts evolve without silently breaking producers or
  consumers.
- **Configuration** — Environment-specific values remain outside domain logic.
- **Testing** — Modules, contracts, and collaboration flows are independently
  verifiable.
- **Auditability** — Material requests, decisions, and outcomes retain enough
  context to be understood later.

## Architectural Boundaries

The following constraints preserve modularity:

- The Orchestrator coordinates work but does not absorb specialized agent
  behavior.
- The AI Router selects and adapts AI capabilities but does not own workflows.
- The Event Bus transports events but does not make domain decisions.
- Agents own specialized behavior but do not depend on other Agents' internals.
- Skills provide reusable operations but do not coordinate workflows.
- Infrastructure supports components but does not define their domain
  contracts.

Implementation choices that alter these boundaries, introduce a shared
dependency, or establish a platform-wide policy must be documented in an ADR.
