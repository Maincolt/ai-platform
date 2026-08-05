# PROJECT_BRIEF.md — AI Platform

> Last updated: 2026-08-05 | Sprint 8 | Status: Done

> **Note on terminology:** the roles in Section 6 are a *virtual contributor
> team* used to plan and execute sprints in this repository. They are not the
> platform's own architectural "Agents" (Orchestrator, Event Bus, AI Router,
> Agents, Skills — see [docs/architecture/README.md](docs/architecture/README.md)),
> and they are not defined under [agents/](agents/). This file is a
> sprint-coordination artifact, not an Architecture Decision Record.

## 1. Project Overview

AI Platform is a foundation for coordinating specialized AI agents through
modular boundaries and event-driven communication (see
[README.md](README.md)). Thirteen Accepted ADRs govern the first
deterministic vertical slice. Phases 1–6 are merged: concrete persistence,
Event Bus, runtime, and local-deployment boundaries are implemented and
validated against real PostgreSQL and Apache Kafka. Phase 7 is partially
complete: a deliberately scoped subset of its real-service test matrix is
automated (see [docs/sprint-7/done.md](docs/sprint-7/done.md)).

## 2. Platform Concept

The platform's logical architecture ([docs/architecture/README.md](docs/architecture/README.md))
separates:

- **Orchestrator** — owns workflow lifecycle and state transitions.
- **Event Bus** — asynchronous, contract-based communication boundary.
- **Agents** — focused participants that own specialized execution.
- **AI Router** — the boundary to external AI providers/capabilities.
- **Skills** — reusable, focused capabilities Agents invoke.

The first proof of this architecture is
[Vertical Slice 01: Deterministic Single-Agent Workflow](docs/implementation/vertical-slice-01.md) —
a complete, deterministic (no AI model, no external side effect) workflow
path: submit → persist → dispatch → execute (`text.word-count`) → recover →
disclose. It is specified in eight implementation phases. Phases 1–6 are
merged: concrete adapters and the local deployment are implemented and
validated against real services. Phase 7 (isolated integration/recovery/
security/end-to-end suites) is partially complete — a scoped automated
subset (Event Bus delivery, Concurrency, Security boundary, Recovery/crash
window) is done; the remainder of its Section 19 matrix has not started.
Phase 8 (verified operational documentation, [docs/operations/README.md](docs/operations/README.md))
is done, completing the eight-phase plan with that Phase 7 caveat carried
forward.

## 3. Tech Stack

- **Language/runtime:** Python, CPython 3.14 (`requires-python = ">=3.14,<3.15"`) — [ADR-0003](docs/architecture/decisions/ADR-0003-runtime-and-development-tooling.md)
- **Dependency/environment management:** uv (one root `pyproject.toml`, committed `uv.lock`)
- **Build backend:** Hatchling
- **Source layout:** `src/ai_platform/` (single regular package; see package tree below)
- **Formatting/linting:** Ruff
- **Static typing:** BasedPyright (Pyright-family strict mode), pinned via `uv.lock`
- **Testing:** pytest (unit, contract, component, integration, end-to-end layout — [docs/testing/README.md](docs/testing/README.md))
- **Contracts:** JSON Schema Draft 2020-12, OpenAPI 3.1.1, AsyncAPI 3.0.0 — [ADR-0004](docs/architecture/decisions/ADR-0004-api-and-contract-standards.md)
- **API framework:** FastAPI + Pydantic v2, Uvicorn (ASGI server) — verified CPython 3.14 compatible per [ADR-0003](docs/architecture/decisions/ADR-0003-runtime-and-development-tooling.md)
- **Request fingerprinting:** `rfc8785` (RFC 8785 JSON Canonicalization Scheme) + SHA-256
- **Persistence:** PostgreSQL with component-owned schemas, accessed through Psycopg 3 — [ADR-0006](docs/architecture/decisions/ADR-0006-persistence-state-and-recovery.md)
- **Event Bus:** Kafka-protocol adapter using `confluent-kafka`; local deployment uses Apache Kafka as the initial broker — [ADR-0005](docs/architecture/decisions/ADR-0005-event-bus-and-messaging-infrastructure.md), [ADR-0013](docs/architecture/decisions/ADR-0013-initial-broker-selection-apache-kafka.md)
- **Deployment:** Docker-based, cloud-agnostic, with Unraid as a first-class target — [infrastructure/README.md](infrastructure/README.md)

