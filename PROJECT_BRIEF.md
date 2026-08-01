# PROJECT_BRIEF.md — AI Platform

> Last updated: 2026-08-01 | Sprint 1 | Status: In Progress

> **Note on terminology:** the roles in Section 6 are a *virtual contributor
> team* used to plan and execute sprints in this repository. They are not the
> platform's own architectural "Agents" (Orchestrator, Event Bus, AI Router,
> Agents, Skills — see [docs/architecture/README.md](docs/architecture/README.md)),
> and they are not defined under [agents/](agents/). This file is a
> sprint-coordination artifact, not an Architecture Decision Record.

## 1. Project Overview

AI Platform is a foundation for coordinating specialized AI agents through
modular boundaries and event-driven communication (see
[README.md](README.md)). The repository is currently at its architecture and
documentation stage: 12 Accepted ADRs and one fully specified implementation
plan exist, but no runtime code has been written yet. Sprint 1 begins the
first implementation phase.

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
disclose. It is specified in 8 implementation phases; Sprint 1 covers only
**Phase 1**.

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
- **Persistence (later phases):** PostgreSQL, owned schemas — [ADR-0006](docs/architecture/decisions/ADR-0006-persistence-state-and-recovery.md)
- **Event Bus (later phases):** Kafka-protocol adapter (`confluent-kafka`), local Redpanda broker — [ADR-0005](docs/architecture/decisions/ADR-0005-event-bus-and-messaging-infrastructure.md)
- **Deployment (later phases):** Docker, cloud-agnostic, Unraid as a first-class target — [infrastructure/README.md](infrastructure/README.md)

Sprint 1 (Phase 1) introduces only tooling metadata and contracts — no
domain, persistence, or transport implementation. Sprint 5 (Phase 5) adds
a real, runnable HTTP API (FastAPI/Uvicorn) composed over in-memory
reference ports; PostgreSQL/Kafka adapters remain Phase 6.

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

Target package tree for `src/ai_platform/` (established across all vertical
slice phases; Sprint 2 populated `orchestrator/domain/` and
`ports/persistence/`; Sprint 3 added `orchestrator/registry/` and
`orchestrator/application/`; Sprint 4 added `agents/test_agent/`,
`agents/domain/`, and expanded `shared/`; Sprint 5 populated `api/`; the
rest remain skeletons):

```text
src/
└── ai_platform/
    ├── api/                   # Sprint 5: Workflow API (context, correlation, fingerprint, routes, in-memory port assembly)
    ├── orchestrator/
    │   ├── domain/            # Sprint 2: Workflow aggregate, value objects
    │   ├── registry/          # Sprint 3: Capability Registry (declarations, snapshot, availability, selection)
    │   └── application/       # Sprint 3: submission/terminal/deadline application services
    ├── agents/
    │   ├── domain/            # Sprint 4: Agent-owned outcome/receipt/event-outbox records
    │   └── test_agent/        # Sprint 4: the built-in text.word-count capability and lifecycle
    ├── contracts/
    ├── ports/
    │   ├── event_bus/
    │   └── persistence/       # Sprint 2: 7 ports; Sprint 3 added NonterminalWorkflowQueryPort
    ├── adapters/
    │   ├── event_bus/
    │   └── persistence/
    └── shared/                # identifiers.py, outcomes.py, recovery.py (Sprint 4): types crossing the Agent/Orchestrator boundary
        ├── configuration/
        └── logging/
```

## 5. Key Files Map

| Area | Path | Contents |
|------|------|----------|
| Contributor guidance | [AGENTS.md](AGENTS.md) | Repository-wide philosophy, standards, ADR process |
| Contribution workflow | [CONTRIBUTING.md](CONTRIBUTING.md) | Branch/PR workflow, ADR process, testing/review expectations |
| Platform architecture | [docs/architecture/README.md](docs/architecture/README.md) | Logical components, contracts, boundaries |
| ADRs | [docs/architecture/decisions/](docs/architecture/decisions/) | 12 Accepted ADRs (0001–0012), governing all implementation |
| First implementation plan | [docs/implementation/vertical-slice-01.md](docs/implementation/vertical-slice-01.md) | 8-phase plan for the first deterministic workflow |
| Test strategy | [docs/testing/README.md](docs/testing/README.md) | Local vs. external-service test levels |
| Platform agents (architecture) | [agents/](agents/) | Placeholder — populated after Phase 3+ (Orchestrator/Registry/Test Agent) |
| Skills (platform capabilities) | [skills/](skills/) | Placeholder — reusable Agent capabilities |
| Infrastructure | [infrastructure/](infrastructure/) | Placeholder — Docker/Unraid deployment definitions |
| Scripts | [scripts/](scripts/) | Placeholder — dev/validation/deploy utilities |
| Tests | [tests/](tests/) | Placeholder — mirrors module boundaries once established |
| Sprint docs | `docs/sprint-N/` | Plans, progress, done, and consilium notes per sprint |
| Source (created in Sprint 1) | `src/ai_platform/` | Root package; only tooling/contract skeleton in Sprint 1 |

## 6. Team Roles (Sprint 5)

