# Sprint 10 — Topology Re-validation, Operator Runbook, ADR-0014 Follow-Ups, Phase 7 Continuation

> Sprint goal: bring the local topology back in sync with Sprint 9/ADR-0016,
> close the operator-runbook gap ADR-0016 explicitly deferred, resolve as
> much of ADR-0014 Section 8 as can be decided without the repository
> owner, and continue Phase 7's Section 19 test matrix.
> Branch: per workstream (see below) — this sprint spans more than one PR,
> unlike Sprints 1–9 which each shipped as a single feature branch.
> Scope authority: [PROJECT_BRIEF.md](../../PROJECT_BRIEF.md) Section 8
> "What's next", [ADR-0014](../architecture/decisions/ADR-0014-ai-router-and-first-ai-backed-agent.md)
> Section 8, [ADR-0016](../architecture/decisions/ADR-0016-provider-call-claim-reconciliation.md)
> "Consequences / Negative"

## Context

Sprint 9 (`text.summarize`, the AI Router) and the ADR-0016 follow-up
(provider-call claim reconciliation) both merged without the running local
Compose topology ever being brought up to date with their schema
migrations and Kafka topic renames — the topology on this host predates
both. Four independent gaps have accumulated as a result, none of which
individually justifies its own sprint, but which don't obviously belong in
one PR together either:

1. The local topology is stale relative to `main`.
2. ADR-0016 shipped without the operator runbook its own "Consequences"
   section says is needed (joining a quarantined command against an
   expired workflow by `task_attempt_id`).
3. Four of ADR-0014 Section 8's five open questions remain open (the
   fifth, the reconciliation window, was resolved by ADR-0016).
4. Phase 7's Section 19 test matrix was deliberately scoped down in
   Sprint 7 (see [docs/sprint-7/plan.md](../sprint-7/plan.md) "Out of
   scope") and has not been revisited since.

## Workstreams and sequencing

1. **Topology re-validation** — bring the running Compose environment's
   database schema and Kafka topics up to date with `main` (migrations
   `0003`–`0007`, capability-scoped topic renames), then re-run the
   `external_service` suite and attempt one real `text.summarize`
   submission end-to-end. The submission is expected to fail at the
   provider call itself, since this environment has only placeholder
   Anthropic/OpenAI credentials — that failure path (quarantine/deadline
   behavior under a real failure, not a fake `AIRouterPort`) is itself the
   validation target, not a live completion. Done first: it is the
   lowest-risk, most self-contained piece, and gives the operator-runbook
   workstream something real to validate against (a real quarantined
   command + a real expired workflow, joinable by `task_attempt_id`).
2. **ADR-0016 operator runbook** — document the manual reconciliation
   procedure ADR-0016's "Negative" consequences deferred: how an operator
   joins `agent.transport_rejections`/the `.quarantine` topic against
   `agent.provider_call_claims` and the Orchestrator's expired-workflow
   state by `task_attempt_id`, and what to check on the provider's own
   dashboard/billing using the claim's idempotency key. Written and
   verified against workstream 1's real quarantined/expired case if
   available, falling back to the existing `external_service` recovery
   tests' fixtures otherwise.
3. **ADR-0014 Section 8 follow-ups** — of the four remaining open
   questions, only some are engineering-scoped; the rest are decisions
   only the repository owner can make (see "Decisions needed" below).
   This workstream drafts a follow-up ADR capturing whichever subset gets
   resolved.
4. **Phase 7 Section 19 continuation** — pick up the test categories
   Sprint 7 explicitly deferred (Contract; most of
   Idempotency/Ownership/State-machine/Agent-readiness/Audit-observability;
   the full Correlation Normalization table) and/or a pytest-automated
   full-container E2E harness. Largest and most open-ended workstream;
   scoped down further once workstreams 1–3 land, since re-validation may
   surface issues that change its priority.

## Decisions needed from the repository owner before workstream 3 can complete

ADR-0014 Section 8's four remaining open questions split into two kinds:

- **Engineering-scoped, resolvable in this sprint:** exact retry-budget
  numbers (currently generic, deployment-wide
  `consumer_maximum_processing_attempts`/retry-delay config, not tuned
  per ADR-0016's "Negative" note that a very short budget quarantines a
  genuinely in-flight call too eagerly).
- **Product/scope decisions, not mine to make unilaterally:**
  - The approved Claude/OpenAI model list (a cost/quality/compliance
    choice).
  - Whether the Orchestrator itself should ever invoke the AI Router
    (a scope-boundary decision — currently only Agents call it).
  - Same-provider-vs-cross-provider fallback ordering (a
    reliability/cost tradeoff with no obviously correct default).

Workstream 3 will draft options for these three and ask before writing
them into an ADR, rather than deciding them silently.

## Scope

**In scope:**

- Everything workstreams 1–4 describe above, to the depth each one's own
  acceptance criteria states.
- Re-running (not rewriting) the existing `external_service` suite; no
  new real-service test categories beyond what workstream 4 explicitly
  adds.

**Explicitly out of scope:**

- Obtaining real Anthropic/OpenAI credentials (repository-owner decision,
  independent of this sprint; PROJECT_BRIEF.md Section 8 already tracks
  it separately).
- A complete Section 19 matrix in one sprint — workstream 4 is
  deliberately open-ended and may itself span into Sprint 11.
- Any production-readiness claim. This remains a local-development-only
  environment (`LocalDevelopmentAuthorizationPolicy`, loopback-only
  Compose topology) regardless of what this sprint validates.

## Acceptance criteria

- [ ] `uv run ruff format --check .`, `uv run ruff check .`,
      `uv run basedpyright`, and `uv run pytest -q` all succeed after each
      workstream.
- [ ] Workstream 1: `external_service` suite passes against the
      re-migrated topology; one real `text.summarize` submission is
      attempted and its outcome (success or provider-call failure) is
      recorded, not assumed.
- [ ] Workstream 2: the runbook lives under `docs/operations/` alongside
      the existing verified operational documentation, and every command
      in it is actually run against a real quarantined/expired case
      before being written down (same verification bar
      `docs/operations/README.md` already set in Sprint 8).
- [ ] Workstream 3: a follow-up ADR is drafted for the
      repository-owner's decision before being marked Accepted; the
      retry-budget question is resolved with a stated rationale.
- [ ] Workstream 4: whatever subset of Section 19 is picked up has real
      test coverage, not a plan-only description.

## Out of scope

See "Explicitly out of scope" above.
