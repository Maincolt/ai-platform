# ADR-0038: Structured Market History — Extending `crypto-market-agent`/`forex-market-agent`

- **Status:** Accepted
- **Date:** 2026-08-20
- **Supersedes:** None
- **Superseded by:** None

## Context

[ADR-0037](ADR-0037-coinbase-trader-agent.md) (Proposed, `coinbase-trader-agent`)
and its forex counterpart ([ADR-0039](ADR-0039-fxcm-trader-agent.md),
also Proposed) need real price/finding history to reason over, not a
single live fetch each cycle — the repository owner's explicit
instruction: the trader roles should **use** `crypto-market-agent`/
`forex-market-agent`'s own observations, not independently re-fetch
Binance/Frankfurter themselves. Today, those two roles' only durable
output is one `agent.autonomous_actions` row per finding — a generic,
role-agnostic audit-log shape (`target`/`result_detail` as free text,
`inputs` as opaque JSONB) never designed to be queried as a time series
("show me BTCUSDT's price trend over the last 6 cycles").

This ADR is deliberately scoped to the safe half of the repository
owner's request: **new structured tables, written by the two
already-accepted, zero-financial-risk observer roles.** It carries none
of ADR-0037/ADR-0039's stakes — no new credential, no new autonomous
action, no money at risk — so unlike those two, this ADR is Accepted
and implemented in the same pass it's proposed, matching ADR-0035/
ADR-0036's own precedent for genuinely low-risk work.

The repository owner's explicit choice: add these tables **alongside**
the existing `agent.autonomous_actions` audit-log rows, not replacing
them — the audit log stays the single source of truth for "what did
every autonomous role do" (ADR-0026 Decision 7's own framing), and
these new tables are purely an additional, purpose-built, queryable
projection of the same underlying findings.

## Decision

### 1. Two new tables, written by `crypto-market-agent`/`forex-market-agent` in addition to their existing audit-log row

- **`agent.market_price_observations`** — one row per watchlist
  symbol/pair per cycle: `role`, `symbol` (e.g. `BTCUSDT` or
  `EUR/USD`), `price`, `change_24h_percent` (nullable, same as the
  in-memory `SymbolPrice`/`CurrencyRate` shapes already have),
  `observed_at`. Raw price-tick history — no AI interpretation, exactly
  what was fetched, useful for trend/momentum computation a trader role
  might want beyond just the AI's own finding text.
- **`agent.market_findings`** — one row per AI-generated finding per
  cycle: `role`, `symbol`, `summary`, `severity`, `observed_at`. The
  same content already going into `agent.autonomous_actions.target`/
  `result_detail`, now first-class and queryable without scraping text
  columns from a generic, role-agnostic table.

Both tables are additive, append-only, never updated or deleted — same
posture as `agent.autonomous_actions`. Migration 0010, `agent` schema
version 5→6.

### 2. `crypto-market-agent`/`forex-market-agent`'s `run_cycle` writes three rows per finding now, not one

Per watchlist entry: one `agent.market_price_observations` row (every
fetched symbol, whether or not the AI flagged a finding for it — this
is the raw price history, independent of what the AI chose to
comment on). Per finding: one `agent.market_findings` row and the
existing one `agent.autonomous_actions` row (unchanged). A new
`MarketHistoryPort` (or role-specific equivalent — kept as two
independent implementations per each role's existing "no shared
package" instruction from ADR-0035/ADR-0036 Decision 3/4, applied
consistently here) is the seam both roles write through.

### 3. A read side for the trader roles: recent history by role, bounded window

`list_recent_prices(role, symbol, since)` and `list_recent_findings(role,
since)` — the query shape ADR-0037/ADR-0039's traders need ("what has
this symbol done in the last N hours," "what has the observer said
recently"), not exposed anywhere the existing dashboard needs it (this
is a trader-role-facing read, not a new dashboard feature).

## Security

No new credential, no new external call, no new action — this is
pure additional persistence for data these two roles already fetch and
already had permission to store (they already write `agent.
autonomous_actions` rows with the same content). No `SECURITY.md`
implication: neither role gains any new capability, only a
better-shaped record of what it already does.

## Alternatives Considered

### Replacing `agent.autonomous_actions` entirely with the new structured tables

