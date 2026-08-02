-- Vertical Slice 01: Test Agent-owned PostgreSQL schema.
-- Apply with the Agent migration identity, never the runtime identity.
-- psql exits on the first error; the open transaction then rolls back in full.

\set ON_ERROR_STOP on

BEGIN;

CREATE SCHEMA IF NOT EXISTS agent;

CREATE TABLE IF NOT EXISTS agent.schema_version (
    component       TEXT        PRIMARY KEY,
    version         INTEGER     NOT NULL CHECK (version > 0),
    applied_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent.terminal_events (
    message_id          TEXT        PRIMARY KEY,
    task_attempt_id     TEXT        NOT NULL UNIQUE,
    workflow_id         TEXT        NOT NULL,
    logical_channel     TEXT        NOT NULL,
    ordering_key        TEXT        NOT NULL,
    payload_bytes       BYTEA       NOT NULL CHECK (octet_length(payload_bytes) > 0),
    headers             JSONB       NOT NULL,
    creation_sequence   BIGINT      NOT NULL CHECK (creation_sequence > 0),
    created_at          TIMESTAMPTZ NOT NULL,
    UNIQUE (logical_channel, workflow_id, creation_sequence)
);

CREATE TABLE IF NOT EXISTS agent.completed_receipts (
    environment               TEXT        NOT NULL,
    agent_deployment_id       TEXT        NOT NULL,
    task_attempt_id           TEXT        PRIMARY KEY,
    command_message_id        TEXT        NOT NULL,
    command_digest            TEXT        NOT NULL,
    terminal_event_message_id TEXT        NOT NULL UNIQUE REFERENCES agent.terminal_events (message_id),
    completed_at              TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS agent.outcomes (
    task_attempt_id TEXT        PRIMARY KEY REFERENCES agent.completed_receipts (task_attempt_id),
    completed_at    TIMESTAMPTZ NOT NULL,
    word_count      INTEGER,
    failure_code    TEXT,
    summary         TEXT,
    CONSTRAINT outcomes_result_xor_failure_check
        CHECK ((word_count IS NULL) <> (failure_code IS NULL))
);

CREATE TABLE IF NOT EXISTS agent.event_outbox (
    message_id                    TEXT        PRIMARY KEY REFERENCES agent.terminal_events (message_id),
    task_attempt_id               TEXT        NOT NULL UNIQUE REFERENCES agent.completed_receipts (task_attempt_id),
    workflow_id                   TEXT        NOT NULL,
    logical_channel               TEXT        NOT NULL,
    ordering_key                  TEXT        NOT NULL,
    payload_bytes                 BYTEA       NOT NULL CHECK (octet_length(payload_bytes) > 0),
    headers                       JSONB       NOT NULL,
    creation_sequence             BIGINT      NOT NULL CHECK (creation_sequence > 0),
    publication_state             TEXT        NOT NULL DEFAULT 'NOT_ATTEMPTED',
    claim_previous_state          TEXT,
    publisher_instance_id         TEXT,
    claim_token                   TEXT,
    claim_expires_at              TIMESTAMPTZ,
    publication_attempts          INTEGER     NOT NULL DEFAULT 0 CHECK (publication_attempts >= 0),
    automatic_retry_allowed       BOOLEAN     NOT NULL DEFAULT TRUE,
    last_attempted_at             TIMESTAMPTZ,
    safe_failure_code             TEXT,
    created_at                    TIMESTAMPTZ NOT NULL,
    UNIQUE (logical_channel, workflow_id, creation_sequence),
    CONSTRAINT event_outbox_publication_state_check CHECK (publication_state IN (
        'NOT_ATTEMPTED', 'CLAIMED', 'ACKNOWLEDGED',
        'DEFINITIVELY_NOT_ACCEPTED', 'ATTEMPTED_UNKNOWN', 'FAILED'
    ))
);

CREATE INDEX IF NOT EXISTS agent_event_outbox_recovery_idx
    ON agent.event_outbox (logical_channel, workflow_id, creation_sequence, created_at)
    WHERE publication_state <> 'ACKNOWLEDGED';

CREATE TABLE IF NOT EXISTS agent.transport_rejections (
    logical_subscription       TEXT        NOT NULL,
    physical_source            TEXT        NOT NULL,
    partition_number           INTEGER     NOT NULL,
    source_offset              BIGINT      NOT NULL,
    rejection_id               TEXT        NOT NULL UNIQUE,
    safe_failure_code          TEXT        NOT NULL,
    original_bytes_sha256      TEXT        NOT NULL,
    quarantine_state           TEXT        NOT NULL DEFAULT 'NOT_ATTEMPTED',
    source_offset_completed    BOOLEAN     NOT NULL DEFAULT FALSE,
    recorded_at                TIMESTAMPTZ NOT NULL,
    quarantine_updated_at      TIMESTAMPTZ,
    source_offset_completed_at TIMESTAMPTZ,
    PRIMARY KEY (logical_subscription, physical_source, partition_number, source_offset),
    CONSTRAINT agent_transport_rejections_state_check
        CHECK (quarantine_state IN ('NOT_ATTEMPTED', 'ATTEMPTED_UNKNOWN', 'CONFIRMED')),
    CONSTRAINT agent_transport_rejections_offset_guard
        CHECK (NOT source_offset_completed OR quarantine_state = 'CONFIRMED')
);

CREATE TABLE IF NOT EXISTS agent.audit (
    id           BIGSERIAL   PRIMARY KEY,
    kind         TEXT        NOT NULL,
    workflow_id  TEXT        NOT NULL,
    occurred_at  TIMESTAMPTZ NOT NULL,
    actor_id     TEXT        NOT NULL,
    details      JSONB       NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS agent_audit_workflow_idx
    ON agent.audit (workflow_id, occurred_at, id);

-- Publish compatibility only after every schema object exists in this transaction.
INSERT INTO agent.schema_version (component, version)
VALUES ('agent', 1)
ON CONFLICT (component) DO UPDATE
SET version = EXCLUDED.version,
    applied_at = CURRENT_TIMESTAMP;

REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
    ON agent.schema_version FROM ai_platform_agent_runtime;
GRANT SELECT ON agent.schema_version TO ai_platform_agent_runtime;

COMMIT;
