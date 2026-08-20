# ADR-0039: `fxcm-trader-agent` — Real, Autonomous Forex Trade Execution

- **Status:** Proposed
- **Date:** 2026-08-20
- **Supersedes:** None
- **Superseded by:** None

## Context

[ADR-0037](ADR-0037-coinbase-trader-agent.md) covers real, autonomous
crypto trade execution against Coinbase. Coinbase does not support
traditional forex products (EUR/USD spot forex, etc.) — it is a crypto
exchange. The repository owner confirmed forex trading is wanted too,
via a separate broker: **FXCM**. This is that role, structurally the
forex counterpart of ADR-0037, deliberately kept as an independent
role/ADR/implementation rather than folded into `coinbase-trader-agent`
— same reasoning `crypto-market-agent`/`forex-market-agent` already
established (ADR-0036 Decision 3): different broker, different
credential, different order-placement API shape, and per-role least
privilege/audit clarity is only unambiguous if each domain is its own
Agent deployment (ADR-0033's Alternatives Considered made this same
call for the two PR-review specialists).

Every one of ADR-0037's stakes applies here unchanged: real,
irreversible financial loss is the direct consequence of a successful
prompt injection or model misjudgment. Nothing about this ADR should be
read as a lower-scrutiny rubber stamp of ADR-0037's already-established
reasoning — it is repeated in full below because a forex order and a
crypto order are different enough operations that "just reuse
ADR-0037's Security section" would be a leaky shortcut.

Confirmed parameters from the repository owner:

- **Broker: FXCM.**
- **Per-trade cap: $100**, **daily caps: 3 trades / $200 per UTC
  day** — identical numbers to `coinbase-trader-agent` (repository
  owner's explicit choice, "keep both roles' worst-case exposure
  identical and easy to reason about together"), tracked as fully
  independent budget rows (`role='fxcm-trader'`), not shared with
  `coinbase-trader-agent`'s `role='coinbase-trader'` rows — a bad day
  for one role's cap does not consume the other's.
- **Data source: `forex-market-agent`'s structured history**
  ([ADR-0038](ADR-0038-structured-market-history.md)), not an
  independent live rate fetch — same "use the existing agents, build on
  real history" instruction ADR-0037 was revised for. `crypto-market-
  agent`'s findings feed in as macro context only, symmetric with how
  ADR-0037 uses `forex-market-agent`'s findings as context — this role
  never places a crypto order (FXCM does not support crypto spot
  trading in the shape this platform would need, and `coinbase-trader-
  agent` already owns that domain).
- **No instrument allowlist**, same repository-owner choice and same
  practical narrowing as ADR-0037 Decision 3's revision: a proposed
  trade's currency pair must match one `forex-market-agent` has a
  recent observation for, which is itself `forex-market-agent`'s
  configured watchlist (`EUR/USD`, `EUR/GBP`, `EUR/JPY` as currently
  configured, base currency EUR).

## Decision

### 1. New credential: a dedicated, trading-only FXCM API key

A separate FXCM API key/account, used by no other role. Same
withdrawal-permission boundary as ADR-0037 Decision 1: FXCM account
transfers/withdrawals must never be enabled on this key (a requirement
on how the repository owner scopes it), and `FxcmTradingPort` has no
withdrawal/transfer method in code regardless. Starts as an
obviously-fake placeholder at deployment time; see Decision 6 for the
additional gate beyond that.

### 2. Action set: one verb, `place_market_order`, bounded by three independent caps

Same shape as ADR-0037 Decision 2: per-trade cap ($100 notional,
rejected outright if exceeded, never clamped), daily trade-count cap
(3/UTC day) and daily notional cap ($200/UTC day), tracked
independently of both the AI-cost budget and `coinbase-trader-agent`'s
own trade budget. Market orders only for this first build, same
narrower-MVP-first reasoning as ADR-0037 Decision 2 — FXCM's API also
supports limit/stop orders, deferred identically.

One forex-specific difference from a crypto order: **position
direction is explicit** (`buy`/`sell` a currency pair, i.e. going long
or short the base currency against the quote currency) — economically
equivalent to Coinbase's `side`, same two-value enum, no new concept.

### 3. `FxcmTradingPort` (write side, real FXCM calls) + `MarketHistoryPort` (read side, ADR-0038's tables)

Same split as ADR-0037 Decision 3 (already revised there to read from
ADR-0038 rather than a live fetch — this role adopts that shape from
the start, never had an un-revised version). Read side: recent
`forex-market-agent` price/finding history (`role="forex-market"`,
bounded lookback window) plus recent `crypto-market-agent` findings as
macro context only (`role="crypto-market"`) — never a trade target.
Write side: exactly one method, `place_market_order(instrument, side,
notional_usd)` — no cancel, no limit order, no withdrawal, no
account-settings method exists on this Protocol at all. A real
FXCM account-balance read and a real order-placement write; every
write failure is a real order-placement failure, never best-effort.
Same freshness-window/watchlist-membership check as ADR-0037: no fresh
`forex-market-agent` observation for a pair means that pair is
unavailable as a trade target this cycle, not silently traded on stale
data.

### 4. A separate real-money budget table, shared shape with `coinbase-trader-agent`'s, not shared rows

Reuses ADR-0037 Decision 4's `agent.autonomous_trade_budget (role, day,
trades_used, notional_cents_used)` table (no new migration beyond
ADR-0037's own) — `role='fxcm-trader'` rows, independent of
`role='coinbase-trader'`. Same reasoning as ADR-0037: real trading
dollars must never be conflated with the existing AI-cost
`spend_cents_used` column every role already has.

### 5. One AI Router call per cycle over real history, same strict-parse discipline

Fetch FXCM account balance + recent forex price/finding history
(ADR-0038) + recent crypto findings as context → one AI Router call
proposing a bounded batch of orders → strict JSON-shape parse, reject
the whole batch on any mismatch → validate each proposal against the
per-trade cap, remaining daily budget, and the freshness/watchlist-
membership check → dispatch sequentially, recording every attempt to
`agent.autonomous_actions` (`role='fxcm-trader'`), same audit-log table
and dashboard visibility every prior role already has.

### 6. An additional, role-specific "trading enabled" gate — off by default

Same mechanism as ADR-0037 Decision 6, its own row:
`agent.autonomous_trading_enabled` (`role='fxcm-trader'`, `enabled
BOOLEAN NOT NULL DEFAULT FALSE`) — independent of
`role='coinbase-trader'`'s row, so enabling one trading role never
implicitly enables the other. No new migration beyond ADR-0037's own
(the table is role-keyed, not role-specific).

## Security

Identical risk class and posture to ADR-0037 (Security section applies
in full, repeated in substance rather than by reference given this
ADR's own Context framing): real, irreversible financial loss is the
direct consequence of a successful prompt injection or misjudgment,
bounded but not prevented by the per-trade/daily caps; no instrument
allowlist as a hardcoded list, narrowed in practice to
`forex-market-agent`'s watchlist by Decision 3's data-source choice;
withdrawal permission enforced both by how the FXCM key is scoped and
by `FxcmTradingPort` having no code path that could use it; the
role-specific trading-enabled gate (Decision 6) is this role's own
independent human-flipped switch, not inherited from
`coinbase-trader-agent`'s.

One forex-specific consideration ADR-0037 didn't need: **leveraged
forex trading exists and is common at retail forex brokers, including
FXCM** — if the FXCM account this role trades against has leverage
enabled, a "$100 notional" order could control a much larger effective
position, and the per-trade cap's real risk would be understated unless
leverage is disabled on the account or the cap is computed against
effective (leveraged) exposure, not just the ordered notional. This
ADR does not resolve that ambiguity — it is called out explicitly as an
open question the repository owner must settle (disable leverage on
this account, or tell this role's implementation to size against
leveraged exposure) before this role is accepted, not something to
infer silently either way.

## Alternatives Considered

### Folding this into `coinbase-trader-agent` as a second broker

Rejected — see Context. Different broker, different API, different
credential; keeping them separate roles matches this codebase's
established per-domain-independent-role precedent and keeps each
role's audit trail/budget/kill-switch-gate unambiguous.

### Limit orders instead of market orders

Rejected for this first build, same reasoning as ADR-0037 Decision 2.

## Consequences

### Positive

- Delivers real, bounded autonomous forex trade execution, matching
  `coinbase-trader-agent`'s safety posture exactly (same cap numbers,
  same independent gates, same history-based data source) rather than
  a lesser-scrutinized forex afterthought.
- Reuses ADR-0037/ADR-0038's schema/migration work — no new migration.

### Negative

- An eighth and ninth autonomous role between this ADR and ADR-0037 —
  two more real-money-risk deployments to operate.
- The leverage question (Security) is unresolved by this ADR and must
  be settled before acceptance, not after.
- No instrument allowlist as a hardcoded list, same knowingly-accepted
  residual risk as ADR-0037, narrowed but not eliminated by Decision 3.

## Related Decisions

- [ADR-0037: `coinbase-trader-agent`](ADR-0037-coinbase-trader-agent.md) — the crypto counterpart this role mirrors in every safety mechanism; a separate role/broker/credential, not a shared implementation
- [ADR-0038: Structured Market History](ADR-0038-structured-market-history.md) — the data source this role reads from
- [ADR-0036: `forex-market-agent`](ADR-0036-forex-market-agent.md) — the observer role this trader consumes, and the watchlist that practically bounds its tradable instruments
- [ADR-0026: Autonomous Team Agents](ADR-0026-autonomous-team-agents.md) — the `PeriodicService`/kill-switch/per-role-budget/audit-log pattern this role extends

## References

- `src/ai_platform/agents/forex_market_agent/` — ADR-0038's `MarketHistoryPort` read side, the actual data source
- ADR-0037's own References — the propose-then-dispatch cycle shape and port patterns this role mirrors independently

## Implementation Status

**Proposed — not accepted, no code written.** Same stakes-driven pause
as ADR-0037: left for the repository owner's explicit review and
acceptance, including resolving the leverage question in Security,
before any implementation begins. `SECURITY.md` needs its own new
carve-out paragraph naming this ADR and role explicitly, independent of
whatever paragraph ADR-0037 eventually adds.
