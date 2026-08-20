# ADR-0037: `coinbase-trader-agent` — Real, Autonomous Trade Execution

- **Status:** Proposed
- **Date:** 2026-08-20
- **Supersedes:** None
- **Superseded by:** None

## Context

The repository owner asked for a "market trader specialist." Confirmed
via direct questions: unlike `crypto-market-agent`/`forex-market-agent`
(ADR-0035/ADR-0036, which are structurally incapable of acting on
anything external), this role should **actually place real orders**
against a real Coinbase account, autonomously, with no per-trade human
approval — the highest-blast-radius, most irreversible capability this
platform would ever hold. `principal-developer-agent`'s merge rights
(ADR-0031) were this platform's previous ceiling; a merged commit can
still be reverted by a human. A filled market order cannot be undone by
this platform at all — only by placing another, opposite trade, at
whatever price the market has moved to by then.

ADR-0035's own Alternatives Considered section anticipated exactly this
request and declined to build it without "its own from-scratch ADR,
explicit repository-owner sign-off, and almost certainly a
`SECURITY.md` amendment given the stakes exceed even
`principal-developer-agent`'s merge rights." This is that ADR.

Confirmed parameters from the repository owner, gathered before any
design work (given the stakes, these are treated as load-bearing
decisions, not implementation details to fill in later):

- **Exchange: Coinbase** (Advanced Trade API), not Binance (the
  `crypto-market-agent` price-feed exchange) — a deliberately separate
  account/credential from any read-only price feed.
- **Per-trade cap: $100** notional value, hard-enforced in code.
- **Daily caps: 3 trades and $200 total notional per UTC day** —
  independent of, and in addition to, the per-trade cap (three $100
  trades would already hit the daily dollar cap; the count cap bounds
  trade *frequency* even if individual trades are smaller).
- **No instrument allowlist** — the repository owner's explicit choice,
  after being shown the alternative: any Coinbase-listed product is a
  legal target, including illiquid or unfamiliar ones. This is a real,
  knowingly-accepted residual risk (see Security), though Decision 3's
  revision below narrows it in practice — see that Decision.

