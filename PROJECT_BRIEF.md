# PROJECT_BRIEF.md — AI Platform

> Last updated: 2026-08-16 | `scrum-master-agent` (ADR-0028, ADR-0026 Phase 2): the platform's first non-Workflow-driven Agent, taking real autonomous board-write actions on an hourly cycle bounded by a kill switch, a daily action/spend cap, and an audit log — deployed and live-verified against the repository owner's real board (real board fetch + real AI Router completion both succeeded); first real write action still pending an explicit go-ahead | Status: In progress

> **Note on terminology:** the roles in Section 6 are a *virtual contributor
> team* used to plan and execute sprints in this repository. They are not the
> platform's own architectural "Agents" (Orchestrator, Event Bus, AI Router,
> Agents, Skills — see [docs/architecture/README.md](docs/architecture/README.md)),
> and they are not defined under [agents/](agents/). This file is a
> sprint-coordination artifact, not an Architecture Decision Record.

## 1. Project Overview

AI Platform is a foundation for coordinating specialized AI agents through
modular boundaries and event-driven communication (see
[README.md](README.md)). Thirty-four Accepted ADRs govern the platform.
Vertical Slice 01's eight-phase deterministic proof of architecture
(`text.word-count`) completed at Sprint 8. Sprint 9 added the first
provider-backed capability (`text.summarize`,
[ADR-0014](docs/architecture/decisions/ADR-0014-ai-router-and-first-ai-backed-agent.md))
behind a new AI Router boundary, and the generic capability result model
([ADR-0015](docs/architecture/decisions/ADR-0015-generic-capability-result-model.md))
it depends on. Five more advisory, AI-backed capabilities followed the
same shape, all activating personas ADR-0018 Decision 2 pre-assessed as
fitting the bounded-advisory model: `code.review`
([ADR-0018](docs/architecture/decisions/ADR-0018-software-team-persona-capabilities.md)),
`ui.review` ([ADR-0019](docs/architecture/decisions/ADR-0019-ui-review-capability.md),
Sprint 11, Playwright-backed), `architecture.review`
([ADR-0020](docs/architecture/decisions/ADR-0020-architecture-review-capability.md)),
`data.analysis`
([ADR-0021](docs/architecture/decisions/ADR-0021-data-analysis-capability.md)),
and `technical.review`
([ADR-0022](docs/architecture/decisions/ADR-0022-technical-review-capability.md))
— the last of which closes out all six personas ADR-0018 Decision 2
found fitting the bounded-advisory model. An eighth capability,
`assignment.route`
([ADR-0023](docs/architecture/decisions/ADR-0023-assignment-route-capability.md)),
is not one of the twelve personas — it reads a free-text assignment and
recommends which of the other six capabilities should look at it, so a
caller can get every genuinely relevant specialist's perspective on one
input via the `submit-assignment.py` dispatch script, without a new
Orchestrator-level AI invocation or agentic tool-calling architecture. A
ninth capability, `security.review`
([ADR-0025](docs/architecture/decisions/ADR-0025-security-review-capability.md)),
is also not one of the twelve personas — it fills a role ADR-0018
Decision 2 never assessed, reviewing a code diff/configuration file/
infrastructure-as-code snippet for security concerns (injection, auth/
authz gaps, secrets handling, insecure defaults, SSRF/deserialization)
with an adversarial lens distinct from `code.review`'s general quality
lens. It is also a routable target for `assignment.route`.
**Real Anthropic (primary) and OpenAI (fallback) credentials are now
configured** and all eight AI-backed capabilities have been live-verified
end to end against them — a real model completion, not a placeholder
failure; see Section 8.

