# Architecture Decision Records

This directory contains Architecture Decision Records (ADRs) for significant
technical and structural choices.

## Index

| ADR | Title | Status |
| --- | --- | --- |
| [ADR-0001](ADR-0001-core-design-principles.md) | Core Design Principles | Accepted |
| [ADR-0002](ADR-0002-platform-communication-and-state.md) | Platform Communication and State | Accepted |
| [ADR-0003](ADR-0003-runtime-and-development-tooling.md) | Runtime and Development Tooling | Accepted |
| [ADR-0004](ADR-0004-api-and-contract-standards.md) | API and Contract Standards | Accepted |
| [ADR-0005](ADR-0005-event-bus-and-messaging-infrastructure.md) | Event Bus and Messaging Infrastructure | Accepted |
| [ADR-0006](ADR-0006-persistence-state-and-recovery.md) | Persistence, State, and Recovery | Accepted |
| [ADR-0007](ADR-0007-agent-execution-model-and-lifecycle.md) | Agent Execution Model and Lifecycle | Accepted |
| [ADR-0008](ADR-0008-capability-registry-and-agent-discovery.md) | Capability Registry and Agent Discovery | Accepted |
| [ADR-0009](ADR-0009-observability-telemetry-and-audit-correlation.md) | Observability, Telemetry, and Audit Correlation | Accepted |
| [ADR-0010](ADR-0010-security-identity-authorization-and-trust-boundaries.md) | Security, Identity, Authorization, and Trust Boundaries | Accepted |
| [ADR-0011](ADR-0011-principal-scoped-api-idempotency-and-accepted-request-ownership.md) | Principal-Scoped API Idempotency and Accepted-Request Ownership | Accepted |
| [ADR-0012](ADR-0012-correlation-id-normalization.md) | Correlation ID Normalization | Accepted |
| [ADR-0013](ADR-0013-initial-broker-selection-apache-kafka.md) | Initial Broker Selection — Apache Kafka Instead of Redpanda | Accepted |
| [ADR-0014](ADR-0014-ai-router-and-first-ai-backed-agent.md) | AI Router and the First AI-Backed Agent | Accepted |
| [ADR-0015](ADR-0015-generic-capability-result-model.md) | Generic Capability Result Model | Accepted |
| [ADR-0016](ADR-0016-provider-call-claim-reconciliation.md) | Provider Call Claim Reconciliation | Accepted |
| [ADR-0017](ADR-0017-ai-router-follow-up-decisions.md) | AI Router Follow-Up Decisions and Multi-Agent Readiness Routing | Accepted |
| [ADR-0018](ADR-0018-software-team-persona-capabilities.md) | Software-Team-Persona Capabilities — Scope and First Candidate | Accepted |
| [ADR-0019](ADR-0019-ui-review-capability.md) | `ui.review` — a Playwright-Backed UI Review Capability | Accepted |
| [ADR-0020](ADR-0020-architecture-review-capability.md) | `architecture.review` — a Solution-Architect Review Capability | Accepted |
| [ADR-0021](ADR-0021-data-analysis-capability.md) | `data.analysis` — a Data-Analyst Review Capability | Accepted |
| [ADR-0022](ADR-0022-technical-review-capability.md) | `technical.review` — a Technical-Architect Review Capability | Accepted |
| [ADR-0023](ADR-0023-assignment-route-capability.md) | `assignment.route` — Team-Based Assignment Routing | Accepted |
| [ADR-0024](ADR-0024-submission-history.md) | Submission History — `GET /api/v1/workflows` | Accepted |
| [ADR-0025](ADR-0025-security-review-capability.md) | `security.review` — a Security-Reviewer Review Capability | Accepted |
| [ADR-0026](ADR-0026-autonomous-team-agents.md) | Autonomous Team Agents — Scrum Master, Product Owner, and Principal Developer Acting Without Human Approval | Accepted |

## Naming

ADRs are numbered sequentially and use descriptive names:

```text
ADR-NNNN-short-descriptive-title.md
```

Copy [ADR-template.md](ADR-template.md) when starting a new decision. Replace
`NNNN` with the next available four-digit number.

## Lifecycle

An ADR has one of these statuses:

- **Proposed** — under discussion and not yet binding
- **Accepted** — approved and currently governing the architecture
- **Deprecated** — retained for history but no longer recommended
- **Superseded** — replaced by a newer ADR
- **Rejected** — considered but not adopted

New ADRs begin as Proposed unless the decision has already been explicitly
accepted. Record the decision date when its status becomes Accepted.

## Process

1. Identify a decision with significant or difficult-to-reverse architectural
   consequences.
2. Copy the template and assign the next number.
3. Describe the context and constraints without assuming a preferred outcome.
4. State the decision and its boundaries precisely.
5. Record positive and negative consequences.
6. Summarize the meaningful alternatives considered.
7. Link related ADRs and documentation.
8. Add the ADR to the index in this file.

Accepted ADRs are immutable historical records. Correct minor errors without
changing the decision's meaning. Record material changes in a new ADR, mark the
earlier record as Superseded, and link the two records.
