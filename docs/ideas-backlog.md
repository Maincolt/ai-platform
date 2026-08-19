# Ideas Backlog

Future-sprint ideas that are out of scope for the current sprint. See
`PROJECT_BRIEF.md` Section 13 ("For future-sprint ideas: add to
`docs/ideas-backlog.md` rather than expanding the current sprint's scope").

## `character.profile` capability + accumulating user profile ("digital twin", phase 1)

A continuous profiler role that learns the repository owner's character
over time, as a precursor to an eventual "digital twin" role that could
act on their behalf. Discussed 2026-08-19; deliberately not started.

Proposed shape (see conversation for full reasoning):

- **Local export step**: a periodic script (run locally, e.g. via the
  `loop`/`schedule` skill), reading recent local Claude Code conversation
  transcripts, redacting anything sensitive, and submitting a digest via
  the Workflow API — mirrors `submit-assignment.py`'s existing pattern.
- **New capability `character.profile`**: same bounded-advisory,
  stateless-per-call shape as `data.analysis`/`technical.review` (digest
  in, one AI Router call, structured findings out — e.g.
  `{trait, evidence, confidence}`). Deliberately *not* a `PeriodicService`
  autonomous agent — cadence is driven locally, not by the platform, so
  it stays in the safer capability family rather than the write-capable
  autonomous-agent family.
- **A durable, accumulating profile table**: each submission's findings
  merge into a running profile (latest-value-per-trait), analogous to
  `submission_history` but purpose-built for accumulation rather than a
  flat log.

Guardrails to carry into the eventual ADR:

- Strictly read/accumulate only — no autonomous action, no write rights.
  This is phase 1 (profiler) only; a later "twin" role that acts using
  the profile is an explicit, separate, later decision — not bundled in.
- This is more sensitive than any data the platform has handled so far
  (code diffs, PR text) — the local redaction step is not optional, and
  the profile's dashboard view should likely be restricted to the
  repository owner alone.
- Needs its own ADR (`SECURITY.md`'s carve-out language already requires
  one for "any new role") plus a `security.review` pass specifically on
  the local export script, since it is the one component that reads raw
  local data.

Open question deferred along with everything else: exact scope of what
"conversation transcripts generally" should include/exclude on export.
