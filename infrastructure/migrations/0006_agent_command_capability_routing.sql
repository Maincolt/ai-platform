-- Vertical Slice 01 extension: add the same capability_name column to
-- agent.event_outbox for structural symmetry with orchestrator.outbox --
-- shared outbox persistence code (src/ai_platform/adapters/persistence/
-- _outbox_common.py) handles both tables uniformly. Always NULL here:
-- task-outcomes is never capability-scoped (ADR-0014 Section 6). Apply
-- with the Agent migration identity, never the runtime identity. psql
-- exits on the first error; the open transaction then rolls back in full.

\set ON_ERROR_STOP on

BEGIN;

ALTER TABLE agent.event_outbox
    ADD COLUMN capability_name TEXT;

-- Publish compatibility only after every schema object exists in this transaction.
INSERT INTO agent.schema_version (component, version)
VALUES ('agent', 3)
ON CONFLICT (component) DO UPDATE
SET version = EXCLUDED.version,
    applied_at = CURRENT_TIMESTAMP;

COMMIT;
