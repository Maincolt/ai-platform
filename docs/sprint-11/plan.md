# Sprint 11 — `ui.review`: a Playwright-Backed UI Review Capability

> Sprint goal: add the platform's third AI-backed capability, `ui.review`
> (ADR-0019), reviewing the platform's own dashboard for UI/UX/accessibility/
> console-error problems, and establish "every new Agent capability gets a
> Compose service + Registry binding" as a standing convention so it
> appears on the agent status dashboard automatically.
> Branch: per workstream, following ADR-0018's precedent that a
> multi-workstream capability spans more than one PR.
> Scope authority: [ADR-0019](../architecture/decisions/ADR-0019-ui-review-capability.md),
> [PROJECT_BRIEF.md](../../PROJECT_BRIEF.md) Section 8 "What's next"

## Context

This sprint has no `docs/sprint-10`-style multi-workstream backlog behind
it — it exists because the repository owner asked for a new Agent with
Playwright skills, chosen for it to reuse the existing single-shot AI
Router architecture rather than open new agentic/tool-calling ground
(ADR-0014 Section 9 stays closed), and for the dashboard-registration step
to become a default for every future capability, not just this one. See
ADR-0019 for the full architectural reasoning, including why the review
target is hardcoded to the platform's own dashboard rather than
caller-configurable.

Unlike `code.review`, this capability needs one thing neither
`text.summarize` nor `code.review` needed: a real, new runtime dependency
(Playwright/Chromium) with a genuinely open question (does it build cleanly
under this platform's Python 3.14 pin, and at what image-size cost) that
is independent of whether the domain logic itself is correct. That's why
this sprint splits into three PRs instead of ADR-0018's two.

## Workstreams and sequencing

1. **ADR-0019 + domain/contract layer** (this PR) — the `ui_review_agent`
   module, contract schema changes, `runtime/loading.py`/`composition.py`
   wiring (ahead of `code.review`'s own precedent, specifically to avoid
   repeating the `_SUPPORTED_CAPABILITY_NAMES` gotcha ADR-0018 already hit),
   full unit/component/contract test coverage against fakes and a
   placeholder `PageCapturePort`. No Playwright dependency yet — buildable
   and fully tested without Chromium ever being installed anywhere.
2. **Real Playwright integration** — `PlaywrightPageCapture` behind the
   `PageCapturePort` seam, the `playwright` dependency, the opt-in
   real-browser test tier. Resolves whether Python 3.14 support is a
   blocker before merging (checked in ADR-0019: `playwright` 1.62.0
   declares 3.14 support as of this sprint).
3. **Deployment wiring** — dedicated `ui-review-agent` Docker image,
   Compose service, Kafka principals/topics/ACLs, Registry binding, the
   CONTRIBUTING.md standing convention, live verification against the real
   Mac Docker host topology (dashboard shows the new agent with zero
   frontend changes), ADR-0019 moved to Accepted.

## Scope

**In scope:** everything workstreams 1–3 describe above, to ADR-0019's own
stated depth.

**Explicitly out of scope:**

- An agentic, tool-calling execution model (ADR-0019 "Alternatives
  Considered" — a materially larger, separate future decision).
- Screenshot/vision-based review (`AIRouterPort` has no multimodal support
  today — separate future ADR if a real use case emerges).
- An operator-configurable review-target allowlist (ADR-0019 Decision 4 —
  hardcoded for v1, deliberately).
- Real Anthropic/OpenAI provider credentials (same standing deferral
  `text.summarize`/`code.review` already carry).

## Acceptance criteria

- [x] Workstream 1: `uv run ruff format --check .`, `uv run ruff check .`,
      `uv run basedpyright`, and `uv run pytest -q` all succeed; full
      unit/component/contract coverage for `ui_review_agent`, mirroring
      `review_agent`'s pattern.
- [ ] Workstream 2: real Playwright capture implemented and unit-tested
      against a fake; a real-browser smoke test run manually at least once.
- [ ] Workstream 3: `ui-review-agent` starts cleanly on the real topology,
      reaches `READY`, and appears on `GET /api/v1/agents`/the dashboard
      with zero dashboard code changes; `test_kafka_acl_matrix.py` extended
      and passing live; CONTRIBUTING.md's standing convention documented;
      ADR-0019 moved to Accepted with the repository owner's approval.

## Out of scope

See "Explicitly out of scope" above.