| Agent | Name | Role | Focus this sprint |
|-------|------|------|--------------------|
| Producer | **Remy** | Sprint planning, coordination, PR review/merge | Scope control against Phase 5 only; kept the in-memory port assembly explicitly labeled non-production |
| API Engineer | **Sage** | Workflow API | Trusted context, ADR-0012 correlation, RFC 8785 fingerprinting, Problem Details, FastAPI routes |
| QA Engineer | **Ivy** | Correlation, fingerprint, and API contract tests | All 5 ADR-0012 scenarios; the full Section 5 HTTP error table via `TestClient` |

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

## 8. Current State

**What works:**
- Repository-wide contributor guidance ([AGENTS.md](AGENTS.md), [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md)).
- Complete platform architecture description and 12 Accepted ADRs.
- A fully specified, ADR-aligned implementation plan for the first vertical slice.
- Root tooling metadata (`pyproject.toml`, `uv.lock`) and the `src/ai_platform/` package skeleton (ADR-0003), validated locally with `uv sync`, Ruff, BasedPyright (strict), and pytest.
- Canonical contracts under `contracts/`: JSON Schema (Draft 2020-12), OpenAPI 3.1.1, and AsyncAPI 3.0.0 for the Workflow API and task-commands/task-outcomes messages, including the ADR-0012 correlation contract and 12 examples.
- The `Workflow` aggregate (`src/ai_platform/orchestrator/domain/workflow.py`) enforcing the full Section 9 state machine, plus accepted-request arbitration, task/attempt, transition history, audit, and inbox/outbox/receipt value objects.
- 8 capability-oriented persistence `Protocol` ports under `src/ai_platform/ports/persistence/`, each proven implementable via an in-memory test fake.
- The Capability Registry (`src/ai_platform/orchestrator/registry/`): configuration-backed loading, exact ADR-0008 compatibility matching, bounded readiness, and exactly-one candidate selection.
- The Orchestrator application services (`src/ai_platform/orchestrator/application/`): `SubmissionOrchestrator`, `TerminalEventProcessor`, `DeadlineReconciler`, wired to the Registry via `RegistryCandidateSelector`.
- The Test Agent (`src/ai_platform/agents/test_agent/`): the full `text.word-count` capability and Section 14 lifecycle, composed over the Phase 2 Agent-side ports.
- A corrected module boundary: envelope identifiers and cross-boundary/Agent-owned types live under `shared/` and `agents/domain/`, not `orchestrator/domain/`.
- **A real, runnable Workflow API** (`src/ai_platform/api/`): `POST /api/v1/workflows`, `GET /api/v1/workflows/{workflow_id}`, `GET /health/live`, `GET /health/ready` — verified both via `TestClient` and as an actual local `uvicorn` process handling real HTTP requests. Composed over in-memory reference ports (explicitly non-production, documented as a Sprint 5 stand-in for Phase 6 adapters).
- 190 tests, all passing: 52 contract + 24 domain unit + 42 registry unit + 14 Test Agent unit + 11 API unit + 47 component (persistence ports, application services, registry integration, Test Agent lifecycle, Workflow API).

**What doesn't work yet:**
- No concrete persistence/Event Bus adapters (Phase 6) — the API's in-memory ports do not survive process restart and have no real transactional guarantee.
- No Event Bus consumer: after HTTP submission, a workflow remains `DISPATCHED` until a future Phase 6 consumer (or a test directly driving `TerminalEventProcessor`) applies the terminal outcome.
- No contract code-generation tooling (explicitly deferred since Phase 2, still open).
- No Docker/local deployment artifacts (Phase 6).
- Broader outbox/inbox recovery-query capabilities remain deferred to Phase 6 (adapter-dependent).
- Lifecycle interruption (shutdown/restart/rebalance cancellation) is deferred to Phase 6.
- Multi-principal authorization / owner-mismatch disclosure paths are structurally unreachable under the current single-principal `LocalDevelopmentAuthorizationPolicy` and are not implemented.

**What's next (Sprint 6 candidate — Phase 6):**
- Concrete adapters and local deployment per [vertical-slice-01.md Section 20, Phase 6](docs/implementation/vertical-slice-01.md#20-implementation-phases): Psycopg 3 persistence adapters, the `confluent-kafka` Event Bus adapter, Redpanda/PostgreSQL local resources, isolated credentials/ACLs, Docker artifacts, publishers/consumers, health, and shutdown. **Note:** this environment currently has no Docker installation; real PostgreSQL/Redpanda validation may require either installing Docker Desktop (heavyweight on a shared machine) or a native local install, and will be flagged for explicit user confirmation before proceeding.

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

The Workflow API is now real and runnable: `POST /api/v1/workflows`,
`GET /api/v1/workflows/{workflow_id}`, `GET /health/live`, and
`GET /health/ready` all work against in-memory reference ports (data does
not survive a restart). No environment variables or secrets are required.
Concrete PostgreSQL/Redpanda-backed persistence remains Phase 6.

## 11. How to Deploy

Not applicable yet. [infrastructure/](infrastructure/) remains a placeholder
until Phase 6 (Concrete Adapters and Local Deployment) of the vertical slice
plan.

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
