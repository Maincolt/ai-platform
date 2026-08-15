-- ADR-0024: an additive submission-history table, not a change to
-- orchestrator.workflows or the Workflow domain aggregate. Carries the two
-- things persisted nowhere else today (capability + submitted text); state
-- and result are always read fresh via a join back to orchestrator.workflows,
-- so this table never goes stale relative to the real terminal outcome.
-- Apply with the Orchestrator migration identity, never the runtime identity.
-- psql exits on the first error; the open transaction then rolls back in full.

\set ON_ERROR_STOP on

BEGIN;

CREATE TABLE IF NOT EXISTS orchestrator.submission_history (
    workflow_id        TEXT        PRIMARY KEY REFERENCES orchestrator.workflows (workflow_id),
    capability_name    TEXT        NOT NULL,
    capability_version TEXT        NOT NULL,
    input_text         TEXT        NOT NULL,
    submitted_at        TIMESTAMPTZ NOT NULL
);

-- Backs GET /api/v1/workflows's cursor pagination: newest first, optionally
-- filtered to one capability.
CREATE INDEX IF NOT EXISTS submission_history_capability_submitted_idx
    ON orchestrator.submission_history (capability_name, submitted_at DESC);
CREATE INDEX IF NOT EXISTS submission_history_submitted_idx
    ON orchestrator.submission_history (submitted_at DESC);

-- Publish compatibility only after every schema object exists in this transaction.
INSERT INTO orchestrator.schema_version (component, version)
VALUES ('orchestrator', 4)
ON CONFLICT (component) DO UPDATE
SET version = EXCLUDED.version,
    applied_at = CURRENT_TIMESTAMP;

COMMIT;