Rejected — the repository owner's explicit choice (Context): the audit
log's role as "one row per attempted action across every autonomous
role, in one place" (ADR-0026 Decision 7) is a platform-wide invariant
that would break if two roles stopped writing to it. The new tables are
additive.

### One combined table instead of two (prices + findings together)

Considered: every fetched symbol doesn't get a finding (the AI is
explicitly instructed to only flag genuinely notable movement), so a
combined table would need nullable finding columns on most rows.
Rejected as the less honest shape — two tables with a clear one-to-many
relationship (many price observations, a subset of which produced a
finding) is more accurate than one table papering over that with NULLs.

## Consequences

### Positive

- Gives ADR-0037/ADR-0039's trader roles real history to reason over
  without either of them needing their own Binance/Frankfurter
  credential or fetch logic — they read this platform's own database
  instead, exactly the "use the existing agents" instruction.
- Zero new risk surface — additive persistence on two already-accepted,
  already-running, zero-financial-risk roles.

### Negative

- `crypto-market-agent`/`forex-market-agent` now write up to
  `watchlist_size + 2 × findings_count` rows per cycle instead of just
  `findings_count` — more writes, still trivially small volume at an
  hourly cadence over a 3-5-symbol watchlist.
- A second migration touching the `agent` schema in quick succession
  (0009 then 0010) — unavoidable given the trader roles' need arrived
  after the observer roles were already shipped.

## Related Decisions

- [ADR-0035: `crypto-market-agent`](ADR-0035-crypto-market-agent.md) / [ADR-0036: `forex-market-agent`](ADR-0036-forex-market-agent.md) — the roles extended here; their own action/finding-parsing/dispatch logic is unchanged, only `run_cycle`'s persistence step grows
- [ADR-0037: `coinbase-trader-agent`](ADR-0037-coinbase-trader-agent.md) / [ADR-0039: `fxcm-trader-agent`](ADR-0039-fxcm-trader-agent.md) — the consumers this history is built for
- [ADR-0026: Autonomous Team Agents](ADR-0026-autonomous-team-agents.md) Decision 7 — the audit-log invariant this ADR is additive to, never replaces

## References

- `src/ai_platform/agents/crypto_market_agent/agent.py` / `src/ai_platform/agents/forex_market_agent/agent.py` — `run_cycle`, extended
- `infrastructure/migrations/0009_agent_autonomous_actions.sql` — the table shape/migration-discipline precedent this ADR's migration 0010 follows

## Implementation Status

A pre-merge review found two real gaps, both fixed before merge: (1)
three integration-test files (`tests/integration/test_autonomous_state.py`,
`test_concurrency.py`, `conftest.py`) still hardcoded the pre-migration
`agent` schema version (5), which would fail every test in those files
at pool-open time against a real, migrated database — bumped to 6; (2)
the new `MarketHistoryPort` writes in both roles' `run_cycle` were
unguarded, so a transient DB failure on this ADR's own "purely
additive/non-critical" table would propagate uncaught and permanently
end `PeriodicService`'s loop (it has no retry of its own) — including
the audit-critical `record_action` path this ADR never intended to
put at risk. Both roles now wrap the new writes in a best-effort
try/except that logs and continues; `AutonomousStatePort.record_action`
is deliberately left with its existing fail-hard behavior unchanged
(same as every other autonomous role, not something this ADR should
alter platform-wide).

Accepted and implemented: migration 0010 (`agent.market_price_observations`/
`agent.market_findings`, `agent` schema version 5→6), `MarketHistoryPort`
(`src/ai_platform/ports/persistence/market_history.py`),
`PsycopgMarketHistoryPort` (`src/ai_platform/adapters/persistence/market_history.py`),
and both `crypto_market_agent`/`forex_market_agent`'s `run_cycle`
extended to write through it (independently, no shared logic beyond
the port itself) alongside their existing `agent.autonomous_actions`
row. New component tests cover the kill-switch/spend-cap skip paths,
successful-cycle persistence (every fetched price recorded, each
finding recorded to both the new table and the existing audit log),
and the off-watchlist rejection path, for both roles independently.
Ruff, BasedPyright (strict), and the full unit+component suite (962
tests) all pass. Not yet deployed/live-verified against the Mac Docker
host — deploying this migration requires the same care as any prior
one (apply against the real database before restarting the two
already-running agent containers).

ADR-0037/ADR-0039 (the traders that will read this history) remain
Proposed, unimplemented, pending the repository owner's separate
acceptance.