**Revised after initial drafting, before any implementation**: the
repository owner clarified this role should not independently reason
from scratch each cycle — it should **use `crypto-market-agent`'s own
observations** ([ADR-0038](ADR-0038-structured-market-history.md)'s new
structured history tables) rather than calling Binance-adjacent/
Coinbase market-data endpoints itself, and a real "database backend"
(ADR-0038) rather than a single live snapshot. `forex-market-agent`'s
findings also feed this role, but only as macro context (e.g. "USD is
weakening") — Coinbase does not support traditional forex products, so
no forex order is ever placed through this role; forex order placement
is [ADR-0039](ADR-0039-fxcm-trader-agent.md)'s separate role, against a
separate broker. Decisions 3 and 5 below are revised accordingly;
Decisions 1, 2, 4, and 6 are unchanged.

## Decision

### 1. New credential: a dedicated, trading-only Coinbase API key

A separate Coinbase Advanced Trade API key, used by no other role.
**Withdrawal/transfer permission must never be granted to this key** —
this is a requirement on how the repository owner creates the key
(Coinbase's own permission scoping), not something this platform's code
can retroactively restrict. On the code side, the same "structural
incapability" pattern every prior role already established:
`CoinbaseTradingPort` (see Decision 3) has no withdrawal/transfer
method at all, so even a misconfigured key with that permission still
has no *code path* here that could use it. Starts as an
obviously-fake placeholder at deployment time, same placeholder-then-
real path every prior role's credential has followed — see Decision 6
for why this role adds an extra gate beyond that pattern.

### 2. Action set: one verb, `place_market_order`, bounded by three independent caps

- **Per-trade cap ($100)**: any proposed order whose notional value
  (quantity × current price, or the order's specified quote amount)
  exceeds $100 is rejected before dispatch — not clamped down to $100,
  rejected outright, so a wildly-oversized proposal is treated as a
  parse failure for that item, not silently resized.
- **Daily trade-count cap (3/UTC day)** and **daily notional cap
  ($200/UTC day)**: tracked independently of the AI-cost budget every
  other role already has (Decision 4) — checked before any order is
  dispatched, and again cumulatively as the cycle's batch is processed
  (mirroring `scrum-master-agent`'s "stop mid-batch once the cap is
  hit" behavior, ADR-0028 Decision 3).
- No instrument allowlist as a hardcoded/configured list (repository
  owner's explicit choice, Context) — but see Decision 3's revision:
  in practice, a proposed order's `product_id` must match a symbol
  `crypto-market-agent` has actually recorded a recent price
  observation for, which is itself a fixed, small watchlist
  (`BTCUSDT`/`ETHUSDT`/`SOLUSDT` as currently configured). Not a
  contradiction of the repository owner's choice — no *new* allowlist
  mechanism was added — but a real, structural narrowing that falls out
  of Decision 3's data-source change, worth being explicit about rather
  than letting it look like silently-reintroduced scope.
- Market orders only for this first build (not limit orders) — accepts
  whatever price Coinbase fills at, simpler and more predictable to
  implement correctly than tracking/cancelling unfilled limit orders;
  the $100 per-trade cap bounds worst-case slippage exposure regardless.

### 3. `CoinbaseTradingPort` (write side, real Coinbase calls) + `MarketHistoryPort` (read side, this platform's own database, not Coinbase/Binance)

**Revised from this ADR's initial draft** (Context): the read side is
no longer a live Coinbase/Binance price fetch. Each cycle reads
`crypto-market-agent`'s recent structured history via ADR-0038's
`list_recent_prices(role="crypto-market", symbol, since)` and
`list_recent_findings(role="crypto-market", since)` (a bounded lookback
window, e.g. the last 24 hours), plus `forex-market-agent`'s recent
findings the same way (`role="forex-market"`) as macro context only —
never as a trade target, since Coinbase has no forex products.
`CoinbaseTradingPort` itself shrinks to the write side and the account-
balance read needed to size/validate an order: exactly one write
method, `place_market_order(product_id, side, notional_usd)` — no
cancel, no limit order, no withdrawal, no transfer, no
account-settings method exists on this Protocol at all. A real
`GET /accounts`-shaped read (for balance) and a real
`POST /orders`-shaped write; every write failure is a real
order-placement failure, never best-effort. If ADR-0038's history has
no observation for a symbol recently enough (freshness window, e.g. 2
hours — `crypto-market-agent` runs hourly), that symbol is simply
unavailable as a trade target this cycle; the AI Router prompt is built
only from symbols with fresh history, and a proposed order for anything
else is rejected the same way an out-of-watchlist symbol already was
in `crypto-market-agent`/`forex-market-agent`'s own finding validation
(ADR-0035/0036's post-review fix).

### 4. A separate real-money budget table, never conflated with AI-cost tracking

Every existing autonomous role's `agent.autonomous_role_budget` table
tracks `spend_cents_used` as an *estimated AI provider cost* in cents
(ADR-0028 Decision 2) — displayed on the dashboard against a $1/day
cap. Reusing that same column for this role's *real trading dollars*
would silently conflate two entirely different quantities and scales
(cents of AI cost vs. dollars of real capital), and would make the
existing dashboard progress bar dangerously misleading (100% "budget
used" at $1 of AI spend, when the real cap is $200 of real money). A
new migration adds `agent.autonomous_trade_budget (role, day,
trades_used, notional_cents_used)` — same shape, deliberately a
separate table, checked independently from (in addition to, not
instead of) the existing AI-cost budget every role already has, since
this role still makes AI Router calls too.

### 5. Real history in, not a single live snapshot — one AI Router call per cycle, same strict-parse discipline

**Revised** (Context/Decision 3): fetch account balance (Coinbase) +
recent crypto price/finding history (ADR-0038, `role="crypto-market"`)
+ recent forex findings as context only (ADR-0038, `role="forex-market"`)
→ one AI Router call proposing a bounded batch of orders, now reasoning
over an actual trend window instead of one moment in time (mirroring
`scrum-master-agent`'s propose-then-dispatch shape, not the observer
roles' no-dispatch shape — this role, uniquely among
ADR-0035/0036/0037/0038, has real actions to propose) → strict
JSON-shape parse, reject the whole batch on any mismatch → validate
each proposal against the per-trade cap, remaining daily budget, and
Decision 3's freshness/watchlist-membership check → dispatch
sequentially, recording every attempt (win or lose) to
`agent.autonomous_actions`, same audit-log table and dashboard
visibility every prior role already has (`result_detail` now genuinely
displayable per ADR-0035/0036's post-review fix).

### 6. An additional, role-specific "trading enabled" gate — off by default, separate from the platform kill switch

The platform-wide kill switch (`agent.autonomous_kill_switch`,
ADR-0026 Decision 7) is shared across every autonomous role — engaging
it to gate this one role's first trade would also halt
`scrum-master-agent`/`product-owner-agent`/etc., which is too blunt an
instrument for a risk this specific. A new, role-scoped
`agent.autonomous_trading_enabled (role TEXT PRIMARY KEY, enabled
BOOLEAN NOT NULL DEFAULT FALSE)` table adds a second, independent gate
checked every cycle, **defaulting to `FALSE`**: even after a real,
correctly-scoped API key is supplied (Decision 1), this role places no
real order until the repository owner explicitly flips this row to
`TRUE` by direct SQL — the same "toggle by SQL, no redeploy needed"
mechanism the kill switch already uses, deliberately duplicated here as
a second, role-specific lock rather than relying on the shared one.
This is stricter than every prior role's rollout: `scrum-master-agent`'s
first real write action merely *awaited* an explicit go-ahead as a
documented caveat (ADR-0028's Implementation Status); this role makes
that gate a structural, code-enforced default rather than a promise.

## Security

This is a materially different risk class from every prior role, and
this ADR treats it as such rather than reusing ADR-0026's risk analysis
by reference:

- **Real, irreversible financial loss is the direct consequence of a
  successful prompt injection here** — not "an unwanted comment" or "a
  wrong status change," a filled order at real money. The per-trade
  ($100) and daily ($200/3 trades) caps bound the *maximum* single
  incident and the *maximum* one-day incident, not the probability of
  one occurring; caps are a blast-radius limit, not a prevention
  mechanism, same honest framing ADR-0026's own Security section used
  for every role's audit-log-is-after-the-fact posture.
- **No instrument allowlist (repository owner's explicit, informed
  choice)** widens the injection surface beyond every other role's:
  fetched/generated price context naming an illiquid or unfamiliar
  product could steer a trade somewhere genuinely bad-faith content
  couldn't achieve against a fixed, small watchlist. Accepted as a
  known residual risk, not an oversight.
- **The withdrawal-permission boundary is enforced two ways, not one**:
  by how the repository owner scopes the Coinbase API key (outside
  this platform's control) and, independently, by `CoinbaseTradingPort`
  having no code path that could call a withdrawal/transfer endpoint
  even if the key had that permission (the same structural pattern
  `scrum_master_agent.tracker`'s "no push endpoint" and every
  review-only specialist's "no merge method" already established).
- **The role-specific trading-enabled gate (Decision 6) is this ADR's
  answer to "how do we avoid a first real trade nobody meant to
  authorize yet"** — every review-only/board-write role before this
  could fail closed safely on a placeholder credential alone (a fake
  PAT just gets `401`s); a fake Coinbase key would too, but this role's
  stakes warranted a second, explicit, human-flipped switch on top of
  that, not reliance on the credential-rollout timing alone.

## Alternatives Considered

### Limit orders instead of market orders

Rejected for this first build: correctly tracking and cancelling
unfilled limit orders is real additional engineering and failure-mode
surface (a limit order sitting open across cycles, a partial fill, a
stale order needing cancellation before a new one can be proposed).
Market orders accept whatever price Coinbase fills at, which the $100
per-trade cap already bounds the worst case of. Revisit once market
orders have run safely in production, matching this codebase's
established narrower-MVP-first precedent (ADR-0028 Decision 1 →
ADR-0029).

### An instrument allowlist

Recommended, and explicitly declined by the repository owner after
being shown the alternative (Context) — not silently omitted. See
Security for the accepted residual risk.

### Reusing `agent.autonomous_role_budget`'s existing `spend_cents_used` column for trade notional

Rejected outright — see Decision 4. Conflating estimated-AI-cost cents
with real-trading-capital dollars in the same column/dashboard display
is the kind of mistake that looks like a harmless code-reuse shortcut
and is actually a real-money risk (a misread dashboard, not just an
engineering inelegance).

### Gating only on the existing platform-wide kill switch, no role-specific gate

Rejected — see Decision 6. The shared kill switch remains the
platform-wide emergency stop (it still applies here too, checked
first, same as every role); this role additionally needs its own,
narrower, off-by-default gate that doesn't require halting every other
autonomous role to keep this one's first trade from firing
prematurely.

## Consequences

### Positive

- Delivers real, bounded autonomous trade execution exactly as
  requested, with defense-in-depth beyond every prior role's safety
  posture: per-trade cap, independent daily trade-count and daily
  notional caps, a dedicated real-money budget table kept structurally
  separate from AI-cost tracking, structural incapability of
  withdrawal, and a second, role-specific, off-by-default enablement
  gate on top of the shared kill switch.

### Negative

- The highest-blast-radius role this platform has ever authorized —
  real, irreversible financial loss is a genuine possible outcome of a
  successful prompt injection or a model misjudgment, bounded but not
  prevented by the caps above.
- No instrument allowlist, a knowingly-accepted residual risk (Security).
- A new migration, a new persistence port, and a second real-money-
  specific safety table — more new engineering surface than any prior
  role since `scrum-master-agent` (ADR-0028) itself.
- Market-order-only means real slippage exposure on any less-liquid
  product, especially relevant given no instrument allowlist.
- Requires the repository owner to fund a real Coinbase account and
  scope a real API key correctly (no withdrawal permission) before this
  role can ever place a real trade — a genuine operational dependency
  outside this platform's control.

## Related Decisions

- [ADR-0026: Autonomous Team Agents](ADR-0026-autonomous-team-agents.md) — the `PeriodicService`/kill-switch/per-role-budget/audit-log pattern this role extends, not replaces
- [ADR-0028: `scrum-master-agent` Phase 2](ADR-0028-scrum-master-agent-phase-2.md) — the propose-then-dispatch execution model this role's `run_cycle` mirrors
- [ADR-0031: `principal-developer-agent` Phase 4](ADR-0031-principal-developer-agent-phase-4.md) — this platform's previous highest-blast-radius role (merge rights), the bar this ADR's Context measures against and exceeds
- [ADR-0035: `crypto-market-agent`](ADR-0035-crypto-market-agent.md) — the ADR that first anticipated and declined this exact request without its own sign-off; this ADR is that sign-off
- [ADR-0038: Structured Market History](ADR-0038-structured-market-history.md) — the data source this role reads from (Decision 3/5's revision), instead of an independent live fetch
- [ADR-0039: `fxcm-trader-agent`](ADR-0039-fxcm-trader-agent.md) — the forex counterpart; a separate role/broker/credential, not this one's responsibility despite both consuming ADR-0038's history
- [ADR-0032: Autonomous Agent Dashboard Visibility](ADR-0032-autonomous-agent-dashboard-visibility.md) — the dashboard panel this role's trades surface through, `KNOWN_ROLES` extended, same `result_detail` visibility ADR-0035/0036 already fixed

## References

- `src/ai_platform/agents/scrum_master_agent/agent.py` — the propose-then-dispatch cycle shape to follow
- `src/ai_platform/ports/persistence/autonomous.py` — `AutonomousStatePort`, extended (new methods) rather than reused unchanged, per Decision 4/6's two new tables
- `src/ai_platform/agents/crypto_market_agent/` / `src/ai_platform/agents/forex_market_agent/` — ADR-0038's `MarketHistoryPort` read side, the actual data source per Decision 3

## Implementation Status

**Proposed — not accepted, no code written.** Given this role's stakes
materially exceed every role built so far, this ADR is deliberately
left for the repository owner's explicit review and acceptance before
any implementation begins, unlike ADR-0035/0036 (accepted and
implemented in the same pass they were drafted). `SECURITY.md` also
needs a new carve-out paragraph naming this ADR and role explicitly,
per the same "any new role... remain[s] fully subject to this section's
approval requirement" text every prior role ADR has re-amended.
