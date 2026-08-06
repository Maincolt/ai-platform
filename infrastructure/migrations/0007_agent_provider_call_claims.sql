-- ADR-0014 Section 5: durable pre-call claim and redacted usage tracking
-- for non-deterministic, provider-backed Agent execution steps (starting
-- with `text.summarize`). Apply with the Agent migration identity, never
-- the runtime identity. psql exits on the first error; the open
-- transaction then rolls back in full.

\set ON_ERROR_STOP on

BEGIN;

-- One row per task_attempt_id that has ever been claimed for a provider
-- call. Rows are never updated or deleted: presence alone means "a call
-- was claimed"; resolution is read from agent.outcomes via
-- agent.completed_receipts, never from this table. A claim found here
-- with no resolved outcome for the same task_attempt_id is the
-- ADR-0014 Section 5 "unknown outcome" case.
CREATE TABLE IF NOT EXISTS agent.provider_call_claims (
    task_attempt_id     TEXT        PRIMARY KEY,
    command_message_id  TEXT        NOT NULL,
    command_digest      TEXT        NOT NULL,
    claimed_at          TIMESTAMPTZ NOT NULL
);

-- Redacted usage evidence for one resolved provider call. Internal
-- evidence only -- never read by the public API (ADR-0010's existing
-- internal-evidence/public-disclosure separation), populated only when
-- the outcome commit that resolved a claimed task_attempt_id carried
-- usage metadata.
CREATE TABLE IF NOT EXISTS agent.provider_call_usage (
    task_attempt_id  TEXT             PRIMARY KEY REFERENCES agent.completed_receipts (task_attempt_id),
    provider         TEXT             NOT NULL,
    model            TEXT             NOT NULL,
    input_tokens     INTEGER          NOT NULL CHECK (input_tokens >= 0),
    output_tokens    INTEGER          NOT NULL CHECK (output_tokens >= 0),
    latency_seconds  DOUBLE PRECISION NOT NULL CHECK (latency_seconds >= 0),
    recorded_at      TIMESTAMPTZ      NOT NULL
);

-- Publish compatibility only after every schema object exists in this transaction.
INSERT INTO agent.schema_version (component, version)
VALUES ('agent', 4)
ON CONFLICT (component) DO UPDATE
SET version = EXCLUDED.version,
    applied_at = CURRENT_TIMESTAMP;

COMMIT;
