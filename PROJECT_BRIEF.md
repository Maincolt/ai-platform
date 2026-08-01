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
- **Persistence (later phases):** PostgreSQL, owned schemas — [ADR-0006](docs/architecture/decisions/ADR-0006-persistence-state-and-recovery.md)
- **Event Bus (later phases):** Kafka-protocol adapter (`confluent-kafka`), local Redpanda broker — [ADR-0005](docs/architecture/decisions/ADR-0005-event-bus-and-messaging-infrastructure.md)
- **Deployment (later phases):** Docker, cloud-agnostic, Unraid as a first-class target — [infrastructure/README.md](infrastructure/README.md)

Sprint 1 (Phase 1) introduces only tooling metadata and contracts — no
domain, persistence, or transport implementation.

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
`orchestrator/application/`; the rest remain skeletons):

```text
src/
└── ai_platform/
    ├── api/
    ├── orchestrator/
    │   ├── domain/            # Sprint 2: Workflow aggregate, value objects
    │   ├── registry/          # Sprint 3: Capability Registry (declarations, snapshot, availability, selection)
    │   └── application/       # Sprint 3: submission/terminal/deadline application services
    ├── agents/
    │   └── test_agent/
    ├── contracts/
    ├── ports/
    │   ├── event_bus/
    │   └── persistence/       # Sprint 2: 7 ports; Sprint 3 added NonterminalWorkflowQueryPort
    ├── adapters/
    │   ├── event_bus/
    │   └── persistence/
    └── shared/
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

## 6. Team Roles (Sprint 3)

| Agent | Name | Role | Focus this sprint |
|-------|------|------|--------------------|
| Producer | **Remy** | Sprint planning, coordination, parallel-work split, PR review/merge | Scope control against Phase 3 only; ran the Registry as a background sub-agent in parallel with main-thread application-service work |
| Domain/Application Engineer | **Sage** | Orchestrator application services | `SubmissionOrchestrator`, `TerminalEventProcessor`, `DeadlineReconciler`, the Registry integration seam and adapter |
| Tooling/Registry Engineer | **Dash** | Capability Registry (background sub-agent) | Declaration/snapshot/availability/selection modules, built independently against a fixed interface spec |
| QA Engineer | **Ivy** | Application-service and integration tests | Component tests with fakes for the application services; end-to-end tests once the Registry integrated |

Frontend/visual roles (Nova, Milo, Kira) remain unneeded. A dedicated Test
Agent engineer and DevOps/deployment engineer should be introduced starting
with the sprints that implement Phase 4 (Test Agent) and Phase 6
(adapters/deployment) respectively.

## 7. Sprint Status

| Sprint | Name | Status | Scope |
|--------|------|--------|-------|
| 0 | Architecture | ✅ Done | ADR-0001–0012 (Accepted), platform architecture doc, Vertical Slice 01 plan |
| 1 | Tooling and Canonical Contracts | ✅ Done | Vertical Slice 01 **Phase 1** only: root tooling metadata + canonical JSON Schema/OpenAPI/AsyncAPI contracts. No domain behavior. See [docs/sprint-1/done.md](docs/sprint-1/done.md). |
| 2 | Workflow Domain and Persistence Ports | ✅ Done | Vertical Slice 01 **Phase 2** only: five-state `Workflow` aggregate, accepted-request arbitration, task/attempt, transition history, audit, inbox/outbox/receipt records, 7 persistence `Protocol` ports. Pure domain code, no adapters. See [docs/sprint-2/done.md](docs/sprint-2/done.md). |
| 3 | Orchestrator and Capability Registry | ✅ Done | Vertical Slice 01 **Phase 3** only: configuration-backed Capability Registry, submission-transaction orchestration, terminal event processing, deadline reconciliation, one recovery query port. Registry built via a parallel background sub-agent. See [docs/sprint-3/done.md](docs/sprint-3/done.md). |

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
- 143 tests, all passing: 52 contract + 24 domain unit + 41 registry unit + 26 component (persistence ports, application services, and end-to-end registry integration).

**What doesn't work yet:**
- No Test Agent, Workflow API, or Event Bus implementation exists — the Orchestrator side of the vertical slice is now complete as application/domain code.
- No concrete persistence/Event Bus adapters (Phase 6) — ports have no real database/Kafka behind them yet.
- No contract code-generation tooling (explicitly deferred since Phase 2, still open).
- No Docker/local deployment artifacts (Phase 6).
- Broader outbox/inbox recovery-query capabilities (not-attempted, unknown, claimed-expired) remain deferred to Phase 6 (adapter-dependent); only the narrow deadline-reconciliation query exists.

**What's next (Sprint 4 candidate — Phase 4):**
- Test Agent implementation per [vertical-slice-01.md Section 20, Phase 4](docs/implementation/vertical-slice-01.md#20-implementation-phases): the built-in `text.word-count` capability, bounded lifecycle, validation, completed-receipt deduplication, outcome transaction, Agent event outbox, and development readiness boundary — composed against the Phase 2 Agent-side ports, still without real adapters.

## 9. Security Rules

1. Secrets never live in code, fixtures, logs, or documentation — see [SECURITY.md](SECURITY.md).
2. Sprint 1 introduces no runtime services, so there are no credentials or trust boundaries to configure yet.
3. When later phases introduce the local-development authorization boundary (ADR-0010), it is explicitly loopback-only and must not be treated as production-ready.
4. Any contract or configuration example must use nonfunctional placeholder values only.

## 10. How to Run Locally

```bash
uv sync
uv run pytest
```

This validates the Sprint 1 tooling and contracts (creates a project-local
`.venv/` only). There is no running service yet — the Workflow API,
Orchestrator, and Agent are implemented starting in later phases. Later
phases will add Docker Compose for PostgreSQL/Redpanda and the Workflow API.

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
