# Sprint 5 — Team Consilium

> Reviewing Sprint 5 scope: Vertical Slice 01, Phase 5 ("Workflow API") —
> submit/read/health HTTP operations, trusted synthetic request context,
> correlation normalization (ADR-0012), RFC 8785 fingerprinting, and stable
> Problem Details. Composed against the Phase 3 `SubmissionOrchestrator`/
> `TerminalEventProcessor` using in-memory port implementations (still no
> real database/Kafka adapters — Phase 6).

## Remy (Producer)

This phase finally makes the platform reachable over HTTP, but it must
not smuggle in Phase 6 scope. The Workflow API talks to
`SubmissionOrchestrator` and `TerminalEventProcessor` (already built,
Sprint 3), which in turn talk to the Phase 2 ports — for this sprint those
ports are still backed by in-memory fakes assembled at app-startup, not a
real PostgreSQL/Redpanda. That's enough to prove the full HTTP contract
end-to-end without Docker: FastAPI's `TestClient` (httpx-based) runs the
ASGI app in-process, so we get real HTTP-semantics testing without a
running server or any external infrastructure.

## Dash (Tooling Engineer)

ADR-0003 specifically verified FastAPI + Pydantic v2 for CPython 3.14
compatibility, so that's the framework. I added `fastapi`, `uvicorn`
(for actually running it locally per PROJECT_BRIEF Section 10), and
`httpx` (test-only, for `TestClient`) as dependencies. For RFC 8785 JSON
canonicalization (needed for the request fingerprint, Section 6), I'm
using the `rfc8785` package (Trail of Bits, pure Python, no dependencies)
rather than hand-rolling canonical JSON serialization — that has enough
subtle correctness pitfalls (float formatting, escaping, key ordering)
that reusing an audited implementation is clearly the right call per
AGENTS.md's "depend on documented abstractions" principle.

## Sage (API Engineer)

The ordering in Section 4 and Section 6 matters: the trusted security
adapter resolves context (environment, `idempotency_scope_id`,
`current_actor_id`, owner intent, policy identity/revision) *before*
correlation normalization touches anything durable, and correlation
normalization happens *before* the fingerprint is computed, which happens
*before* `SubmissionOrchestrator.submit()` is ever called. I'm building
this as a small per-request pipeline: resolve trusted context -> normalize
correlation -> validate/parse body against the Sprint 1 JSON Schema ->
compute fingerprint -> call `SubmissionOrchestrator.submit()` -> map its
`SubmissionDisposition` to the exact status codes in Section 5's error
table. `LocalDevelopmentAuthorizationPolicy` is deliberately the *only*
policy implementation this sprint — every caller resolves to the same
synthetic principal, so the owner-mismatch/hidden-conflict disclosure
paths in Section 6 (which require distinguishing multiple principals)
are structurally unreachable and are not implemented, not silently
mishandled.

## Ivy (QA Engineer)

Test surface: correlation normalization for all five ADR-0012 scenarios
(missing, valid, malformed, oversized, control-character) using
`TestClient`; fingerprint determinism (same canonical inputs produce the
same digest regardless of JSON key order); the full Section 5 error table
via real HTTP requests (invalid body -> 400, first acceptance -> 202,
replay -> 200, conflict -> 409, no eligible Agent -> 503); `GET` returning
a safe 404 for both a missing workflow and one it never processes
(indistinguishable, per Section 5); and `/health/live` never depending on
anything. I will not claim to test real database/Kafka failure behavior —
that needs Phase 6's concrete adapters and is explicitly out of scope.

## Disagreements

1. **Remy vs. Sage — should `/health/ready` report readiness of the
   in-memory port "adapters" used this sprint.** Remy wants
   `/health/ready` to always return `200` since there's no real dependency
   to be unready about yet. Sage argues that's misleading: Section 8 says
   "core/API readiness" must reflect whether "configuration, PostgreSQL,
   Event Bus adapters, Registry, and recovery workers are usable" — none
   of the persistence/broker adapters exist yet, so claiming full
   readiness would misrepresent the slice. **Resolution:** `/health/ready`
   reports readiness based only on what this sprint actually constructs
   (the Registry snapshot loading successfully); it does not claim
   database/broker readiness that doesn't exist, and the response/docs
   explicitly state this is a partial, Phase-5-scoped readiness signal,
   not the full Section 8 semantics.

2. **Ivy vs. Sage — should the fingerprint's "API contract major" field be
   a real, evolvable version or a fixed constant.** Ivy wants it modeled
   as a real input so future contract-version tests are possible. Sage
   argues that since this slice has exactly one API contract major (`v1`)
   and Section 5 says versioning evolution is a "future" concern, a fixed
   constant accurately reflects current scope without inventing
   unused multi-version machinery. **Resolution:** the fingerprint
   includes `api_contract_major: "1"` as a fixed value for this slice,
   documented as the seam where a real multi-version scheme would plug in
   later — not built now.

## Outcome

Sprint 5 scope confirmed as the full Workflow API contract: trusted
synthetic context, ADR-0012 correlation normalization, RFC 8785
fingerprinting, `workflow.submit`/`workflow.read`/health operations, and
Problem Details error mapping — composed over Sprint 3's application
services with in-memory port implementations, tested end-to-end via
FastAPI's in-process `TestClient`. Proceeding to `docs/sprint-5/plan.md`.
