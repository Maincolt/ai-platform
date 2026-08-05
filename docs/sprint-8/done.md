# Sprint 8 — Done

> Scope: Vertical Slice 01, Phase 8 (verified operational documentation)
> Branch: `feature/sprint-8-verified-operational-documentation`
> Completed: 2026-08-05

## What was built

One operational document, [`docs/operations/README.md`](../operations/README.md),
covering the local `infrastructure/compose/` deployment:

1. Setup (clean-checkout bring-up sequence).
2. Health (readiness/liveness checks, container health, Kafka consumer
   group status).
3. Query (submitting and reading a workflow through the real API).
4. Recovery (the Test Agent and platform crash scenarios demonstrated in
   Sprints 6–7, including the `test-agent` network-namespace recreation
   requirement — the single most consequential operational gotcha in this
   deployment).
5. Troubleshooting (the genuine Windows/WSL2/Podman host-networking issue
   diagnosed in Sprint 7, and its accepted workaround).
6. Shutdown and cleanup.
7. Security limitations (consolidated from `SECURITY.md`, ADR-0010, and
   the loopback-only/single-node/no-TLS/file-secret realities of this
   deployment).
8. Contract generation status (none exists — stated plainly, not omitted).
9. Validation commands (the quality-gate and real-service test commands
   from Sprints 6–7).

## What was validated

Every command in the document was independently re-run against the real
local environment during this sprint — not copied from earlier sprint docs
without re-verification, per this sprint's own acceptance criteria:

- Setup commands (secret generation, topology/migration bring-up)
  re-run and confirmed idempotent.
- Health-check commands re-run and confirmed to match documented output.
- The query example was actually submitted and read back, reaching
  `COMPLETED` with the correct `word_count`.
- Both recovery scenarios (Test Agent crash, platform crash) were actually
  executed, including the `test-agent` recreation step, with recovery
  confirmed via a fresh workflow submission afterward.
- All four quality gates and both real-service test commands from Section
  9 were run for real.
- Shutdown/cleanup commands were verified by inspection against
  `infrastructure/compose/docker-compose.yml` and the relevant scripts,
  not executed, since running them would have destroyed the shared
  topology and secrets other work depends on — this is stated explicitly
  in the document rather than left ambiguous.

Two inaccuracies were found and fixed during verification (not left for a
future session to discover):

- The setup section's comment about which secret-generation script skips
  already-existing files was imprecise; corrected to describe
  `generate-app-secrets.sh`'s actual (harmless but not skip-based)
  re-run behavior.
- The real-service validation commands needed `MSYS_NO_PATHCONV=1` set
  first on Git Bash/Windows or the `podman run -v` mount in
  `run-in-network.sh` fails — this was missing from the original draft
  and is now documented, along with a note that `test_recovery.py`'s two
  tests can occasionally fail individually on a fast rerun due to the
  same genuine timing races Section 4 describes, which is an accepted,
  documented characteristic of that suite, not an environment defect.

## Quality gates

All four local acceptance gates from [plan.md](plan.md) pass:

- `uv run ruff format --check .`
- `uv run ruff check .`
- `uv run basedpyright` (strict)
- `uv run pytest -q` — 339 passed, 49 deselected (unaffected; this is a
  documentation sprint)

## What needed manual setup

Nothing beyond what Sprints 6–7 already require (`infrastructure/compose/scripts/generate-secrets.sh`
and `generate-app-secrets.sh`, the application image build, `podman
compose --profile app up -d platform test-agent`) — this sprint added no
new setup requirements, only documented the existing ones.

## What's not done / explicitly out of scope

Per [plan.md](plan.md): any capability, procedure, or command not already
demonstrated in Sprints 6–7 (nothing was added or assumed); production
deployment, HA, Kubernetes, or managed-service procedures; contract
code-generation tooling (still not built, and the document says so);
anything AI Router or additional-Agent related, which remains outside
Vertical Slice 01 entirely.

This completes Vertical Slice 01's eight-phase plan as originally
specified, with the caveat carried forward honestly from Sprint 7: Phase
7's full Section 19 test matrix was not completed in full — Sprint 7
automated a deliberately scoped, high-value subset, and Phase 8 documents
only what that subset (plus Sprint 6's manual validation) actually
demonstrated. The remaining Section 19 categories, and any future
multi-agent/AI Router work, remain open items for a future sprint, not
silently claimed as done.
