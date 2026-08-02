# Ideas Backlog

Future-sprint ideas that are out of scope for the current sprint. See
`PROJECT_BRIEF.md` Section 13 ("For future-sprint ideas: add to
`docs/ideas-backlog.md` rather than expanding the current sprint's scope").

- **Dedicated unit test for `src/ai_platform/runtime/composition.py`.**
  Raised during Sprint 6 PR review: this ~665-line module wires the entire
  platform/Agent process composition (security config, topic mapping,
  persistence, publishers/consumers, readiness) but has no dedicated unit
  test, unlike every other `runtime/` module. A wiring mistake (e.g. the
  wrong `KafkaSecurityConfig` or `LogicalChannel` passed to the wrong
  collaborator) would currently pass the full test suite and only surface
  during manual real-service validation. Sprint 6 validated the composition
  correctness through real end-to-end runs instead; a focused unit test
  asserting the wiring itself (which collaborator gets which config/port)
  would catch this class of regression without needing a live broker/database.