[ADR-0026](docs/architecture/decisions/ADR-0026-autonomous-team-agents.md)
(Accepted, policy/architecture only — no code) authorizes an eventual
autonomous multi-agent team (Scrum Master, Product Owner, Principal
Developer) to take real, hard-to-reverse actions with no per-action human
approval, narrowly amending `SECURITY.md`'s Human Approval for High-Impact
Actions policy for those specific roles/actions — but stages the rollout,
starting with a read-only Phase 1 that needs none of that. A tenth
capability, `scrum.status`
([ADR-0027](docs/architecture/decisions/ADR-0027-scrum-status-capability.md),
ADR-0026's Phase 1), fetches a live GitHub Projects v2 board via one
deterministic, read-only API call and returns one AI Router call's worth
of advisory findings — the same fetch-then-AI-call shape `ui.review`
established, structurally no different from any prior capability. Deployed
to the Mac Docker host and reaches `READY`, but not yet live-verified end
to end: the repository has no populated GitHub Projects v2 board yet, so
`scrum-status-agent` runs against placeholder credentials until the
repository owner creates one and supplies a real `read:project`-scoped
PAT.

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

Beyond Vertical Slice 01, Sprint 9 adds the platform's second built-in
Agent, `text.summarize` v1.0, the first to call a real external AI
provider through the new AI Router boundary (`src/ai_platform/ports/ai_router/`,
`src/ai_platform/adapters/ai_router/`). This is where the "AI Router"
and "Skills" boxes in the diagram below start being real rather than
placeholders (Skills remain deferred).

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
    │   ├── domain/             # Sprint 4: Agent-owned outcome/receipt/event-outbox records
    │   ├── test_agent/         # Sprint 4: the built-in text.word-count capability and lifecycle
    │   └── summarize_agent/    # Sprint 9: the built-in text.summarize capability, AI Router-backed
    ├── contracts/             # Contract package boundary; canonical artifacts remain under root contracts/
    ├── ports/
    │   ├── event_bus/
    │   ├── ai_router/          # Sprint 9: AIRouterPort, completion request/result contract
    │   └── persistence/       # Capability and transaction-shaped durable ports
    ├── adapters/
    │   ├── event_bus/          # Kafka-protocol producer/consumer, health, topics, quarantine
    │   ├── ai_router/          # Sprint 9: Anthropic/OpenAI provider adapters, fallback router
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
| ADRs | [docs/architecture/decisions/](docs/architecture/decisions/) | 19 Accepted ADRs (0001–0019), governing all implementation |
| First implementation plan | [docs/implementation/vertical-slice-01.md](docs/implementation/vertical-slice-01.md) | 8-phase plan for the first deterministic workflow |
| Test strategy | [docs/testing/README.md](docs/testing/README.md) | Local vs. external-service test levels |
| Agent capability implementations | [src/ai_platform/agents/](src/ai_platform/agents/) | `test_agent/` (`text.word-count`), `summarize_agent/` (`text.summarize`), `review_agent/` (`code.review`), `ui_review_agent/` (`ui.review`), `architecture_review_agent/` (`architecture.review`), `data_analysis_agent/` (`data.analysis`), `technical_review_agent/` (`technical.review`), `security_review_agent/` (`security.review`), `scrum_status_agent/` (`scrum.status`), `assignment_route_agent/` (`assignment.route`) — each a self-contained Workflow-invocable deployable per ADR-0007. Plus `scrum_master_agent/` — not a capability (no `ExecuteTask` consumption, no Registry binding); a `PeriodicService`-driven autonomous role (ADR-0026/ADR-0028). |
| Skills (platform capabilities) | [skills/](skills/) | Placeholder — reusable Agent capabilities |
| Infrastructure | [infrastructure/](infrastructure/) | Application image(s) (including the dedicated `ui-review-agent/` Chromium image), migrations, PostgreSQL role definitions, and the full local Compose deployment topology (`compose/`) |
| Agent status dashboard | [frontend/dashboard/](frontend/dashboard/) | Vue.js SPA consuming `GET /api/v1/agents`, containerized behind nginx sharing `platform`'s network namespace |
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
| 9 | AI Router and the First AI-Backed Agent | ✅ Done (real-provider validation deferred) | First work beyond Vertical Slice 01: [ADR-0014](docs/architecture/decisions/ADR-0014-ai-router-and-first-ai-backed-agent.md) (AI Router boundary, Anthropic/OpenAI provider adapters, deterministic fallback routing, durable redacted usage tracking, capability-scoped Kafka `task-commands` routing, the `text.summarize` v1.0 Agent with a durable pre-call claim model) and [ADR-0015](docs/architecture/decisions/ADR-0015-generic-capability-result-model.md) (generalized `result_data` model replacing the `word_count`-specific shape across contracts, Agent/Orchestrator persistence, and the public API, proven not to regress `text.word-count`). 420 tests passing (up from 339); real Anthropic/OpenAI provider validation and real-topology re-validation of this sprint's own infrastructure changes are both explicitly deferred (no credentials in this environment; see [docs/sprint-9/done.md](docs/sprint-9/done.md)). |
| 10 | Topology Re-validation, Operator Runbook, ADR-0014 Follow-Ups, Phase 7 Continuation | ✅ Done | Spanned multiple PRs rather than one feature branch (see [docs/sprint-10/plan.md](docs/sprint-10/plan.md) sequencing note): re-migrated the local topology to `main` and re-ran `external_service` against it; wrote the ADR-0016 operator runbook (`docs/operations/README.md` Section 5); resolved [ADR-0014](docs/architecture/decisions/ADR-0014-ai-router-and-first-ai-backed-agent.md) Section 8's remaining four open questions via [ADR-0017](docs/architecture/decisions/ADR-0017-ai-router-follow-up-decisions.md) (model allowlist, retry-budget defaults, fallback ordering ratified, Orchestrator-invocation deliberately left out of scope) plus a readiness-routing bug found along the way; picked up most of Phase 7's deferred Section 19 categories (Agent selection/readiness, Idempotency, Ownership/disclosure, State machine, Inbox/outbox, Contract, Correlation Normalization — `external_service` suite grew 65→79 passed). Still open: a pytest-automated full-container End-to-End harness (not scoped into this sprint). No single `docs/sprint-10/done.md`; see [docs/sprint-10/progress.md](docs/sprint-10/progress.md) for the full account. |
| — | Post-Sprint-10 (unsprinted, individual PRs) | ✅ Done | [ADR-0018](docs/architecture/decisions/ADR-0018-software-team-persona-capabilities.md) (Accepted): a twelve-role software-team persona set as Claude Code subagents (`.claude/agents/*.md`, PR #29 — a coordination mechanism, not a platform capability) plus the platform's third built-in Agent class, `code.review` v1.0, fully wired into the running platform (domain/contract layer PR #28, `runtime/composition.py`/`review-agent` Compose service/Registry binding PR #31, public-API submission fix PR #32). `GET /api/v1/agents` (PR #33): a read-only Capability Registry status endpoint. A Vue.js agent status dashboard (`frontend/dashboard/`, containerized, consumes `GET /api/v1/agents`) — PR #34, merged. A platform/agent shutdown-diagnostics fix (PR #35, merged) addressed a previously-undiagnosable `PLATFORM_SHUTDOWN_INCOMPLETE`/`AGENT_SHUTDOWN_INCOMPLETE` crash that had been misattributed to host-specific flakiness since Sprint 10 — its actual root cause was found and fixed in Sprint 11 (see below). |
| 11 | `ui.review` — a Playwright-Backed UI Review Capability | ✅ Done | [ADR-0019](docs/architecture/decisions/ADR-0019-ui-review-capability.md) (Accepted): the platform's fourth capability and third AI-backed one, reviewing the platform's own dashboard for UI/UX/accessibility/console-error problems via a deterministic Playwright/Chromium capture step feeding one AI Router call — stays inside the existing single-shot AI Router contract, no new tool-calling architecture. Three PRs (#36 domain/contract layer, #37 real Playwright integration — later consolidated into #39 after a GitHub stacked-PR-after-squash-merge quirk auto-closed it, #39 deployment wiring), all live-verified on the real Mac Docker host: `ui-review-agent` reaches `READY`, appears on `GET /api/v1/agents`/the dashboard with zero frontend changes, the full 73-case live Kafka ACL matrix passes. Two genuine bugs found only by live deployment, both fixed: (1) `runtime/composition.py`'s Orchestrator `command_publisher` was never given `environment=`, crashing on *any* capability-scoped publish — the actual root cause of the multi-sprint `PLATFORM_SHUTDOWN_INCOMPLETE` mystery (PR #38, standalone since platform-wide not `ui.review`-specific); (2) `ui.review`'s own redirect-safety check didn't normalize default ports, rejecting every successful navigation (fixed in #39 with a regression test). See `docs/sprint-11/plan.md` for the full account. |
| — | Post-Sprint-11: real AI provider validation | ✅ Done | Real Anthropic (primary) and OpenAI (fallback) API keys configured in `infrastructure/compose/secrets/` (git-ignored). All three AI-backed capabilities live-verified with genuine model completions: `text.summarize` (real summary), `code.review` (correctly flagged a hardcoded password + SQL injection in a test diff), `ui.review` (real Chromium capture of the live dashboard + genuine accessibility findings). One real bug found live and fixed (PR #40, merged): `code.review`/`ui.review` both rejected genuine Claude responses wrapped in a ` ```json ` markdown fence despite the prompt saying not to — `_strip_markdown_json_fence()` now tolerates the wrapping without loosening the underlying strict parse. |
| — | `architecture.review` — a Solution-Architect Review Capability | ✅ Done | [ADR-0020](docs/architecture/decisions/ADR-0020-architecture-review-capability.md) (Accepted): the platform's fifth capability and fourth AI-backed one, structurally identical to `code.review` end to end (no new external side effect, no new architecture) — reviews a proposed architectural change/design doc/ADR draft and returns `{section, summary, severity}` findings. Two PRs (#42 domain/contract layer + deployment wiring, plus a small follow-up fix for a top-level `secrets:` stanza omission found live), live-verified on the Mac Docker host: `architecture-review-agent` reaches `READY`, the full 89-case live Kafka ACL matrix passes, a real submission returned seven genuine findings from Anthropic. Found and documented a new operational gotcha along the way: bumping `registry.json`'s revision leaves every *already-running* Agent `UNAVAILABLE` until it's individually restarted, not just the newly added one (`docs/operations/README.md`). |
| — | `data.analysis` — a Data-Analyst Review Capability | ✅ Done | [ADR-0021](docs/architecture/decisions/ADR-0021-data-analysis-capability.md) (Accepted): the platform's sixth capability and fifth AI-backed one, structurally identical to `architecture.review` — reviews a dataset excerpt/metrics summary/usage report and returns `{metric, summary, severity}` findings. Closes out the original six ADR-0018 Decision 2 personas except Technical Architect. Two PRs (#43 domain/contract layer, #44 deployment wiring — this time declaring the new Kafka secrets in the top-level `secrets:` stanza from the start, applying the lesson from `architecture.review`'s deployment), live-verified on the Mac Docker host: all six capabilities reached `READY` on the first check (applying the registry-revision-bump restart gotcha proactively this time), the full 106-case live Kafka ACL matrix passes, a real submission correctly correlated a four-metric week-4 anomaly (MAU drop, latency spike, cost spike, support-ticket spike) into four findings. |
| — | `technical.review` — a Technical-Architect Review Capability | ✅ Done | [ADR-0022](docs/architecture/decisions/ADR-0022-technical-review-capability.md) (Accepted): the platform's seventh capability and sixth AI-backed one, structurally identical to `data.analysis` — reviews a proposed data model/schema/API contract/service-boundary design and returns `{component, summary, severity}` findings. Closes out all six ADR-0018 Decision 2 personas. Two PRs (#45 domain/contract layer, #46 deployment wiring), live-verified on the Mac Docker host: all seven capabilities reached `READY` on the first check, the full 124-case live Kafka ACL matrix passes, a real submission against a deliberately under-specified notifications schema/API returned eight sharply specific findings (missing indexes, no idempotency key, synchronous send blocking the request handler, no delivery-status visibility, no rate limiting). |
| — | `assignment.route` — Team-Based Assignment Routing | ✅ Done | [ADR-0023](docs/architecture/decisions/ADR-0023-assignment-route-capability.md) (Accepted): the platform's eighth capability and seventh AI-backed one — not one of the twelve ADR-0018 personas, but a new triage capability that reads a free-text assignment and recommends which of the team's six real capabilities should look at it (`{capability, rationale}`, 1–6 items). Deliberately stays inside two boundaries ADR-0014/ADR-0017 already deferred (no Orchestrator-level AI invocation, no tool-calling/platform-action capability): the actual multi-capability fan-out lives entirely in a caller-side script, `infrastructure/compose/scripts/submit-assignment.py` (PR #49), not in platform architecture. Three PRs (#47 domain/contract layer, #48 deployment wiring, #49 dispatch script), live-verified on the Mac Docker host: all eight capabilities reached `READY` on the first check, the full 143-case live Kafka ACL matrix passes, and `submit-assignment.py` was run end to end against a mixed schema-design-and-reporting assignment — correctly routed to and fanned out across both `technical.review` and `data.analysis`, each returning genuine, distinct findings, combined into one report. |
| — | Submission History — `GET /api/v1/workflows` | ✅ Done | [ADR-0024](docs/architecture/decisions/ADR-0024-submission-history.md) (Accepted): answers "how do I see what's been submitted" for the new Submit-assignment tab — a durable, shared history visible to every dashboard visitor, not ephemeral in-browser state. Additive `orchestrator.submission_history` table (migration 0008, orchestrator schema version 3→4) rather than a change to the `Workflow` aggregate, written in the same atomic transaction as a new submission, always read fresh via a join so it can never go stale. First paginated (cursor, not offset) list endpoint in this API. Three PRs (#51 backend/migration/contracts, #52 dashboard History tab, plus a deploy pass), live-verified on the Mac Docker host: migration applied cleanly, all eight capabilities stayed `READY` (no registry change this round, so no cascading agent restarts needed), a real submission round-tripped through the live endpoint with exact capability/text/state, and the four real-Postgres integration tests (including the new submission-history round-trip) passed directly against the Mac database. |
| — | Agent busy status — `in_flight_count` on `GET /api/v1/agents` | ✅ Done | Dashboard shows a "Busy · N in flight" badge per agent, derived by counting `orchestrator.task_attempts` rows still `DISPATCHED` per `agent_id` — no new migration or instrumentation. New `InFlightWorkloadQueryPort` with in-memory and Postgres adapters. PR #53, live-verified on the Mac Docker host: a real `architecture.review` submission showed `in_flight_count` go 0→1 while `DISPATCHED` and back to 0 on `COMPLETED`, confirmed visually via a Playwright screenshot of the live dashboard mid-flight. |
| — | `security.review` — a Security-Reviewer Review Capability | ✅ Done | [ADR-0025](docs/architecture/decisions/ADR-0025-security-review-capability.md) (Accepted): the platform's ninth capability and eighth AI-backed one — not one of the twelve ADR-0018 personas (no dedicated Security role was assessed there), a fresh fit check against Decision 1's admission policy. Structurally identical to `technical.review`, with an adversarial security lens (injection, auth/authz gaps, secrets handling, insecure defaults, SSRF/path-traversal-shaped issues, unsafe deserialization) and `{location, summary, severity}` findings instead of `{component, summary, severity}`. Also added as a routable `assignment.route` target. One PR (#54, domain/contract layer + deployment wiring together), live-verified on the Mac Docker host: all nine capabilities reached `READY` on the first check (confirmed visually via a Playwright screenshot showing "9 / 9 online" with zero frontend changes needed), the full 162-case live Kafka ACL matrix passes, and a real submission against a deliberately vulnerable Python snippet returned four sharply specific findings from Anthropic (two SQL injections, a hardcoded API key, a missing auth/authz check on a destructive endpoint). |
| — | Autonomous Team Agents (policy) | ✅ Done (policy only, no code) | [ADR-0026](docs/architecture/decisions/ADR-0026-autonomous-team-agents.md) (Accepted): authorizes three future roles (Scrum Master, Product Owner, Principal Developer) to take real, hard-to-reverse actions with no per-action human approval, narrowly amending `SECURITY.md`'s Human Approval for High-Impact Actions policy for those specific roles/actions. Safety is structural instead of a checkpoint: a fixed, code-dispatched per-role action allowlist, per-role least-privilege credentials, a durable audit trail, a platform-wide kill switch, a hard spend/rate cap. Deploy rights excluded from every role's initial scope, deferred to a future ADR. Staged rollout, starting with the read-only Phase 1 below. |
| — | `scrum.status` — a Read-Only, Live Scrum-Board Status Capability | ✅ Done | [ADR-0027](docs/architecture/decisions/ADR-0027-scrum-status-capability.md) (Accepted): ADR-0026's Phase 1 — the platform's tenth capability and ninth AI-backed one, structurally identical to `ui.review`'s fetch-then-single-AI-call shape, but fetching an authenticated GitHub Projects v2 board via GraphQL instead of an unauthenticated Playwright page load. New `ProjectBoardPort`/`GitHubProjectsBoardReader`, a new `read:project`-scoped PAT credential class, and (unlike `ui.review`) config-driven rather than hardcoded project coordinates, since there's no SSRF-shaped risk to close off for an authenticated API call. `{location, summary, severity}` findings. Two PRs (#56 domain/contract layer + deployment wiring, #58 real board configuration), live-verified on the Mac Docker host: all ten capabilities reached `READY` (confirmed visually via a Playwright screenshot showing "10 / 10 online" with zero frontend changes needed), the full 183-case live Kafka ACL matrix passes, and — after the repository owner created a real GitHub Projects v2 board and supplied a real PAT — two real submissions reached `COMPLETED` with genuine fetch results (`{"findings": []}`, correct for a newly-created, still-empty board; no more `PROJECT_BOARD_FETCH_FAILED`). |
| — | `scrum-master-agent` — ADR-0026 Phase 2, Real Autonomous Board Write Access | 🔄 In progress | [ADR-0028](docs/architecture/decisions/ADR-0028-scrum-master-agent-phase-2.md) (Accepted): the platform's first Agent not driven by a Workflow submission — no `ExecuteTask` consumption, no Kafka wiring at all, no Capability Registry binding. A `PeriodicService` (reused unchanged from the Orchestrator's `DeadlineReconciler`) wakes it hourly to propose and dispatch real write actions against the same board `scrum.status` reads, bounded by a new platform-wide kill switch, a 10-actions/$1-per-day hard cap, and a durable append-only audit log (`agent.autonomous_actions`, migration 0009, agent schema version 4→5) — all new, all DB-backed, all checked every cycle. A separate, `project`+`repo`-scoped PAT from `scrum-status-agent`'s (per-role least privilege). Deployed to the Mac Docker host and live-verified: real board fetch and a real Anthropic completion both succeeded on live cycles; the 4 real-Postgres `AutonomousStatePort` integration tests passed. Live deployment surfaced and fixed a bug unit/component tests missed (`run_cycle()` was building an already-elapsed AI Router deadline). No real write action has been taken yet — the board is currently empty, and the first real write action still awaits an explicit go-ahead per this ADR's own caveat. |
| — | `scrum-master-agent` — Rounding Out the Action Set | ✅ Done | [ADR-0029](docs/architecture/decisions/ADR-0029-scrum-master-agent-action-set-expansion.md) (Accepted): the fast-follow ADR-0028 Decision 1 flagged — completes ADR-0026 Decision 1's full six-action grant for this role with `close_issue`/`relabel`/`reassign` (REST `PATCH`/`PUT` calls, full-replace semantics for labels/assignees rather than an add/remove delta). No new credential, no new migration — the existing PAT and `agent.autonomous_*` tables already cover it. The proposed-action parser gains its first bounded string-list field type (for `labels`/`assignees`) alongside the existing scalar-string fields. Deployed and live-verified on the Mac Docker host. |
| — | `product-owner-agent` — ADR-0026 Phase 3 | 🔄 In progress | [ADR-0030](docs/architecture/decisions/ADR-0030-product-owner-agent-phase-3.md) (Accepted): the platform's second `PeriodicService`-driven, non-Workflow-driven Agent (after `scrum-master-agent`) — same zero-Kafka, no-Registry-binding shape. Full ADR-0026 Decision 1 action set delivered from day one (repository owner's choice, no MVP-narrowing step this time): `create_ticket`/`edit_ticket`/`close_ticket`/`archive_draft_ticket`/`reprioritize`/`adjust_sprint_scope` against the same board `scrum-master-agent` also writes to. Zero new migration — `agent.autonomous_role_budget`/`agent.autonomous_actions`' per-role design (ADR-0028) pays off immediately for a second role; the platform-wide kill switch (ADR-0026 Decision 7) already covers it too. A new shared `_AutonomousRoleRuntimeConfigBase` and `_autonomous_shared.py` (the two pure helpers both roles need) reduce this role's marginal engineering cost versus Phase 2. A separate, `project`+`repo`-scoped PAT from both other roles'. Deployed to the Mac Docker host; now running with a real PAT — a live cycle showed a genuine board fetch and a genuine Anthropic completion both succeed. No action proposed yet (nothing new to react to beyond the existing test card). |
| — | `principal-developer-agent` — ADR-0026 Phase 4 | ✅ Done | [ADR-0031](docs/architecture/decisions/ADR-0031-principal-developer-agent-phase-4.md) (Accepted): the platform's third `PeriodicService`-driven Agent and ADR-0026's last authorized phase — real PR review (`request_changes`) and **merge** rights, the highest-blast-radius and first genuinely irreversible action any role in this platform can take. `merge` is gated on GitHub's own `mergeable_state == "clean"`, re-checked immediately before the merge call itself to close the TOCTOU gap between the cycle's initial fetch and the dispatch. REST-only `SourceControlPort`/`GitHubSourceControlClient` (`source_control.py`) — no GraphQL, since this role operates on pull requests directly, never the Projects v2 board. Zero new migration (same per-role budget/audit/kill-switch design). Repository owner's explicit choice: any PR with `mergeable_state == "clean"` is eligible, no human-applied label gate. Deployed to the Mac Docker host, initially with a placeholder PAT (live-verified fail-closed behavior), then — after the repository owner's explicit go-ahead — with a real `repo`-scoped PAT: a live cycle showed a genuine board fetch and Anthropic completion, correctly proposing no action since no PR was open at the time. `principal-developer-agent` is now live with real merge capability. |
| — | Autonomous Agent Status — Dashboard Visibility | ✅ Done | [ADR-0032](docs/architecture/decisions/ADR-0032-autonomous-agent-dashboard-visibility.md) (Accepted): a new "Autonomous Agents" dashboard tab shows the kill switch, each role's today-budget usage, and recent audit-log entries for `scrum-master-agent`/`product-owner-agent`/`principal-developer-agent` — none of which appear in the Agents tab, since they hold no Capability Registry binding (ADR-0028 Decision 6). New `GET /api/v1/autonomous-agents` endpoint; `platform` reads the `agent` Postgres schema for the first time (two new read-only `AutonomousStatePort` methods, the same `dsn_agent`-role credential every autonomous role already uses, now also mounted into `platform`), degrading to an inert response if unconfigured rather than failing to start. Also migrates the whole dashboard's styling to Element Plus (the platform's first adopted UI component library) — every existing component (`AgentCard`, tab nav, `AssignmentForm`, `HistoryList`), not just the new panel. |
| — | `frontend-specialist-agent` + `postgres-specialist-agent` — Extending ADR-0026's Autonomous Roles | ✅ Done | [ADR-0033](docs/architecture/decisions/ADR-0033-frontend-and-postgres-specialist-agents.md) (Accepted): two more autonomous roles beyond ADR-0026's original three — **new policy, not a same-phase extension** (ADR-0026 Decision 1 named exactly three roles, and `SECURITY.md`'s own carve-out text explicitly excludes "any new role" from the existing exemption, so this ADR re-amends `SECURITY.md` by name, mirroring exactly how ADR-0026 did it originally). Review-only, no merge rights (repository owner's explicit choice — merge authority stays concentrated in `principal-developer-agent` alone): each proposes `request_changes` only, on pull requests filtered to its own domain (`frontend/` for the frontend specialist; `infrastructure/migrations/`+`src/ai_platform/adapters/persistence/`+`src/ai_platform/ports/persistence/` for the Postgres specialist) **before** any AI Router call sees them. The requested Node.js backend and Oracle DB roles were dropped — neither technology exists anywhere in this codebase. First genuine 1:1 code reuse across two roles: one shared `src/ai_platform/agents/domain_review_agent/` package (`DomainReviewAgent`, parametrized by role/domain label/path prefixes) and `_pull_request_review_shared.py` (`PullRequestReviewPort` has no `merge` method at all — "no merge" is structural, not a policy choice). Zero new migration. Deployed to the Mac Docker host, initially with placeholder PATs (live-verified fail-closed behavior), then with real `repo`-scoped PATs the repository owner supplied — both now live and correctly idle (genuine `200 OK` fetches, no open PRs currently touch either domain). |
| — | `backend-specialist-agent` — A Third Domain Review Role | 🔄 In progress | [ADR-0034](docs/architecture/decisions/ADR-0034-backend-specialist-agent.md) (Accepted): a sixth autonomous role, closing the gap ADR-0033 itself flagged as the clearest remaining one — a Python backend reviewer, filtered to `src/ai_platform/`. Zero new code beyond configuration/wiring: reuses `DomainReviewAgent`/`_pull_request_review_shared.py` (ADR-0033) unchanged, a third `build_*_process()` composition function passing different role/domain-label/path-prefix literals. Deliberately overlaps `postgres-specialist-agent`'s persistence paths (the filter has no exclusion mechanism, and two independent review comments on the same PR is treated as layered depth, not a bug). Same re-amend-`SECURITY.md`-by-name requirement as every new role. Deployed to the Mac Docker host with a placeholder PAT; real credential is a separate, later step. |

## 8. Current State

**What works:**
- Repository-wide contributor guidance ([AGENTS.md](AGENTS.md), [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md)).
- Complete platform architecture description and 19 Accepted ADRs.
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
- A Docker application image (`infrastructure/Dockerfile`), built and run via Docker on a dedicated remote Docker host (a Mac on the LAN; see `infrastructure/README.md` Section 1) — this replaced an earlier local Windows/Podman/WSL2 setup, migrated 2026-08-12.
- A local PostgreSQL + Apache Kafka Compose deployment topology (`infrastructure/compose/`) with pinned images, migrations/role bootstrap, topics, least-privilege ACLs, file-based secrets, and health-ordered startup.
- [ADR-0013](docs/architecture/decisions/ADR-0013-initial-broker-selection-apache-kafka.md): Apache Kafka selected as the initial self-hosted broker instead of Redpanda, superseding only the broker-selection clauses of ADR-0005.
- An automated, opt-in `external_service` pytest suite (`tests/integration/`, 49 tests) exercising the real PostgreSQL/Kafka topology for Event Bus delivery, Concurrency, Security boundary (PostgreSQL role isolation, a 24-case Kafka ACL matrix, secret redaction, audit-failure rollback), and Recovery/crash window (real container kill/restart via `docker exec`) — not the complete Section 19 matrix, but real-service coverage that previously existed only as one-off manual sessions.
- A genuine Windows/WSL2/Podman host-port-forwarding reliability gap, found and diagnosed during Sprint 7, required a documented dual run path (`tests/integration/run-in-network.sh` plus direct host execution for `test_recovery.py`) to work around. That gap no longer exists: the topology moved to a dedicated Docker host (2026-08-12; see `infrastructure/README.md`), and the full `external_service` suite now runs as a single command.
- [docs/operations/README.md](docs/operations/README.md): verified operational documentation (Phase 8) — setup, health, query, recovery, troubleshooting, shutdown/cleanup, contract-generation status, security limitations, and validation commands, every command independently re-run against the real local environment during Sprint 8. Completes Vertical Slice 01's eight-phase plan.
- **A generic capability result model** ([ADR-0015](docs/architecture/decisions/ADR-0015-generic-capability-result-model.md)): `AgentOutcome.result_data`/`WorkflowResult.result_data` (capability-scoped `Mapping[str, object]`) replace the `word_count`-specific fields across wire contracts (discriminated `if`/`then` union in `task_completed.schema.json`), Agent/Orchestrator persistence (migrations `0003`, `0004`), and the public API (`WorkflowResultModel` is now a generic passthrough). `text.word-count` was re-pointed at this model with its full test suite re-run and no regression, before any new capability was built on top of it.
- **An AI Router boundary** ([ADR-0014](docs/architecture/decisions/ADR-0014-ai-router-and-first-ai-backed-agent.md) Sections 1–3, `src/ai_platform/ports/ai_router/`, `src/ai_platform/adapters/ai_router/`): a synchronous, provider-neutral `AIRouterPort.complete()` contract, Anthropic and OpenAI adapters built on the official SDKs (no third-party abstraction library), a deterministic configuration-ordered `FallbackAIRouter`, and durable redacted per-call usage tracking (`agent.provider_call_usage`) kept as internal evidence, never surfaced on the public API.
- **Capability-scoped Kafka `task-commands` routing** ([ADR-0014](docs/architecture/decisions/ADR-0014-ai-router-and-first-ai-backed-agent.md) Section 6), resolving the routing-model review ADR-0005 Section 5 flagged for a second Agent class: `task-commands` stays one logical channel, but its physical topic is now computed per capability (`command_topic_binding_for_capability`), so a second Agent class's consumer group never receives the first class's commands.
- **`text.summarize` v1.0** (`src/ai_platform/agents/summarize_agent/`), the platform's second built-in Agent and the first to call a real external AI provider. Its lifecycle adds a durable pre-call claim (`AgentOutcomeTransactionPort.claim_provider_call`) before invoking the AI Router, per ADR-0014 Section 5's execution-model requirements for a non-deterministic, provider-backed side effect (distinct from `text.word-count`'s safe-to-recompute model). A redelivery that finds its own unresolved claim resolves conservatively to a `PROVIDER_CALL_OUTCOME_UNKNOWN` failure rather than re-calling the provider or blocking (ADR-0016). Wired into `runtime/composition.py`, the Registry, and a `summarize-agent` Compose service with its own Kafka principals and capability-scoped topic.
- **`code.review` v1.0** (`src/ai_platform/agents/review_agent/`, [ADR-0018](docs/architecture/decisions/ADR-0018-software-team-persona-capabilities.md)), the platform's third capability: a diff/patch in, a structured advisory findings list out (file, line, summary, severity), never applied automatically. Same durable-claim lifecycle and AI Router machinery as `text.summarize`, its own `review-agent` Compose service/Kafka principals/Registry binding.
- **`ui.review` v1.0** (`src/ai_platform/agents/ui_review_agent/`, [ADR-0019](docs/architecture/decisions/ADR-0019-ui-review-capability.md), Sprint 11), the platform's fourth capability and third AI-backed one: a deterministic, read-only Playwright/Chromium capture of a hardcoded review target (the platform's own dashboard — no configuration path widens this, an intentional SSRF-conscious design choice) feeds exactly one AI Router call, same single-shot shape as `code.review`. Ships as its own deployable with a **dedicated Docker image** (`infrastructure/ui-review-agent/Dockerfile`) so Chromium's footprint stays isolated to just this service.
- **`architecture.review` v1.0** (`src/ai_platform/agents/architecture_review_agent/`, [ADR-0020](docs/architecture/decisions/ADR-0020-architecture-review-capability.md)), the platform's fifth capability and fourth AI-backed one: structurally identical to `code.review` end to end, no new external side effect or architecture — a proposed architectural change/design doc/ADR draft in, `{section, summary, severity}` findings out. Same durable-claim lifecycle and AI Router machinery, its own `architecture-review-agent` Compose service/Kafka principals/Registry binding.
- **`data.analysis` v1.0** (`src/ai_platform/agents/data_analysis_agent/`, [ADR-0021](docs/architecture/decisions/ADR-0021-data-analysis-capability.md)), the platform's sixth capability and fifth AI-backed one: structurally identical to `architecture.review` — a dataset excerpt/metrics summary/usage report in, `{metric, summary, severity}` findings out. Its own `data-analysis-agent` Compose service/Kafka principals/Registry binding.
- **`technical.review` v1.0** (`src/ai_platform/agents/technical_review_agent/`, [ADR-0022](docs/architecture/decisions/ADR-0022-technical-review-capability.md)), the platform's seventh capability and sixth AI-backed one: structurally identical to `data.analysis` — a proposed data model/schema/API contract/service-boundary design in, `{component, summary, severity}` findings out. Closes out all six ADR-0018 Decision 2 personas. Its own `technical-review-agent` Compose service/Kafka principals/Registry binding.
- **`assignment.route` v1.0** (`src/ai_platform/agents/assignment_route_agent/`, [ADR-0023](docs/architecture/decisions/ADR-0023-assignment-route-capability.md)), the platform's eighth capability and seventh AI-backed one — not one of the twelve ADR-0018 personas: a free-text assignment in, a `{"assignments": [{capability, rationale}]}` recommendation list out (1–6 of the other capabilities), never dispatched automatically. Its own `assignment-route-agent` Compose service/Kafka principals/Registry binding, plus `infrastructure/compose/scripts/submit-assignment.py` — the caller-side script that submits an assignment, reads the recommendation, fans out to every recommended capability, and prints a combined report, all through ordinary Workflow API calls with no new platform/Orchestrator/Agent architecture (deliberately keeping ADR-0014 Section 9's tool-calling scope-out and ADR-0017's deferred Orchestrator-level AI invocation question both untouched).
- **`security.review` v1.0** (`src/ai_platform/agents/security_review_agent/`, [ADR-0025](docs/architecture/decisions/ADR-0025-security-review-capability.md)), the platform's ninth capability and eighth AI-backed one — not one of the twelve ADR-0018 personas (a fresh fit check against Decision 1's admission policy, since Security was never assessed there): structurally identical to `technical.review` — a code diff/configuration file/infrastructure-as-code snippet/design description in, `{location, summary, severity}` findings out, with an adversarial security lens (injection, auth/authz gaps, secrets handling, insecure defaults, SSRF/path-traversal-shaped issues, unsafe deserialization) instead of `code.review`'s general quality lens. Also a routable `assignment.route` target. Its own `security-review-agent` Compose service/Kafka principals/Registry binding.
- **`scrum.status` v1.0** (`src/ai_platform/agents/scrum_status_agent/`, [ADR-0027](docs/architecture/decisions/ADR-0027-scrum-status-capability.md), ADR-0026 Phase 1), the platform's tenth capability and ninth AI-backed one: the same fetch-then-single-AI-call shape `ui.review` established — a deterministic, read-only GitHub Projects v2 GraphQL fetch (`ProjectBoardPort`/`GitHubProjectsBoardReader`, an injectable-transport seam for fast deterministic unit tests with `httpx.MockTransport`, no real network needed) feeds one AI Router call, `{location, summary, severity}` findings out. Unlike `ui.review`, the fetch target (project owner/number) is ordinary config, not a hardcoded constant — an authenticated, PAT-scoped API call has no SSRF-shaped risk to close off. Its own `scrum-status-agent` Compose service/Kafka principals/Registry binding, fully live-verified on the Mac Docker host against a real GitHub Projects v2 board and a real PAT (ADR-0027's Implementation Status).
- **[ADR-0026](docs/architecture/decisions/ADR-0026-autonomous-team-agents.md): Autonomous Team Agents** (Accepted, policy/architecture only) — authorizes three future roles to take real, hard-to-reverse actions with no per-action human approval, narrowly amending `SECURITY.md`'s Human Approval for High-Impact Actions policy. `scrum.status` above is its Phase 1.
- **`scrum-master-agent`** (`src/ai_platform/agents/scrum_master_agent/`, [ADR-0028](docs/architecture/decisions/ADR-0028-scrum-master-agent-phase-2.md), ADR-0026 Phase 2) — the platform's first Agent that is not driven by a Workflow submission: no `ExecuteTask` consumption, no Kafka wiring at all (`build_scrum_master_process` in `runtime/composition.py`, a parallel, leaner composition path than `build_agent_process`), no Capability Registry binding. Its only service is a `PeriodicService` (reused unchanged from the Orchestrator's `DeadlineReconciler`) calling `ScrumMasterAgent.run_cycle()` hourly: check the kill switch, check today's budget, fetch the board, one AI Router call proposing a bounded batch of actions, strict JSON-shape parse, then dispatch each of `set_status`/`add_comment`/`create_draft_item` independently (a narrower MVP than ADR-0026's full six-action target) via a new `ProjectTrackerPort`/`GitHubProjectsTrackerClient` (`tracker.py`, extending `scrum_status_agent`'s read-only fetch with three GraphQL/REST write mutations). Three new DB-backed safety mechanisms (migration 0009, `agent` schema version 4→5): `agent.autonomous_kill_switch` (platform-wide, checked first every cycle), `agent.autonomous_role_budget` (10 actions/$1 estimated spend per UTC day, repository owner's explicit choice), `agent.autonomous_actions` (append-only audit log, one row per attempted action). A separate `project`+`repo`-scoped PAT from `scrum-status-agent`'s read-only one (ADR-0028 Decision 4, per-role least privilege). Live on the Mac Docker host as of 2026-08-16; see ADR-0028's Implementation Status for the live-verification detail and the deadline bug it surfaced.
- **`scrum-master-agent`'s action set rounded out** (`close_issue`/`relabel`/`reassign`, [ADR-0029](docs/architecture/decisions/ADR-0029-scrum-master-agent-action-set-expansion.md)) — the fast-follow ADR-0028 Decision 1 deferred, completing ADR-0026 Decision 1's full six-action grant for this role. No new credential or migration; the proposed-action parser's first bounded string-list field type (for `labels`/`assignees`).
- **`product-owner-agent`** (`src/ai_platform/agents/product_owner_agent/`, [ADR-0030](docs/architecture/decisions/ADR-0030-product-owner-agent-phase-3.md), ADR-0026 Phase 3) — the platform's second `PeriodicService`-driven Agent, structurally identical to `scrum-master-agent` (`build_product_owner_process` in `runtime/composition.py`, same zero-Kafka/no-Registry-binding shape). Full ADR-0026 Decision 1 action set from day one (repository owner's choice — no MVP-narrowing step this time, unlike Phase 2): `create_ticket`/`edit_ticket`/`close_ticket`/`archive_draft_ticket`/`reprioritize`/`adjust_sprint_scope` via a new `BacklogTrackerPort`/`GitHubProjectsBacklogClient` (`tracker.py`, its own copy of the GraphQL/REST patterns `scrum_master_agent.tracker` established, extended with `updateProjectV2ItemPosition`/`archiveProjectV2Item` mutations). Zero new migration — `agent.autonomous_role_budget`/`agent.autonomous_actions`'s per-role design and the platform-wide kill switch (both from migration 0009) already cover a second role; new state is just `role='product-owner'` rows. New shared `_AutonomousRoleRuntimeConfigBase` (`runtime/configuration.py`) and `_autonomous_shared.py` (the two pure helpers `estimate_spend_cents`/`strip_markdown_json_fence`, previously duplicated only in `scrum_master_agent`) reduce this role's marginal engineering cost. A separate `project`+`repo`-scoped PAT from both other roles' (ADR-0028 Decision 4's per-role least privilege, applied a third time). Deployed to the Mac Docker host, initially with a placeholder PAT (live-verified fail-closed behavior against a real GitHub `401`), then with a real PAT the repository owner supplied — a live cycle showed a genuine board fetch and genuine Anthropic completion both succeeding.
- **`principal-developer-agent`** (`src/ai_platform/agents/principal_developer_agent/`, [ADR-0031](docs/architecture/decisions/ADR-0031-principal-developer-agent-phase-4.md), ADR-0026 Phase 4) — the platform's third `PeriodicService`-driven Agent and the last phase ADR-0026 itself authorizes: real PR review (`request_changes`) and **merge** rights via a new REST-only `SourceControlPort`/`GitHubSourceControlClient` (`source_control.py` — no GraphQL, unlike the other two roles, since this role operates on pull requests directly rather than the Projects v2 board). `merge` is gated on GitHub's own `mergeable_state == "clean"` and **re-checked immediately before the merge call itself** to close the TOCTOU gap between the cycle's initial fetch and the dispatch — the one mechanism specific to this role given `merge` is the platform's first genuinely irreversible autonomous action. Repository owner's explicit choice: any PR with `mergeable_state == "clean"` is eligible, no human-applied label gate (closer to ADR-0026's original full-autonomy framing than a gated alternative). Zero new migration; reuses `_AutonomousRoleRuntimeConfigBase`/`_autonomous_shared.py` from the Phase 3 refactor, adding only its own `github_repo_owner`/`github_repo_name` fields (no project number — this role never touches Projects v2). A fourth distinct GitHub PAT (`repo` scope). **Deployed to the Mac Docker host with an obviously-fake placeholder credential only (ADR-0031 Decision 5)** — unlike every other role's credential rollout, this one is a deliberate, separate decision still awaiting the repository owner's explicit go-ahead.
- **Real Anthropic (primary) and OpenAI (fallback) AI provider credentials are now configured** (`infrastructure/compose/secrets/`, git-ignored) and all nine AI-backed capabilities are live-verified with genuine model completions — real Anthropic (Claude Haiku 4.5) round-trips for `text.summarize`/`code.review`/`ui.review`/`architecture.review`/`data.analysis`/`technical.review`/`assignment.route`/`security.review`/`scrum.status` all confirmed working end to end, including a real-model `code.review` catching a planted hardcoded password + SQL injection, a real-model `ui.review` catching genuine accessibility issues on the live dashboard, a real-model `data.analysis` correctly correlating a four-metric anomaly across an otherwise-stable dataset, a real-model `technical.review` catching eight genuine schema/API design issues in a deliberately under-specified proposal, a real-model `assignment.route` + `submit-assignment.py` correctly splitting a mixed assignment across `technical.review`/`data.analysis` end to end, a real-model `security.review` catching two SQL injections, a hardcoded API key, and a missing auth check in a deliberately vulnerable snippet, and a real-model `scrum.status` correctly fetching and reporting on the repository owner's real (currently empty) GitHub Projects v2 board via a real `read:project`-scoped PAT. The OpenAI fallback path itself has not yet been exercised (Anthropic has never failed in testing).
- **`GET /api/v1/agents`** (`src/ai_platform/api/app.py`): a read-only, fully generic Capability Registry status endpoint — renders whatever bindings exist in `registry.json`, no per-capability code. A new capability appears here automatically once it registers a Compose service + Registry binding (a standing convention documented in `CONTRIBUTING.md`).
- **A Vue.js agent status dashboard** (`frontend/dashboard/`), containerized behind nginx sharing `platform`'s network namespace, consuming `GET /api/v1/agents` — equally generic, zero capability-specific code, live and reachable at the Mac Docker host's published port. Now four tabs: Agents, Submit assignment (ADR-0023), History (ADR-0024), and Autonomous Agents (ADR-0032).
- **Autonomous Agent Status dashboard panel + Element Plus migration** ([ADR-0032](docs/architecture/decisions/ADR-0032-autonomous-agent-dashboard-visibility.md)) — a new "Autonomous Agents" tab (`AutonomousAgentsPanel.vue`) shows the platform-wide kill switch, each of the three autonomous roles' today-budget usage (`el-progress` against the deployed 10-actions/100¢ caps), and the most recent audit-log entries, backed by a new `GET /api/v1/autonomous-agents` endpoint. Two new `SELECT`-only `AutonomousStatePort` methods (`list_role_budgets`, `list_recent_actions`); `platform` now also holds the same `dsn_agent`-role credential every autonomous role already uses, opening a **second** connection pool into the `agent` schema for the first time any process has crossed that boundary — an optional config field (`agent_database_dsn`), so `platform` still starts and the endpoint degrades to an inert response if it's unconfigured. Bundled in the same PR: the whole dashboard's styling migrates to Element Plus (`AgentCard`/tab nav/`AssignmentForm`/`HistoryList`, not just the new panel — repository owner's explicit choice), the platform's first adopted UI component library, replacing the hand-rolled custom-property design tokens every component used before.
- **`frontend-specialist-agent` + `postgres-specialist-agent`** ([ADR-0033](docs/architecture/decisions/ADR-0033-frontend-and-postgres-specialist-agents.md)) — two more autonomous roles beyond ADR-0026's original three, genuinely new policy scope (ADR-0026 Decision 1 named exactly three roles; `SECURITY.md`'s carve-out text explicitly excludes "any new role" from the prior exemption, so this ADR re-amends `SECURITY.md` by name). Review-only (`request_changes`, no merge — `PullRequestReviewPort` has no merge method at all, a structural boundary), each filtered to pull requests touching its own domain's file paths before any AI Router call sees them (`frontend/` vs. `infrastructure/migrations/`+the two `persistence/` port/adapter directories). The requested Node.js backend and Oracle DB roles were dropped as not matching this codebase. First genuine 1:1 code reuse across two autonomous roles: one shared `domain_review_agent` package and `_pull_request_review_shared.py`, parametrized by role/domain label/path prefixes rather than duplicated. Zero new migration; two more placeholder-only `repo`-scoped PATs.
- **`backend-specialist-agent`** ([ADR-0034](docs/architecture/decisions/ADR-0034-backend-specialist-agent.md)) — a sixth autonomous role, the gap ADR-0033 itself flagged as the clearest remaining one: a Python backend reviewer filtered to `src/ai_platform/`. Zero new code beyond configuration and wiring — reuses `domain_review_agent`/`_pull_request_review_shared.py` unchanged, a third `build_*_process()` composition function. Deliberately overlaps `postgres-specialist-agent`'s persistence paths (the path-prefix filter has no exclusion mechanism; two independent review comments on the same PR is layered depth, not a bug). `SECURITY.md` re-amended a third time, naming this role explicitly.
- **`GET /api/v1/workflows`** ([ADR-0024](docs/architecture/decisions/ADR-0024-submission-history.md)): newest-first, cursor-paginated (`limit`/`before`) submission history, optionally filtered by `capability` — the first paginated list endpoint in this API. Backed by an additive `orchestrator.submission_history` table (migration 0008), not a change to the `Workflow` aggregate; state/result are always read fresh via a join, never a cached snapshot. The dashboard's History tab is its first consumer.
- The root cause of the multi-sprint `PLATFORM_SHUTDOWN_INCOMPLETE`/`AGENT_SHUTDOWN_INCOMPLETE` flakiness (previously misattributed to Windows/Podman host issues, then vague "pre-existing host instability") is found and fixed: `runtime/composition.py`'s Orchestrator `command_publisher` was never given `environment=`, so it crashed on *any* capability-scoped Kafka publish. Diagnostic logging (`shared/logging`'s `JsonLogFormatter`, previously silently dropping the exception it was supposed to log) is what finally surfaced it.

