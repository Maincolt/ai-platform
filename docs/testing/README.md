# Test Strategy

## Purpose

AI Platform uses layered testing to verify modules, contracts, asynchronous
workflows, infrastructure definitions, and complete user outcomes. Tests should
find failures at the smallest useful boundary while preserving enough
higher-level coverage to validate collaboration between components.

This strategy is technology-neutral. Test frameworks and supporting tools must
be selected only when implementation requirements are known and the choice is
documented.

## Execution Categories

Every test must belong to one of these execution categories.

### Local Tests

Local tests run without access to shared or third-party services. They use
in-process implementations, fakes, stubs, fixtures, or isolated dependencies
started and owned by the test run.

Local tests must:

- run without production credentials or confidential data;
- be deterministic and repeatable;
- avoid dependence on execution order or persistent shared state;
- clean up resources they create; and
- fail with enough context to diagnose the affected boundary.

### External-Service Tests

External-service tests communicate with a separately operated platform service,
provider, or deployed environment. They may require network access,
credentials, quotas, or billable resources.

External-service tests must:

- be opt-in and clearly identified;
- use isolated, non-production environments and least-privilege credentials;
- document required services, configuration, data, and cleanup;
- tolerate only explicitly documented provider variability;
- prevent secrets and sensitive payloads from appearing in output; and
- report when they were not run rather than silently implying coverage.

No automated continuous-integration test workflow is currently configured.
Contributors must record which local and external-service tests they ran, and
which relevant tests they could not run, in the pull request.

## Test-Level Matrix

| Test level | Local coverage | External-service coverage |
| --- | --- | --- |
| Unit | Required; isolated logic only | Not applicable |
| Component | Required with controlled boundaries | Used only to verify a real backing service or deployment boundary |
| Contract | Required for schemas, compatibility, and fixtures | Used when verifying a separately operated provider or service |
| Workflow | Required with controlled Agents and services | Used for deployed multi-component workflows |
| Integration | Used with test-owned or simulated dependencies | Required for real external integrations |
| Infrastructure | Static and structural validation | Planning, provisioning, upgrade, and recovery validation |
| Resilience and retry | Deterministic fault injection | Real delivery, restart, and outage behavior |
| Security | Input, authorization, policy, and leakage checks | Live environment and external-boundary validation |
| End-to-end | Optional when a complete isolated platform can run locally | Required for representative deployed-system validation |

External-service coverage complements local coverage; it must not replace fast,
deterministic tests of platform-owned behavior.

## Unit Tests

Unit tests verify one function, class, policy, or state transition in isolation.
They should cover:

- normal behavior and boundary values;
- validation and explicit error paths;
- workflow state transitions;
- routing and selection policies;
- idempotency decisions;
- retry and timeout calculations; and
- security-sensitive allow, deny, and redaction rules.

Unit tests are always local. Network, filesystem, clock, randomness, provider,
and persistence dependencies should be controlled where they affect
determinism.

## Component Tests

Component tests verify a complete module through its public interface while
keeping dependencies controlled. They confirm that internal parts collaborate
correctly without depending on another platform component's implementation.

Component tests should cover each component's:

- public inputs, outputs, and failure modes;
- configuration and startup validation;
- authorization boundary;
- state and lifecycle behavior;
- observability metadata; and
- behavior when dependencies are unavailable or return invalid data.

The baseline component suite runs locally with test-owned substitutes. A
component test becomes an external-service test when it connects to a service
not created and isolated by that test run.

## Contract Tests

Contract tests verify compatibility at module boundaries without requiring a
complete workflow. They apply to asynchronous messages, synchronous platform
services, capability manifests, configuration, and external integrations.

Contract tests should verify:

- required fields, types, and validation rules;
- semantic meaning of commands, facts, results, and lifecycle events;
- contract and capability version compatibility;
- stable message, correlation, causation, and partition identifiers;
- backward-compatible evolution and rejection of unsupported versions;
- error, timeout, and cancellation responses; and
- representative producer and consumer fixtures.

Schema and fixture validation runs locally. Verification against a separately
operated provider or service is external-service testing and must remain
opt-in.

## Workflow Tests

Workflow tests verify Orchestrator-owned execution state and collaboration
across a sequence of commands, facts, results, and lifecycle events.

They should cover:

- successful multi-step execution;
- branching, cancellation, timeout, and failure transitions;
- duplicate, late, and out-of-order messages;
- Agent unavailability and capability-version mismatch;
- restart and workflow resumption;
- correlation and causation across the complete workflow; and
- safe handling of irreversible side effects during recovery.

Workflow tests run locally when the Event Bus, state capability, AI Router, and
Agents are controlled by the test. Tests against deployed instances are
external-service tests.

## Integration Tests

Integration tests verify that two or more real boundaries work together. Their
scope must be narrower than an end-to-end test and identify the specific
integration being exercised.

Examples include:

- Orchestrator persistence through the workflow state contract;
- asynchronous publication and consumption through the Event Bus contract;
- authorized AI Router request-response behavior;
- Agent registration with the Capability Registry; and
- provider adapters translating platform contracts.

Integration tests may run locally when all dependencies are isolated and owned
by the test environment. Tests that call shared, hosted, or third-party
services are external-service tests and require explicit configuration.

## Infrastructure Validation

Infrastructure validation checks version-controlled definitions without
assuming a particular infrastructure tool.

Local validation should cover:

- formatting and structural correctness;
- required variables and safe defaults;
- environment separation;
- secret references without secret values;
- least-privilege intent;
- portability and platform boundaries; and
- consistency between definitions and documentation.

External-service validation covers environment planning or provisioning,
connectivity, persistence, health checks, upgrades, rollback, backup, restore,
and cleanup. It must use an isolated non-production target and document any
resources or costs it can create.

## Resilience and Retry Tests

Resilience tests verify the communication and state guarantees defined by the
architecture and ADRs.

Local deterministic tests should cover:

- at-least-once delivery and duplicate processing;
- consumer idempotency and deduplication;
- partition-scoped ordering;
- bounded retries and retry classification;
- transition to dead-letter handling;
- timeout and cancellation propagation;
- partial failure between state persistence and message publication;
- process interruption and workflow recovery; and
- event replay that does not repeat irreversible side effects.

External-service resilience tests validate the same expectations against
deployed messaging, state, and service boundaries, including restart and
temporary outage behavior. Fault injection must remain isolated from production
systems.

## Security Tests

Security tests should verify:

- authentication and authorization at trust boundaries;
- least-privilege access for Agents, services, and credentials;
- input validation and contract enforcement;
- secret redaction from events, prompts, logs, traces, errors, and images;
- prompt injection and untrusted input handling;
- safe treatment of external AI provider input and output;
- human approval gates for destructive or irreversible actions;
- dependency and container-image security expectations; and
- denial of unauthorized direct platform-service access.

Policy, validation, and redaction tests should run locally. Tests requiring live
identity systems, provider accounts, deployed networks, dependency services, or
container registries are external-service tests. Such tests must follow
[SECURITY.md](../../SECURITY.md) and must not use production secrets.

The repository does not currently configure a security test or scanning tool.

## End-to-End Tests

End-to-end tests validate a small set of critical outcomes across the complete
deployed platform. They should confirm:

- request acceptance and authorization;
- orchestration and workflow-state persistence;
- capability discovery and Agent execution;
- AI Router access when the workflow requires it;
- event correlation and operational visibility;
- successful completion and result delivery; and
- controlled failure, recovery, and cancellation.

End-to-end tests are not a substitute for lower-level coverage. They should be
few, outcome-focused, isolated, and traceable.

An end-to-end test can run locally only when the complete required platform is
started and owned by the local test environment. Tests against any separately
deployed environment or external AI provider are external-service tests.

## Test Data and Isolation

- Use synthetic, minimal data by default.
- Never place credentials, customer data, or confidential production content
  in tests or fixtures.
- Give each test run isolated identifiers, state, and resources.
- Do not depend on test execution order.
- Make time, randomness, and failure injection controllable where practical.
- Clean up external resources even after failure, and document manual recovery
  when automatic cleanup cannot be guaranteed.

## Adding or Changing Tests

Place tests alongside the module or under `tests/` according to the project
layout established for that implementation. Keep test ownership aligned with
the boundary being validated.

When behavior or a contract changes:

1. update the lowest-level tests that express the intended behavior;
2. update affected component and contract fixtures;
3. add workflow or integration coverage when collaboration changes;
4. update external-service coverage when a real boundary is affected; and
5. document the validation performed and any remaining gaps.

Framework selection, test commands, naming conventions, and automation should
be documented when they are introduced. This document does not select them.
