# QA Sprint 8 Sign-Off

Date: 2026-08-05
Tester: Ivy (QA)

## Scope

Vertical Slice 01, Phase 8: verified operational documentation. See
[docs/sprint-8/done.md](../sprint-8/done.md) for the complete account.

## Test Results

- Local suite: 339 passed, 49 deselected (`uv run pytest -q`) — unaffected
  by this documentation-only sprint.
- Documentation verification: every command in
  [docs/operations/README.md](../operations/README.md) was independently
  re-run against the live local environment during this sprint (Sections
  1–4 and 9 by execution; Section 5 by inspection against
  `infrastructure/compose/docker-compose.yml`, since running its
  destructive commands would have torn down the shared topology). Two
  inaccuracies found this way were corrected before merge.

## Tooling Verification

- `uv run ruff format --check .` — no reformatting needed.
- `uv run ruff check .` — all checks passed.
- `uv run basedpyright` (strict mode) — 0 errors, 0 warnings, 0 notes.

## Real-Service Verification

- Health checks (`/health/ready`, `/health/live`, container health, Kafka
  consumer-group describe) all confirmed against the live topology.
- A workflow was submitted and read back for real, reaching `COMPLETED`
  with the correct `word_count`.
- Both documented recovery scenarios (Test Agent crash, platform crash
  including the `test-agent` network-namespace recreation step) were
  actually executed, with recovery confirmed via a fresh workflow
  submission afterward. Both application containers were confirmed
  running and ready at the end.
- `bash tests/integration/run-in-network.sh -v` and
  `uv run pytest -m external_service tests/integration/test_recovery.py -v`
  both run and pass as documented.

## Behavior Coverage

- This sprint added no new application behavior — it is a documentation
  deliverable whose "coverage" is the accuracy of every command against
  the real environment, verified as above.
- The document explicitly states, rather than omits, every known
  limitation: `LocalDevelopmentAuthorizationPolicy`, loopback-only
  exposure, no TLS, single-node/single-broker, file-based secrets,
  structurally-unreachable multi-principal authorization paths, the open
  Kafka authorization-proof question, and the absence of contract
  code-generation tooling.

## Blockers

NONE

## Issues Filed

None new. All items carried forward from Sprints 6–7 remain open and are
listed plainly in `docs/operations/README.md` Section 7 rather than
re-filed: the Kafka producer/consumer-group/quarantine authorization-proof
design question, the remaining Section 19 test categories not automated in
Sprint 7, and the not-fully-understood direct-connection reliability gap
on this development host (worked around, not root-caused).

## Result

✅ PASS — No blockers. Sprint 8 (Phase 8) is ready to merge. This
completes Vertical Slice 01's eight-phase plan as originally specified,
with the Phase 7 scope caveat carried forward honestly (see
[docs/sprint-7/plan.md](../sprint-7/plan.md)'s "Out of scope"). No
production-readiness claim is made anywhere in this sprint's
documentation.
