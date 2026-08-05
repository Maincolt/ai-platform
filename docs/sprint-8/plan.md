# Sprint 8 — Verified Operational Documentation

> Sprint goal: implement Vertical Slice 01, Phase 8.
> Branch: `feature/sprint-8-verified-operational-documentation`
> Scope authority: [Vertical Slice 01, Section 20, Phase 8](../implementation/vertical-slice-01.md#20-implementation-phases)

## Context

Phase 8's spec is narrow by design: *"Document only demonstrated setup,
health, query, recovery, troubleshooting, shutdown, cleanup, contract
generation, security limitations, and validation commands. Do not claim
production readiness."* This is not new engineering — it is writing down,
precisely and only, what Sprints 6–7 already proved against real
PostgreSQL/Kafka, with every command independently re-verified against the
live environment before being committed to the document.

Phase 7 is not fully complete (Sprint 7 deliberately scoped a subset of the
Section 19 matrix — see `docs/sprint-7/plan.md`'s "Out of scope"). Phase 8
does not require full Phase 7 completion: it only documents what has
actually been demonstrated, and says so plainly wherever something has not
been.

## Scope

**In scope**: one operational document
(`docs/operations/README.md`) covering, for the local
`infrastructure/compose/` deployment only:

- Setup: bringing up the topology and application containers from a clean
  checkout.
- Health: readiness/liveness checks for every component.
- Query: submitting a workflow and reading its state via the real API.
- Recovery: the crash-recovery procedures demonstrated in Sprints 6–7
  (Test Agent crash, platform crash), including the `test-agent`
  network-namespace recreation requirement.
- Troubleshooting: the genuine Windows/WSL2/Podman host-networking issue
  found and resolved in Sprint 7, and the dual test-run-path workaround.
- Shutdown and cleanup: stopping/removing the local topology.
- Contract generation status: there is none (still explicitly deferred
  since Phase 2 — this document says so rather than omitting the topic).
- Security limitations: `LocalDevelopmentAuthorizationPolicy`,
  loopback-only exposure, and every other limitation already documented in
  `SECURITY.md`/ADRs, consolidated in one operator-facing place.
- Validation commands: the exact quality-gate and real-service test
  commands from Sprints 6–7, so a future operator can reproduce the same
  evidence.

**Explicitly out of scope**:

- Any capability, procedure, or command not already demonstrated in
  Sprints 6–7. If Sprint 8 work surfaces a gap, it is either demonstrated
  for real first (and the evidence trail extended) or explicitly marked
  undocumented — never assumed or written from expectation.
- Production deployment, HA, Kubernetes, managed services procedures.
- Contract code-generation tooling (still not built).
- Anything AI Router or additional-Agent related — out of Vertical Slice
  01 entirely.

## Acceptance criteria

- [x] `uv run ruff format --check .` succeeds.
- [x] `uv run ruff check .` succeeds.
- [x] `uv run basedpyright` succeeds in strict mode.
- [x] `uv run pytest -q` succeeds (unaffected by a docs-only sprint).
- [x] Every command in `docs/operations/README.md` has been independently
      re-run against the live local environment during this sprint, not
      copied from earlier sprint docs without re-verification. Two
      inaccuracies found this way were fixed — see
      [done.md](done.md).
- [x] The document makes no production-readiness claim and clearly marks
      every known limitation and undemonstrated capability.

## Out of scope

See "Explicitly out of scope" above.
