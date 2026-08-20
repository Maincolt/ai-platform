-- ADR-0038: structured, queryable price/finding history for
-- crypto-market-agent/forex-market-agent, additive to the existing
-- agent.autonomous_actions audit log (never replacing it -- ADR-0026
-- Decision 7's "one row per attempted action, in one place" invariant
-- stays intact). Apply with the Agent migration identity, never the
-- runtime identity. psql exits on the first error; the open
-- transaction then rolls back in full.

\set ON_ERROR_STOP on

BEGIN;

-- Raw price-tick history: one row per watchlist symbol/pair per
-- cycle, whether or not the AI flagged a finding for it -- independent
-- of AI interpretation, useful for trend/momentum context a trader
-- role builds a prompt from (ADR-0037/ADR-0039).
CREATE TABLE IF NOT EXISTS agent.market_price_observations (
    id                  BIGSERIAL    PRIMARY KEY,
    role                TEXT         NOT NULL,
    symbol              TEXT         NOT NULL,
    price               NUMERIC      NOT NULL,
    change_24h_percent  NUMERIC,
    observed_at         TIMESTAMPTZ  NOT NULL
);

CREATE INDEX IF NOT EXISTS market_price_observations_role_symbol_observed_at_idx
    ON agent.market_price_observations (role, symbol, observed_at, id);

-- AI-generated finding history: the same content already written to
-- agent.autonomous_actions.target/result_detail, now first-class and
-- queryable without scraping a generic, role-agnostic table's text
-- columns.
CREATE TABLE IF NOT EXISTS agent.market_findings (
    id            BIGSERIAL    PRIMARY KEY,
    role          TEXT         NOT NULL,
    symbol        TEXT         NOT NULL,
    summary       TEXT         NOT NULL,
    severity      TEXT         NOT NULL CHECK (severity IN ('low', 'medium', 'high')),
    observed_at   TIMESTAMPTZ  NOT NULL
);

CREATE INDEX IF NOT EXISTS market_findings_role_observed_at_idx
    ON agent.market_findings (role, observed_at, id);

-- Publish compatibility only after every schema object exists in this transaction.
INSERT INTO agent.schema_version (component, version)
VALUES ('agent', 6)
ON CONFLICT (component) DO UPDATE
SET version = EXCLUDED.version,
    applied_at = CURRENT_TIMESTAMP;

COMMIT;
