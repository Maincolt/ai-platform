-- Vertical Slice 01 extension: add explicit capability routing metadata to
-- the Orchestrator outbox so the publisher can resolve the capability-scoped
-- physical task-commands topic without parsing the immutable payload bytes
-- (ADR-0014 Section 6). Apply with the Orchestrator migration identity,
-- never the runtime identity. psql exits on the first error; the open
-- transaction then rolls back in full.

\set ON_ERROR_STOP on

BEGIN;

ALTER TABLE orchestrator.outbox
    ADD COLUMN capability_name TEXT;

-- Publish compatibility only after every schema object exists in this transaction.
INSERT INTO orchestrator.schema_version (component, version)
VALUES ('orchestrator', 3)
ON CONFLICT (component) DO UPDATE
SET version = EXCLUDED.version,
    applied_at = CURRENT_TIMESTAMP;

COMMIT;
