-- Vertical Slice 01 extension: generalize the Agent's outcome column from a
-- word-count-specific integer to a capability-scoped JSON payload
-- (ADR-0015). Apply with the Agent migration identity, never the runtime
-- identity. psql exits on the first error; the open transaction then rolls
-- back in full.

\set ON_ERROR_STOP on

BEGIN;

ALTER TABLE agent.outcomes
    DROP CONSTRAINT outcomes_result_xor_failure_check;

ALTER TABLE agent.outcomes
    RENAME COLUMN word_count TO result_data;
ALTER TABLE agent.outcomes
    ALTER COLUMN result_data TYPE JSONB USING
        CASE WHEN result_data IS NULL THEN NULL
             ELSE jsonb_build_object('word_count', result_data) END;

ALTER TABLE agent.outcomes
    ADD CONSTRAINT outcomes_result_xor_failure_check
        CHECK ((result_data IS NULL) <> (failure_code IS NULL));

-- Publish compatibility only after every schema object exists in this transaction.
INSERT INTO agent.schema_version (component, version)
VALUES ('agent', 2)
ON CONFLICT (component) DO UPDATE
SET version = EXCLUDED.version,
    applied_at = CURRENT_TIMESTAMP;

COMMIT;