Sprint 6 replaced the in-memory runtime boundary with concrete asynchronous
PostgreSQL and Kafka-protocol adapters, and validated the deployment and
real-service behavior end to end. See [docs/sprint-6/done.md](docs/sprint-6/done.md).
Sprint 7 automated a scoped subset of that real-service validation as an
opt-in `external_service` pytest suite (`tests/integration/`). See
[docs/sprint-7/done.md](docs/sprint-7/done.md).

## 4. Architecture

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
```

Current package tree for `src/ai_platform/` (established across Sprints 1–6):

```text
src/
└── ai_platform/
    ├── api/                   # Workflow API and in-memory component-test composition
    ├── orchestrator/
    │   ├── domain/            # Sprint 2: Workflow aggregate, value objects
    │   ├── registry/          # Sprint 3: Capability Registry (declarations, snapshot, availability, selection)
    │   └── application/       # Sprint 3: submission/terminal/deadline application services
    ├── agents/
    │   ├── domain/            # Sprint 4: Agent-owned outcome/receipt/event-outbox records
    │   └── test_agent/        # Sprint 4: the built-in text.word-count capability and lifecycle
    ├── contracts/             # Contract package boundary; canonical artifacts remain under root contracts/
    ├── ports/
    │   ├── event_bus/
    │   └── persistence/       # Capability and transaction-shaped durable ports
    ├── adapters/
    │   ├── event_bus/          # Kafka-protocol producer/consumer, health, topics, quarantine
    │   └── persistence/        # Psycopg 3 component adapters
    ├── runtime/                # Process composition, configuration, workers, health and lifecycle
    └── shared/                 # Cross-boundary identifiers, messages, outcomes and operational signals
        ├── configuration/
        └── logging/