**What doesn't work yet:**
- No contract code-generation tooling (explicitly deferred since Phase 2, still open).
- Portable runtime proof of Kafka producer, consumer-group, and quarantine authorization remains an explicit architecture gap; a metadata probe cannot establish those permissions without adding a new canary contract or overprivileged ACL introspection. Deferred to a future ADR, per [docs/sprint-6/progress.md](docs/sprint-6/progress.md).
- Multi-principal authorization / owner-mismatch disclosure paths are structurally unreachable under the current single-principal `LocalDevelopmentAuthorizationPolicy` and are not implemented.
- Deliberate, operator-initiated quarantine replay has not been exercised (quarantine itself has been, repeatedly).
- The Compose topology is explicitly local-only: single broker, single database node, no TLS, application ports not reachable from the host by design (loopback-only).
- A dedicated pytest-automated full-container End-to-End harness (driving `platform`/`test-agent`/`summarize-agent` as black boxes over HTTP, not exercising adapters/application services directly the way `tests/integration/` does) — the one Section 19 item Sprint 10 did not pick up; see "What's next" below.
- On this development host specifically, direct connections from Windows-native Python to the topology's host-published ports remain unreliable at the protocol-handshake level even after fixing the underlying WSL2/firewall configuration issues; the documented workaround (`run-in-network.sh`) is a permanent, working capability, not merely a stopgap, but the root cause of the remaining handshake-level flakiness is not fully understood.
- Two stale Windows/Podman-migration references remain: `tests/integration/conftest.py`'s auto-bring-up fixture (`_podman_available`/`_compose_up`) still shells out to `podman`, which doesn't exist on the current Docker host — the `AI_PLATFORM_TEST_SKIP_COMPOSE_UP=1` escape hatch works around it, but the fixture itself hasn't been updated. A handful of comments elsewhere were already fixed in passing (`docker-compose.yml`, `docs/operations/README.md`).
- The OpenAI fallback provider has real credentials configured but has never actually been exercised end-to-end (Anthropic has never failed in testing) — the config path is proven at startup (router construction succeeds), not the live fallback behavior itself.
- ADR-0014's Section 8 open questions are all resolved (see ADR-0016/ADR-0017 below) except Orchestrator-level AI Router invocation, which was deliberately ratified as staying out of scope rather than left open.

