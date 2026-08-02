-- Vertical Slice 01: Orchestrator-owned PostgreSQL schema.
-- Apply with the Orchestrator migration identity, never the runtime identity.
-- psql exits on the first error; the open transaction then rolls back in full.

\set ON_ERROR_STOP on

BEGIN;

CREATE SCHEMA IF NOT EXISTS orchestrator;

CREATE TABLE IF NOT EXISTS orchestrator.schema_version (
    component       TEXT        PRIMARY KEY,
    version         INTEGER     NOT NULL CHECK (version > 0),
    applied_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS orchestrator.accepted_requests (
    environment                    TEXT        NOT NULL,
    operation                      TEXT        NOT NULL,
    idempotency_scope_id           TEXT        NOT NULL,
    request_id                     TEXT        NOT NULL,
    workflow_id                    TEXT        NOT NULL UNIQUE,
    acceptance_actor_id            TEXT        NOT NULL,
    accepted_owner_subject_id      TEXT        NOT NULL,
    current_owner_subject_id       TEXT        NOT NULL,
    fingerprint                    TEXT        NOT NULL,
    fingerprint_policy_version     TEXT        NOT NULL,
    policy_identity                TEXT        NOT NULL,
    policy_revision                TEXT        NOT NULL,
    policy_decision                TEXT        NOT NULL,
    scope_mapping_revision         TEXT        NOT NULL,
    authorization_evidence         TEXT        NOT NULL,
    accepted_at                    TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (environment, operation, idempotency_scope_id, request_id),
    UNIQUE (environment, operation, idempotency_scope_id, request_id, workflow_id)
);

CREATE TABLE IF NOT EXISTS orchestrator.request_access_audit (
    id                          BIGSERIAL   PRIMARY KEY,
    environment                 TEXT        NOT NULL,
    operation                   TEXT        NOT NULL,
    idempotency_scope_id        TEXT        NOT NULL,
    request_id                  TEXT        NOT NULL,
    workflow_id                 TEXT        NOT NULL,
    current_actor_id            TEXT        NOT NULL,
    resolved_owner_subject_id   TEXT        NOT NULL,
    effective_correlation_id    TEXT        NOT NULL,
    policy_identity             TEXT        NOT NULL,
    policy_revision             TEXT        NOT NULL,
    policy_decision             TEXT        NOT NULL,
    scope_mapping_revision      TEXT        NOT NULL,
    authorization_evidence      TEXT        NOT NULL,
    disposition                 TEXT        NOT NULL,
    occurred_at                 TIMESTAMPTZ NOT NULL,
    FOREIGN KEY (
        environment, operation, idempotency_scope_id, request_id, workflow_id
    ) REFERENCES orchestrator.accepted_requests (
        environment, operation, idempotency_scope_id, request_id, workflow_id
    ),
    CONSTRAINT request_access_audit_disposition_check CHECK (disposition IN (
        'EQUIVALENT_REPLAY_AUTHORIZED',
        'FINGERPRINT_CONFLICT_AUTHORIZED',
        'OWNER_INTENT_MISMATCH'
    ))
);

CREATE INDEX IF NOT EXISTS request_access_audit_workflow_idx
    ON orchestrator.request_access_audit (workflow_id, occurred_at, id);

CREATE TABLE IF NOT EXISTS orchestrator.workflows (
    workflow_id       TEXT        PRIMARY KEY,
    request_id        TEXT        NOT NULL,
    correlation_id    TEXT        NOT NULL,
    state             TEXT        NOT NULL,
    revision          INTEGER     NOT NULL CHECK (revision > 0),
    result_word_count INTEGER,
    failure_code      TEXT,
    failure_detail    TEXT,
    created_at        TIMESTAMPTZ NOT NULL,
    updated_at        TIMESTAMPTZ NOT NULL,
    CONSTRAINT workflows_state_check
        CHECK (state IN ('RECEIVED', 'PENDING', 'DISPATCHED', 'COMPLETED', 'FAILED')),
    CONSTRAINT workflows_terminal_payload_check CHECK (
        (state = 'COMPLETED' AND result_word_count IS NOT NULL AND failure_code IS NULL)
        OR (state = 'FAILED' AND result_word_count IS NULL AND failure_code IS NOT NULL)
        OR (state NOT IN ('COMPLETED', 'FAILED')
            AND result_word_count IS NULL AND failure_code IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS orchestrator.tasks (
    task_id           TEXT        PRIMARY KEY,
    workflow_id       TEXT        NOT NULL UNIQUE REFERENCES orchestrator.workflows (workflow_id),
    state             TEXT        NOT NULL,
    result_word_count INTEGER,
    failure_code      TEXT,
    failure_detail    TEXT,
    created_at        TIMESTAMPTZ NOT NULL,
    updated_at        TIMESTAMPTZ NOT NULL,
    CONSTRAINT tasks_state_check
        CHECK (state IN ('DISPATCHED', 'COMPLETED', 'FAILED'))
);

CREATE TABLE IF NOT EXISTS orchestrator.task_attempts (
    task_attempt_id                 TEXT        PRIMARY KEY,
    task_id                         TEXT        NOT NULL REFERENCES orchestrator.tasks (task_id),
    attempt_number                  INTEGER     NOT NULL CHECK (attempt_number = 1),
    state                           TEXT        NOT NULL,
    agent_id                        TEXT        NOT NULL,
    capability_name                 TEXT        NOT NULL,
    capability_version              TEXT        NOT NULL,
    implementation_identity         TEXT        NOT NULL,
    implementation_version          TEXT        NOT NULL,
    command_contract_version        TEXT        NOT NULL,
    event_contract_versions         JSONB       NOT NULL,
    registry_revision               TEXT        NOT NULL,
    deployment_declaration_digest   TEXT        NOT NULL,
    selection_policy_version        TEXT        NOT NULL,
    availability_classification     TEXT        NOT NULL,
    observed_at                     TIMESTAMPTZ NOT NULL,
    selected_at                     TIMESTAMPTZ NOT NULL,
    task_result_deadline            TIMESTAMPTZ NOT NULL,
    result_word_count               INTEGER,
    failure_code                    TEXT,
    failure_detail                  TEXT,
    completed_at                    TIMESTAMPTZ,
    CONSTRAINT task_attempts_one_per_task UNIQUE (task_id, attempt_number),
    CONSTRAINT task_attempts_state_check
        CHECK (state IN ('DISPATCHED', 'COMPLETED', 'FAILED'))
);

CREATE INDEX IF NOT EXISTS task_attempts_deadline_idx
    ON orchestrator.task_attempts (task_result_deadline, task_attempt_id)
    WHERE state = 'DISPATCHED';

CREATE TABLE IF NOT EXISTS orchestrator.workflow_history (
    workflow_id          TEXT        NOT NULL REFERENCES orchestrator.workflows (workflow_id),
    revision             INTEGER     NOT NULL,
    from_state           TEXT,
    to_state             TEXT        NOT NULL,
    occurred_at          TIMESTAMPTZ NOT NULL,
    cause                TEXT        NOT NULL,
    request_id           TEXT        NOT NULL,
    correlation_id       TEXT        NOT NULL,
    task_id              TEXT,
    task_attempt_id      TEXT,
    causing_message_id   TEXT,
    actor_id             TEXT        NOT NULL,
    failure_code         TEXT,
    PRIMARY KEY (workflow_id, revision)
);

CREATE TABLE IF NOT EXISTS orchestrator.outbox (
    message_id                    TEXT        PRIMARY KEY,
    workflow_id                   TEXT        NOT NULL REFERENCES orchestrator.workflows (workflow_id),
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
    CONSTRAINT outbox_publication_state_check CHECK (publication_state IN (
        'NOT_ATTEMPTED', 'CLAIMED', 'ACKNOWLEDGED',
        'DEFINITIVELY_NOT_ACCEPTED', 'ATTEMPTED_UNKNOWN', 'FAILED'
    ))
);

CREATE INDEX IF NOT EXISTS outbox_recovery_idx
    ON orchestrator.outbox (logical_channel, workflow_id, creation_sequence, created_at)
    WHERE publication_state <> 'ACKNOWLEDGED';

CREATE TABLE IF NOT EXISTS orchestrator.inbox (
    environment                 TEXT        NOT NULL,
    logical_consumer_id         TEXT        NOT NULL,
    validated_message_id        TEXT        NOT NULL,
    immutable_message_digest    TEXT        NOT NULL,
    workflow_id                 TEXT        NOT NULL,
    task_attempt_id             TEXT        NOT NULL,
    disposition                 TEXT        NOT NULL,
    recorded_at                 TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (environment, logical_consumer_id, validated_message_id)
);

CREATE TABLE IF NOT EXISTS orchestrator.transport_rejections (
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
    CONSTRAINT transport_rejections_state_check
        CHECK (quarantine_state IN ('NOT_ATTEMPTED', 'ATTEMPTED_UNKNOWN', 'CONFIRMED')),
    CONSTRAINT transport_rejections_offset_guard
        CHECK (NOT source_offset_completed OR quarantine_state = 'CONFIRMED')
);

CREATE TABLE IF NOT EXISTS orchestrator.audit (
    id           BIGSERIAL   PRIMARY KEY,
    kind         TEXT        NOT NULL,
    workflow_id  TEXT        NOT NULL,
    occurred_at  TIMESTAMPTZ NOT NULL,
    actor_id     TEXT        NOT NULL,
    details      JSONB       NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS orchestrator_audit_workflow_idx
    ON orchestrator.audit (workflow_id, occurred_at, id);

-- Publish compatibility only after every schema object exists in this transaction.
INSERT INTO orchestrator.schema_version (component, version)
VALUES ('orchestrator', 1)
ON CONFLICT (component) DO UPDATE
SET version = EXCLUDED.version,
    applied_at = CURRENT_TIMESTAMP;

REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
    ON orchestrator.schema_version FROM ai_platform_orchestrator_runtime;
GRANT SELECT ON orchestrator.schema_version TO ai_platform_orchestrator_runtime;

COMMIT;