```

## 5. Key Files Map

| Area | Path | Contents |
|------|------|----------|
| Contributor guidance | [AGENTS.md](AGENTS.md) | Repository-wide philosophy, standards, ADR process |
| Contribution workflow | [CONTRIBUTING.md](CONTRIBUTING.md) | Branch/PR workflow, ADR process, testing/review expectations |
| Platform architecture | [docs/architecture/README.md](docs/architecture/README.md) | Logical components, contracts, boundaries |
| ADRs | [docs/architecture/decisions/](docs/architecture/decisions/) | 13 Accepted ADRs (0001–0013), governing all implementation |
| First implementation plan | [docs/implementation/vertical-slice-01.md](docs/implementation/vertical-slice-01.md) | 8-phase plan for the first deterministic workflow |
| Test strategy | [docs/testing/README.md](docs/testing/README.md) | Local vs. external-service test levels |
| Platform agents (architecture) | [agents/](agents/) | Placeholder — populated after Phase 3+ (Orchestrator/Registry/Test Agent) |
| Skills (platform capabilities) | [skills/](skills/) | Placeholder — reusable Agent capabilities |
| Infrastructure | [infrastructure/](infrastructure/) | Sprint 6 image, migrations, PostgreSQL role definitions, and the full local Compose deployment topology (`compose/`) |
| Scripts | [scripts/](scripts/) | Placeholder — dev/validation/deploy utilities |
| Tests | [tests/](tests/) | Unit, contract, and component suites; real-service integration/E2E suites remain Phase 7 |
| Sprint docs | `docs/sprint-N/` | Plans, progress, done, and consilium notes per sprint |
| Source | `src/ai_platform/` | Domain, application, API, adapter, runtime, port, Agent, and shared modules |

## 6. Team Roles (Sprint 6)

| Agent | Name | Role | Focus this sprint |
|-------|------|------|--------------------|
| Principal coordinator | **Codex** | Architecture reconciliation, integration, QA, handoff | Phase 6 scope and Accepted-ADR alignment |
| Persistence workstream | **Erdos** | PostgreSQL transactions, migrations, recovery, grants | Component-owned durable boundaries and semantic validation |
| Runtime workstream | **Herschel** | Runtime composition, readiness, lifecycle, Event Bus integration | Independent startup, bounded processing, safe shutdown |
| Consumer workstream | **Descartes** | Architecture review and consumer lifecycle | Assignment fencing, rebalance behavior, and acceptance review |

Frontend/visual roles remain unneeded. A DevOps/deployment engineer should
be introduced starting with the sprint that implements Phase 6
(adapters/deployment).

## 7. Sprint Status

| Sprint | Name | Status | Scope |
|--------|------|--------|-------|
| 0 | Architecture | ✅ Done | ADR-0001–0012 (Accepted), platform architecture doc, Vertical Slice 01 plan |
| 1 | Tooling and Canonical Contracts | ✅ Done | Vertical Slice 01 **Phase 1** only: root tooling metadata + canonical JSON Schema/OpenAPI/AsyncAPI contracts. No domain behavior. See [docs/sprint-1/done.md](docs/sprint-1/done.md). |
| 2 | Workflow Domain and Persistence Ports | ✅ Done | Vertical Slice 01 **Phase 2** only: five-state `Workflow` aggregate, accepted-request arbitration, task/attempt, transition history, audit, inbox/outbox/receipt records, 7 persistence `Protocol` ports. Pure domain code, no adapters. See [docs/sprint-2/done.md](docs/sprint-2/done.md). |
| 3 | Orchestrator and Capability Registry | ✅ Done | Vertical Slice 01 **Phase 3** only: configuration-backed Capability Registry, submission-transaction orchestration, terminal event processing, deadline reconciliation, one recovery query port. Registry built via a parallel background sub-agent. See [docs/sprint-3/done.md](docs/sprint-3/done.md). |
| 4 | Test Agent | ✅ Done | Vertical Slice 01 **Phase 4** only: the built-in `text.word-count` capability, receipt-first idempotency lifecycle, capability/input validation, readiness boundary. Includes an architectural correction moving shared/Agent-owned types out of `orchestrator/domain/`. See [docs/sprint-4/done.md](docs/sprint-4/done.md). |
| 5 | Workflow API | ✅ Done | Vertical Slice 01 **Phase 5** only: submit/read/health HTTP operations, trusted synthetic context, ADR-0012 correlation normalization, RFC 8785 fingerprinting, Problem Details. Composed over in-memory reference ports (explicitly non-production). See [docs/sprint-5/done.md](docs/sprint-5/done.md). |
| 6 | Concrete Adapters and Local Deployment | ✅ Done | Vertical Slice 01 **Phase 6** only: concrete PostgreSQL/Kafka adapters, runtime process composition, application image, and a local PostgreSQL + Apache Kafka Compose topology, validated end-to-end (submission, crash recovery, assignment fencing, quarantine) against real services. Apache Kafka replaces Redpanda as the initial broker per [ADR-0013](docs/architecture/decisions/ADR-0013-initial-broker-selection-apache-kafka.md). See [docs/sprint-6/done.md](docs/sprint-6/done.md). |
| 7 | Integration, Recovery, Security, and End-to-End Tests | ✅ Done (partial, scoped) | Vertical Slice 01 **Phase 7**, a deliberately chosen subset: an automated, opt-in `external_service` pytest suite (49 tests) covering Event Bus delivery, Concurrency, Security boundary, and Recovery/crash window against the real Sprint 6 topology — not the complete Section 19 matrix. See [docs/sprint-7/done.md](docs/sprint-7/done.md). |
| 8 | Verified Operational Documentation | ✅ Done | Vertical Slice 01 **Phase 8**: [docs/operations/README.md](docs/operations/README.md) — setup, health, query, recovery, troubleshooting, shutdown/cleanup, contract-generation status, security limitations, and validation commands, every one independently re-run against the real local environment during this sprint. No production-readiness claim. Completes the eight-phase Vertical Slice 01 plan (with the Phase 7 scope caveat above carried forward). See [docs/sprint-8/done.md](docs/sprint-8/done.md). |

## 8. Current State

**What works:**
- Repository-wide contributor guidance ([AGENTS.md](AGENTS.md), [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md)).
- Complete platform architecture description and 13 Accepted ADRs.
- A fully specified, ADR-aligned implementation plan for the first vertical slice.
- Root tooling metadata (`pyproject.toml`, `uv.lock`) and the `src/ai_platform/` package skeleton (ADR-0003), validated locally with `uv sync`, Ruff, BasedPyright (strict), and pytest.
- Canonical contracts under `contracts/`: JSON Schema (Draft 2020-12), OpenAPI 3.1.1, and AsyncAPI 3.0.0 for the Workflow API and task-commands/task-outcomes messages, including the ADR-0012 correlation contract and 12 examples.
- The `Workflow` aggregate (`src/ai_platform/orchestrator/domain/workflow.py`) enforcing the full Section 9 state machine, plus accepted-request arbitration, task/attempt, transition history, audit, and inbox/outbox/receipt value objects.
- 8 capability-oriented persistence `Protocol` ports under `src/ai_platform/ports/persistence/`, each proven implementable via an in-memory test fake.
- The Capability Registry (`src/ai_platform/orchestrator/registry/`): configuration-backed loading, exact ADR-0008 compatibility matching, bounded readiness, and exactly-one candidate selection.
- The Orchestrator application services (`src/ai_platform/orchestrator/application/`): `SubmissionOrchestrator`, `TerminalEventProcessor`, `DeadlineReconciler`, wired to the Registry via `RegistryCandidateSelector`.
- The Test Agent (`src/ai_platform/agents/test_agent/`): the full `text.word-count` capability and Section 14 lifecycle, composed over the Phase 2 Agent-side ports.
- A corrected module boundary: envelope identifiers and cross-boundary/Agent-owned types live under `shared/` and `agents/domain/`, not `orchestrator/domain/`.
- **A real, runnable Workflow API** (`src/ai_platform/api/`): `POST /api/v1/workflows`, `GET /api/v1/workflows/{workflow_id}`, `GET /health/live`, and `GET /health/ready`. The Sprint 5 in-memory composition remains available for component tests; Sprint 6 adds a durable runtime composition.
- Asynchronous transaction-shaped persistence ports and Psycopg 3 adapters for Orchestrator and Agent state, including inbox/outbox, deadline, audit, access-audit, deduplication, and recovery boundaries — validated against a real PostgreSQL database, not just in-memory fakes.
- Versioned PostgreSQL migrations plus credential-free least-privilege permission-role bootstrap for separate Orchestrator and Agent schemas, applied and verified against a real database.
- A broker-neutral Event Bus port and `confluent-kafka` adapter with exact immutable bytes, keyed routing, manual acknowledgements, bounded publication certainty, durable quarantine, and offset reconciliation — validated against a real Apache Kafka broker, including assignment fencing across multiple Agent replicas.
- Platform and Test Agent process composition with typed configuration, protected secret-file references, schema gates, independent startup, health/readiness, bounded workers, JSON logging, and graceful shutdown — run as real processes against real PostgreSQL/Kafka, including demonstrated crash recovery.
- A Docker application image (`infrastructure/Dockerfile`), built and run locally via Podman.
- A local PostgreSQL + Apache Kafka Compose deployment topology (`infrastructure/compose/`) with pinned images, migrations/role bootstrap, topics, least-privilege ACLs, file-based secrets, and health-ordered startup.
- [ADR-0013](docs/architecture/decisions/ADR-0013-initial-broker-selection-apache-kafka.md): Apache Kafka selected as the initial self-hosted broker instead of Redpanda, superseding only the broker-selection clauses of ADR-0005.
- An automated, opt-in `external_service` pytest suite (`tests/integration/`, 49 tests) exercising the real PostgreSQL/Kafka topology for Event Bus delivery, Concurrency, Security boundary (PostgreSQL role isolation, a 24-case Kafka ACL matrix, secret redaction, audit-failure rollback), and Recovery/crash window (real container kill/restart via `podman exec`) — not the complete Section 19 matrix, but real-service coverage that previously existed only as one-off manual sessions.
- A documented, working dual run path (`tests/integration/run-in-network.sh` plus direct host execution for `test_recovery.py`) for a genuine Windows/WSL2/Podman host-port-forwarding reliability gap found and diagnosed during Sprint 7.
- [docs/operations/README.md](docs/operations/README.md): verified operational documentation (Phase 8) — setup, health, query, recovery, troubleshooting, shutdown/cleanup, contract-generation status, security limitations, and validation commands, every command independently re-run against the real local environment during Sprint 8. Completes Vertical Slice 01's eight-phase plan.

**What doesn't work yet:**
- No contract code-generation tooling (explicitly deferred since Phase 2, still open).
- Portable runtime proof of Kafka producer, consumer-group, and quarantine authorization remains an explicit architecture gap; a metadata probe cannot establish those permissions without adding a new canary contract or overprivileged ACL introspection. Deferred to a future ADR, per [docs/sprint-6/progress.md](docs/sprint-6/progress.md).
- Multi-principal authorization / owner-mismatch disclosure paths are structurally unreachable under the current single-principal `LocalDevelopmentAuthorizationPolicy` and are not implemented.
- Deliberate, operator-initiated quarantine replay has not been exercised (quarantine itself has been, repeatedly).
- The Compose topology is explicitly local-only: single broker, single database node, no TLS, application ports not reachable from the host by design (loopback-only).
- The remaining Section 19 test categories beyond what Sprint 7 automated (Contract, most of Idempotency/Ownership/State machine/Agent readiness/Audit-observability, the full Correlation Normalization table), and a dedicated pytest-automated full-container End-to-End harness.
- On this development host specifically, direct connections from Windows-native Python to the topology's host-published ports remain unreliable at the protocol-handshake level even after fixing the underlying WSL2/firewall configuration issues; the documented workaround (`run-in-network.sh`) is a permanent, working capability, not merely a stopgap, but the root cause of the remaining handshake-level flakiness is not fully understood.

**What's next:**
- Vertical Slice 01's eight-phase plan is complete, with the Phase 7 scope
  caveat above carried forward honestly rather than backfilled. Candidate
  next directions, none started: the remainder of Phase 7's Section 19
  matrix (see [docs/sprint-7/plan.md](docs/sprint-7/plan.md)'s "Out of
  scope"); or a new architecture stream for a real AI-capable Agent and
  the AI Router boundary (both explicitly deferred by Vertical Slice 01
  and not yet designed — see [docs/implementation/vertical-slice-01.md](docs/implementation/vertical-slice-01.md)
  Section 21, "Explicit Deferrals").

## 9. Security Rules

1. Secrets never live in code, fixtures, logs, or documentation — see [SECURITY.md](SECURITY.md).
2. `LocalDevelopmentAuthorizationPolicy` (Sprint 5) is explicitly loopback/local-development-only and must never be treated as production-ready: it has no client credential, resolves every caller to one synthetic principal, and provides no per-developer attribution or isolation.
3. Any contract or configuration example must use nonfunctional placeholder values only.
4. The in-memory reference ports introduced in Sprint 5 hold no secrets and are explicitly non-durable/non-production.

## 10. How to Run Locally

```bash
uv sync
uv run pytest
uv run uvicorn ai_platform.api.app:app --reload
```

The Workflow API can still be run against the Sprint 5 in-memory reference
ports for component development; data in that mode does not survive restart.
The Sprint 6 durable process entry points require protected configuration,
PostgreSQL, and a Kafka-compatible broker; a complete local deployment is
demonstrated in `infrastructure/compose/` — see
[infrastructure/README.md](infrastructure/README.md) to run it.

## 11. How to Deploy

A complete local deployment topology exists under
[infrastructure/](infrastructure/): versioned migrations, credential-free
PostgreSQL permission roles, the application Docker image, and a Podman
Compose topology (PostgreSQL + Apache Kafka + the platform/Test Agent
processes) with least-privilege ACLs and file-based secrets. It is
explicitly local-only (single broker, single database node, no TLS,
loopback-only application exposure) — see
[infrastructure/README.md](infrastructure/README.md) for exact commands.
Production deployment topology, backup, and disaster recovery remain future
work.

## 12. Cross-Chat Handoff Protocol

Every sprint chat/session must do these before finishing:

1. Write `docs/sprint-N/done.md` — what was built, what's not done, what needs manual setup, files changed/created.
2. Update this file: Section 7 (mark sprint status) + Section 8 (rewrite current state).
3. Commit with a descriptive message following [CONTRIBUTING.md](CONTRIBUTING.md) commit-message guidance (short imperative subject, body when needed).
4. Open a pull request per [CONTRIBUTING.md](CONTRIBUTING.md): one clear outcome, documentation updated in the same PR, validation performed listed explicitly.

The repository is the shared memory — keep `docs/sprint-N/` and this file
accurate so the next session does not duplicate or contradict prior work.

## 13. Bug & Fix Tracking

Bugs and follow-up work are tracked as GitHub Issues on this repository —
the single source of truth across sessions.

**For QA (Ivy):** file issues with labels (`bug`, `severity:blocker/major/minor`).
Include: affected file/contract, steps to reproduce, expected vs. actual. When
no blockers are found, write `docs/qa/sprint-N-signoff.md` with an explicit
"no blockers" statement and the validation performed.

**For contributors:** check existing issues before starting work. Fix
blockers and majors before polish. Use GitHub closing keywords in commits:
`fix: description (Fixes #NN)`. Use `Refs #NN` for reference-only.

**For tooling/infrastructure issues:** label `infra`.

**For future-sprint ideas:** add to `docs/ideas-backlog.md` rather than
expanding the current sprint's scope.

## 14. Multi-Repo / Branch Setup

This repository does not require separate clones per role for a single
contributor session, but the branch and PR discipline from
[CONTRIBUTING.md](CONTRIBUTING.md) applies to every sprint:

- Create one short-lived branch per sprint from the latest `main`, e.g.
  `feature/sprint-1-tooling-and-contracts`.
- Keep the branch limited to the sprint's declared scope (Phase 1 only for
  Sprint 1). Do not mix unrelated refactors or future-phase work into it.
- Never push directly to `main`. Open a pull request, address review
  feedback, and merge (do not rebase a shared feature branch — merge to
  preserve history, per [CONTRIBUTING.md](CONTRIBUTING.md)).
- If parallel work streams are later run in separate sessions/clones (e.g.
  a QA session validating contracts while a dev session continues Phase 2),
  follow the same isolated-clone pattern documented in the
  `ai-team-orchestration` skill: one clone and branch per active role,
  coordinated through this file and `docs/sprint-N/progress.md`.