**What's next:**
- The pytest-automated full-container End-to-End harness (driving `platform`/agents as black boxes over HTTP) — deferred since Sprint 7, still not picked up by anyone across five sprints since.
- `tests/integration/conftest.py`'s leftover Podman auto-bring-up fixture (above) — low-priority cleanup, not blocking anything since the skip-compose-up escape hatch works.
- Exercising the OpenAI fallback path for real (would need a way to make the Anthropic call fail deliberately, or simply wait for it to happen naturally).
- A ninth platform capability, if wanted, needs a fresh fit assessment (per ADR-0018 Decision 2's own "does not fit" list) — all six original personas are built, and `assignment.route` already covers the team-routing gap.
- `submit-assignment.py`'s fan-out is not durable/resumable the way the platform's own submission machinery is (ADR-0023's documented "Negative" consequence) — if it's killed mid-fan-out, the individual workflows it already submitted still complete normally, but the combined report is lost. A durable version would require exactly the in-platform coordinator ADR-0023 deliberately declined to build.
- A read-write Azure infrastructure capability was discussed and explicitly deferred: it's a categorically different risk class (destructive/irreversible real-cloud actions) that needs a SECURITY.md-required human-approval-gate mechanism this codebase doesn't have yet, plus likely genuine agentic tool-calling (a real architecture gap, not just new capability code) — not undertaken without that groundwork first.

For the full history of how the platform got here: [ADR-0016](docs/architecture/decisions/ADR-0016-provider-call-claim-reconciliation.md)/[ADR-0017](docs/architecture/decisions/ADR-0017-ai-router-follow-up-decisions.md) resolved ADR-0014 Section 8; [docs/sprint-10/progress.md](docs/sprint-10/progress.md) has Sprint 10's full workstream account (Phase 7 Section 19 continuation, the operator runbook, the readiness-routing fix); [docs/sprint-11/plan.md](docs/sprint-11/plan.md) has `ui.review`'s.

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

A complete deployment topology exists under
[infrastructure/](infrastructure/): versioned migrations, credential-free
PostgreSQL permission roles, the application Docker image, and a Docker
Compose topology (PostgreSQL + Apache Kafka + the platform/Test Agent
processes) with least-privilege ACLs and file-based secrets, run on a
dedicated Docker host (a Mac on the LAN) rather than any individual
developer's machine. It is still explicitly non-production (single broker,
single database node, no TLS, loopback-only application exposure) — see
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
