-- Vertical Slice 01 extension: generalize the Orchestrator's result columns
-- from a word-count-specific integer to a capability-scoped JSON payload
-- (ADR-0015). Apply with the Orchestrator migration identity, never the
-- runtime identity. psql exits on the first error; the open transaction
-- then rolls back in full.

\set ON_ERROR_STOP on

BEGIN;

ALTER TABLE orchestrator.workflows
    DROP CONSTRAINT workflows_terminal_payload_check;

ALTER TABLE orchestrator.workflows
    RENAME COLUMN result_word_count TO result_data;
ALTER TABLE orchestrator.workflows
    ALTER COLUMN result_data TYPE JSONB USING
        CASE WHEN result_data IS NULL THEN NULL
             ELSE jsonb_build_object('word_count', result_data) END;

ALTER TABLE orchestrator.workflows
    ADD CONSTRAINT workflows_terminal_payload_check CHECK (
        (state = 'COMPLETED' AND result_data IS NOT NULL AND failure_code IS NULL)
        OR (state = 'FAILED' AND result_data IS NULL AND failure_code IS NOT NULL)
        OR (state NOT IN ('COMPLETED', 'FAILED')
            AND result_data IS NULL AND failure_code IS NULL)
    );

ALTER TABLE orchestrator.tasks
    RENAME COLUMN result_word_count TO result_data;
ALTER TABLE orchestrator.tasks
    ALTER COLUMN result_data TYPE JSONB USING
        CASE WHEN result_data IS NULL THEN NULL
             ELSE jsonb_build_object('word_count', result_data) END;

ALTER TABLE orchestrator.task_attempts
    RENAME COLUMN result_word_count TO result_data;
ALTER TABLE orchestrator.task_attempts
    ALTER COLUMN result_data TYPE JSONB USING
        CASE WHEN result_data IS NULL THEN NULL
             ELSE jsonb_build_object('word_count', result_data) END;

-- Publish compatibility only after every schema object exists in this transaction.
INSERT INTO orchestrator.schema_version (component, version)
VALUES ('orchestrator', 2)
ON CONFLICT (component) DO UPDATE
SET version = EXCLUDED.version,
    applied_at = CURRENT_TIMESTAMP;

COMMIT;
