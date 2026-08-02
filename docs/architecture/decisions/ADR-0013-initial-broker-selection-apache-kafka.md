# ADR-0013: Initial Broker Selection — Apache Kafka Instead of Redpanda

- **Status:** Accepted
- **Date:** 2026-08-02
- **Supersedes:** ADR-0005 (broker selection only — Section 3 and the
  "Redpanda Community Edition as the preferred initial self-hosted broker"
  clause of its Section 22 Decision)
- **Superseded by:** None

## Context

ADR-0005 selected a technology-neutral, Kafka-protocol Event Bus port and
named Redpanda Community Edition as the preferred initial self-hosted broker,
explicitly conditioned on repository-owner license compliance review: "The
planned self-hosted use does not offer Redpanda as a commercial streaming or
queuing service to third parties; license compliance must be confirmed before
implementation or deployment." ADR-0005 Section 26 (Open Question 8) leaves
"who records the required Redpanda Community Edition license compliance
review" unresolved, and Section 24 lists that review as a standing risk.
Section 22 also retains Apache Kafka as "the tested protocol-compatible
alternative" for exactly this situation, and Section 1000 ("Future Review
Triggers") names "Redpanda license terms or required features no longer fit
the project" as an explicit trigger to revisit this decision.

Sprint 6 (Vertical Slice 01, Phase 6) needs to stand up a local
PostgreSQL/broker Compose topology now to validate the concrete Event Bus
adapter built in this sprint (`src/ai_platform/adapters/event_bus/`) against
a real broker, per `docs/sprint-6/progress.md`. The Redpanda BSL review has
not been completed. A usable container engine is confirmed available on this
host (Podman 6.0.2, WSL-backed machine, verified with a working container
pull/run), which resolves the other Sprint 6 environment prerequisite
independently of this decision.

The repository owner decided in this session to proceed with Apache Kafka as
the initial self-hosted broker rather than block Sprint 6 validation on the
pending Redpanda license review.

## Decision

The initial self-hosted broker for local development, CI, and the first
deployed topology is **Apache Kafka**, run in KRaft combined broker/controller
mode for local and single-machine use, instead of Redpanda Community Edition.

This decision changes only the broker product named in ADR-0005 Section 3
and Section 22. It does not change any other part of ADR-0005:

- the technology-neutral Event Bus port (ADR-0005 Section 4);
- the Kafka-protocol capability allowlist (ADR-0005 Section 2), which Apache
  Kafka satisfies natively as the reference implementation;
- `confluent-kafka` as the selected Python client (ADR-0005 Section 21);
- logical channels, physical naming, partitioning, delivery, retry,
  quarantine, retention, security, and observability requirements (ADR-0005
  Sections 5–18);
- the transactional outbox, inbox, and Agent result-publication model
  (ADR-0005 Sections 12–13); or
- the testing strategy (ADR-0005 Section 20), except that the containerized
  broker used for local integration, resilience, and end-to-end tests is now
  Apache Kafka rather than Redpanda.

Redpanda remains a documented, protocol-compatible alternative. If the BSL
review is later completed and approved, re-adopting Redpanda as a deployment
option is a configuration and image-pin change to the topology, not a
contract or adapter change, but still requires the full migration
verification in ADR-0005 Section 3 (conformance, ACL/identity recreation,
and resilience testing) before cutover — Kafka-compatibility is not assumed
to be interchangeable without that verification.

## Consequences

### Positive

- Removes the Redpanda BSL license-review dependency as a blocker for Sprint
  6 validation and the first local deployment.
- Apache Kafka is the reference implementation of the Kafka protocol; the
  existing `confluent-kafka`-based adapter and Section 2 capability allowlist
  require no code change.
- Apache-2.0 licensing removes any future commercial-use or source-available
  license review for the broker itself.
- Broadest available ecosystem, documentation, and long-term operational
  history among the evaluated options.

### Negative

- Local and single-machine deployments now carry Kafka's JVM and KRaft
  operating model, which ADR-0005 Section 3 identified as added local
  overhead relative to Redpanda's single binary.
- Loses Redpanda's smaller resource footprint and simpler single-container
  administration for the initial local stack.
- Any future move to Redpanda (or a managed Kafka-compatible service) still
  requires the full conformance and cutover work in ADR-0005 Section 3; nothing
  about today's choice is free to reverse.

## Alternatives Considered

### Wait for the Redpanda license review before proceeding

Rejected for this sprint. The review has no committed owner or timeline
(ADR-0005 Open Question 8), and blocking Sprint 6's real-broker validation
indefinitely on it is a worse outcome than using the already-approved
protocol-compatible alternative that ADR-0005 itself reserved for this case.

### Deploy Redpanda without completing the license review

Rejected. ADR-0005 makes license compliance a precondition of implementation
or deployment, and AGENTS.md requires explicit repository-owner approval
before treating a licensing question as resolved. Proceeding without that
review would violate both.

## Related Decisions

- [ADR-0005: Event Bus and Messaging Infrastructure](ADR-0005-event-bus-and-messaging-infrastructure.md) — partially superseded (broker selection only)
- [ADR-0006: Persistence, State, and Recovery](ADR-0006-persistence-state-and-recovery.md)

## References

- [Sprint 6 Progress](../../sprint-6/progress.md)
- [Apache Kafka KRaft operations](https://kafka.apache.org/42/operations/kraft/)
- [Apache Kafka Docker images](https://kafka.apache.org/42/getting-started/docker/)
