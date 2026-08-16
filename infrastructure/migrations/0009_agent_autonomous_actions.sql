-- ADR-0026/ADR-0028: durable state for autonomous, non-Workflow-driven
-- Agent write actions -- a kill switch, a per-role daily budget, and an
-- append-only audit log of every attempted action. Apply with the Agent
-- migration identity, never the runtime identity. psql exits on the
-- first error; the open transaction then rolls back in full.

\set ON_ERROR_STOP on

BEGIN;

-- Platform-wide kill switch (ADR-0026 Decision 7): a single row, checked
-- by every autonomous role's PeriodicService cycle before any GitHub
-- call. Toggled by direct SQL -- no redeploy needed to engage it. The
-- CHECK constraint enforces exactly one row (a singleton table).
CREATE TABLE IF NOT EXISTS agent.autonomous_kill_switch (
    singleton_id  BOOLEAN     PRIMARY KEY DEFAULT TRUE CHECK (singleton_id),
    engaged       BOOLEAN     NOT NULL DEFAULT FALSE,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO agent.autonomous_kill_switch (singleton_id, engaged, updated_at)
VALUES (TRUE, FALSE, CURRENT_TIMESTAMP)
ON CONFLICT (singleton_id) DO NOTHING;

-- Per-role, per-UTC-day hard cap (ADR-0028 Decision 2): one row per
-- (role, day). A role's cycle reserves budget here before doing any
-- write-capable work; once either counter reaches its configured
-- ceiling, the role skips write behavior until the next UTC day.
-- spend_cents_used is an estimate from a hardcoded per-model rate table
-- applied to real token counts, never exact provider billing.
CREATE TABLE IF NOT EXISTS agent.autonomous_role_budget (
    role              TEXT    NOT NULL,
    day               DATE    NOT NULL,
    actions_used      INTEGER NOT NULL DEFAULT 0 CHECK (actions_used >= 0),
    spend_cents_used  INTEGER NOT NULL DEFAULT 0 CHECK (spend_cents_used >= 0),
    PRIMARY KEY (role, day)
);

-- Append-only audit log of every attempted autonomous action (ADR-0026
-- Decision 7): after-the-fact, not preventive -- makes every action
-- reconstructable, never stoppable in advance. One row per dispatch
-- attempt, win or lose. Never updated or deleted.
CREATE TABLE IF NOT EXISTS agent.autonomous_actions (
    id               BIGSERIAL    PRIMARY KEY,
    agent_deployment_id TEXT      NOT NULL,
    role             TEXT         NOT NULL,
    action_type      TEXT         NOT NULL,
    target           TEXT         NOT NULL,
    inputs           JSONB        NOT NULL,
    result_status    TEXT         NOT NULL CHECK (result_status IN ('SUCCEEDED', 'FAILED')),
    result_detail    TEXT         NOT NULL,
    occurred_at      TIMESTAMPTZ  NOT NULL
);

CREATE INDEX IF NOT EXISTS autonomous_actions_role_occurred_at_idx
    ON agent.autonomous_actions (role, occurred_at, id);

-- Publish compatibility only after every schema object exists in this transaction.
INSERT INTO agent.schema_version (component, version)
VALUES ('agent', 5)
ON CONFLICT (component) DO UPDATE
SET version = EXCLUDED.version,
    applied_at = CURRENT_TIMESTAMP;

COMMIT;
