# Sprint 6 Team Consilium

> Review scope: Vertical Slice 01, Phase 6 — concrete PostgreSQL and
> Kafka-protocol adapters, local deployment, runtime lifecycle, and recovery.

## Principal architecture review

The merged Phase 2–5 interfaces were insufficiently transaction-shaped for the
failure windows already accepted in ADR-0005, ADR-0006, and Vertical Slice 01.
Sprint 6 therefore makes the existing persistence boundary asynchronous and
expresses the required submission, Agent outcome, terminal outcome, deadline,
access-audit, inbox/outbox, and recovery units explicitly. This is an
implementation correction within the accepted architecture, not a new
architecture decision.

Current Capability Registry state governs only new selection. Already accepted
work completes from its durable selection and command evidence even if the
current Registry artifact is missing, invalid, or changed. Platform startup and
workflow queries remain independent of Test Agent startup.

## Persistence workstream

The Psycopg 3 adapters use component-owned schemas and complete database
transactions. Submission arbitration, terminal handling, inbox/audit evidence,
deadline expiry, Agent deduplication/outcome/outbox, and publication recovery
are atomic at their documented boundaries. Retry is bounded and limited to
failures whose commit outcome is known not to have succeeded. The database
uses separate migration and runtime permission roles for the Orchestrator and
Agent, with no committed login credentials.

## Event Bus and runtime workstream

The public port exposes logical channels, immutable bytes, keyed routing,
opaque delivery handles, and bounded certainty; it does not expose Kafka
topics, partitions, offsets, or clients. The adapter uses only the ADR-0005
Kafka subset. Workers preserve outbox identity and bytes, manually advance
source progress only after durable handling, quarantine bounded safe rejection
records, reconcile crash windows, and fail closed when recovery is incomplete.

The runtime validates typed configuration, secret-file references, schema
compatibility, canonical message schemas, Registry/deployment declarations,
and readiness identity. It keeps Agent availability out of core platform
readiness and uses bounded lifecycle/shutdown coordination.

## QA position

Broker-free tests can verify adapter configuration, exact message preservation,
state machines, error classification, bounds, and composition. They cannot
verify real PostgreSQL isolation/locking, Kafka delivery or rebalance behavior,
ACL enforcement, persistence across service restart, or deployment networking.
Those claims require the isolated real services defined by Phases 6 and 7.

## External gates

ADR-0005 requires repository-owner license compliance review before Redpanda
implementation or deployment. The current host also has no usable Docker,
Podman, `nerdctl`, native PostgreSQL, Kafka, or Redpanda service. Accordingly:

- no Redpanda image, Compose service, or Redpanda-specific security artifact is
  added before owner approval;
- no real-service result is inferred from mocks;
- Sprint 6 remains in progress; and
- Phase 7 and the demonstrated Phase 8 procedures remain gated.

## Team conclusion

Complete all safe local implementation and quality gates, commit the coherent
Sprint 6 checkpoint, and ask the repository owner for the two explicit actions
recorded in [progress.md](progress.md). Do not create `done.md` or a QA sign-off
until the deployment and real-service evidence exist.
