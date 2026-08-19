# ADR-0035: `crypto-market-agent` — A Read-Only, Action-Free Autonomous Role

- **Status:** Accepted
- **Date:** 2026-08-19
- **Supersedes:** None
- **Superseded by:** None

## Context

The repository owner asked for a "financial market specialist" role.
Confirmed via direct question: this should be a `PeriodicService`-driven
autonomous role (the `scrum-master-agent`/specialist-reviewer family,
not a Workflow-invoked capability), watching crypto prices via a public
exchange API, on a configured watchlist.

This role has no precedent action to take. Every prior autonomous role
(`scrum-master-agent`, `product-owner-agent`, `principal-developer-agent`,
the three PR-review specialists) exists to propose and dispatch a real
action against GitHub, bounded by ADR-0026's kill-switch/budget/audit
machinery. A market agent that could place trades would be a categorically
new, far higher-consequence capability class (real money, genuinely
irreversible) — not requested, and not what this ADR proposes. What
*is* requested is an observer: fetch prices, produce one AI Router
call's worth of advisory findings (trend/volatility commentary), and
record them. It never acts on anything external.

Because it takes no external write action, `crypto-market-agent` does
not touch `SECURITY.md`'s Human Approval for High-Impact Actions
carve-out at all — that section governs actions, and this role performs
none. No amendment to `SECURITY.md` is proposed here (see Decision 4).

## Decision

### 1. Data source: Binance's public `/api/v3/ticker/24hr` endpoint, no credential

Unauthenticated, free, unauthenticated public market-data endpoint —
revised during implementation from this ADR's original choice
(CoinGecko's `/simple/price`) at the repository owner's request, after
finding CoinGecko's plans page looked "a bit expansive" (the *paid* Pro
tier's pricing; the free, keyless `/simple/price` endpoint used here was
never actually paid, but Binance's own public feed was judged a cleaner
fit anyway — an exchange's own market data, not a third-party
aggregator, with no separate pricing page to cause the same confusion
again). No change to this ADR's core shape: still **no PAT, no
credential of any kind** — a public GET request against a configured
list of trading-pair symbols (e.g. `BTCUSDT`, `ETHUSDT`), returning
current price plus 24h change. Lower blast radius than every prior
role: there is no credential to place under least privilege because
none exists.

### 2. Watchlist: configuration, not hardcoded

A list of Binance trading-pair symbols read from runtime configuration,
matching `scrum.status`'s precedent (fetch target is config, not a
hardcoded constant — no SSRF-shaped risk to close off for a public
read-only API call against a fixed, known host).

### 3. Execution model: fetch, one AI Router call, record — no dispatch step

`PeriodicService`-driven (reused unchanged, same as `scrum-master-agent`),
hourly cycle. Unlike every prior autonomous role, there is no
propose-then-dispatch split: the AI Router call's output *is* the
finding, not a proposed action to validate against an allowlist. Shape:
kill-switch check → fetch prices → one AI Router call
(`{symbol, summary, severity}` findings, same structured-findings shape
every capability already uses) → write one row per cycle into
`agent.autonomous_actions` (reused unchanged, zero new migration) with
`action_type='record_finding'` and the findings as `result` — the
existing table's columns (role, action type, target, inputs, result,
timestamp) already fit an observation as well as an action; only the
*meaning* of "result" changes, from "what happened when I tried to
write to GitHub" to "what I found."

### 4. No `SECURITY.md` amendment

The exemption pattern established by ADR-0026/0033/0034 exists to
narrowly excuse specific *actions* from per-action human approval.
This role has no action to excuse — `record_finding`'s only effect is a
local database write, the same kind of effect any capability's
`TaskCompleted` persistence already has without needing an exemption.
Confirmed against `SECURITY.md`'s own text: the approval requirement
applies to actions "outside a role's explicitly granted set"; a role
with an empty external-action set needs no grant.

### 5. Daily budget, no action cap

The $1.00/day estimated-AI-spend cap (ADR-0026 Decision 2, applied
uniformly since) still applies, tracked as `role='crypto-market'` in
the existing `agent.autonomous_role_budget` table — this bounds AI
provider cost, independent of whether the role can act. The
10-actions/day cap that exists elsewhere to bound GitHub write volume
does not apply here in the same sense (there is nothing to rate-limit
beyond the hourly cadence itself); the daily spend cap alone is
sufficient.

### 6. Dashboard visibility

Appears on the existing "Autonomous Agents" tab (`AutonomousAgentsPanel.vue`'s
`KNOWN_ROLES`, extended, per ADR-0032's precedent) showing today's spend
usage and recent findings from `agent.autonomous_actions` — no new
frontend surface needed, the existing recent-audit-log view already
renders arbitrary `result` content per row.

## Security

Lowest blast radius of any autonomous role built so far: no credential
to misuse or leak (public API, no auth), and no external write path
exists in code at all — `record_finding`'s only side effect is a row in
this platform's own database. A successful prompt injection via
manipulated price-feed content (unlikely for numeric price data, but
not impossible if Binance ever includes free-text fields) could at
most produce a misleading finding string, never an action — the same
"structurally incapable of doing anything but writing text" posture the
PR-review specialists already established, one level further removed
since there is not even a comment-posting capability here.

## Alternatives Considered

### Trade execution (real orders against an exchange)

Rejected outright, not deferred — this is a categorically different,
far higher-consequence capability class (real money, genuinely
irreversible action) that was never requested and would need its own
from-scratch ADR, explicit repository-owner sign-off, and almost
certainly a `SECURITY.md` amendment given the stakes exceed even
`principal-developer-agent`'s merge rights.

### A Workflow-invoked capability instead (like `data.analysis`)

Rejected per the repository owner's explicit choice of the autonomous,
scheduled pattern over the on-demand, submitted-input pattern — the
point is a standing watchlist checked on a cadence, not a one-off
analysis of caller-supplied data.

### CoinGecko's `/simple/price` endpoint (this ADR's original choice)

Superseded during implementation, not because it required payment (the
`/simple/price` endpoint used here is genuinely free and keyless) but
because CoinGecko's pricing page reads as commercial/expansive at a
glance and the repository owner preferred to avoid that ambiguity
entirely going forward. Binance's public 24h-ticker endpoint has no
paid tier attached to the same feed at all, removing the concern by
construction rather than by re-explaining the free/paid boundary each
time. See Decision 1.

### A dedicated findings table instead of reusing `agent.autonomous_actions`

Considered, for semantic cleanliness ("finding" is not really an
"action"). Rejected to keep this ADR's marginal engineering cost
minimal, matching the zero-new-migration precedent of every specialist
role since ADR-0028 — the existing table's columns already fit without
strain, and a purpose-built name would be the only benefit.

## Consequences

### Positive

- No new credential, no new migration, no `SECURITY.md` amendment — the
  smallest-footprint autonomous role added so far.
- Extends the platform into a genuinely new domain (external market
  data) using only existing primitives (`PeriodicService`, AI Router,
  `agent.autonomous_actions`).

### Negative

- A seventh autonomous role deployment to operate, with its own failure
  mode (a public API this platform doesn't control, no SLA).
- `result_data`/`result` semantics now carries two meanings across
  roles (attempted-action outcome vs. observation) in the same column —
  a minor readability cost accepted for zero new migration.
- Binance's public endpoint is rate-limited and could throttle or
  change without notice, same category of risk any free public API
  carries; no fallback provider is proposed here.

## Related Decisions

- [ADR-0026: Autonomous Team Agents](ADR-0026-autonomous-team-agents.md) — the `PeriodicService`/kill-switch/budget pattern this role reuses; explicitly does not extend its action-exemption grant, since this role has no actions
- [ADR-0027: `scrum.status`](ADR-0027-scrum-status-capability.md) — the config-driven-fetch-target precedent (Decision 2)
- [ADR-0028: `scrum-master-agent` Phase 2](ADR-0028-scrum-master-agent-phase-2.md) — `PeriodicService`, the safety-mechanism trio, and the `agent.autonomous_actions` table this role writes to unchanged
- [ADR-0032: Autonomous Agent Dashboard Visibility](ADR-0032-autonomous-agent-dashboard-visibility.md) — the dashboard panel this role's findings surface through unchanged

## References

- `src/ai_platform/agents/scrum_master_agent/agent.py` — the `PeriodicService`/kill-switch/budget cycle shape to follow, minus the dispatch step
- `src/ai_platform/agents/_autonomous_shared.py` — shared spend-estimate/JSON-fence helpers to reuse

## Implementation Status

A pre-merge review (PR #67) found three real gaps, all fixed before
merge: (1) `agent.autonomous_actions.result_detail` was written but
never surfaced anywhere the dashboard could show it, contradicting this
ADR's own Decision 6 claim — `AutonomousActionRecord`/the `GET
/api/v1/autonomous-agents` response/the dashboard table now include a
truncated `result_detail` column (previously excluded platform-wide per
ADR-0032 Security; now included since these two roles' entire purpose
is to surface it, and it renders as plain, escaped text); (2)
`_parse_findings` validated a finding's `symbol` shape but never
checked it against the symbols actually present in the fetched
snapshot, so a hallucinated or injected off-watchlist symbol could be
recorded as a real observation — `run_cycle` now rejects the whole
batch if any finding references a symbol outside the fetched watchlist,
matching this codebase's existing "reject the whole batch on any
mismatch" discipline; (3) the Binance multi-symbol query parameter used
`json.dumps`'s default separators (a space after each comma), untested
for the multi-symbol case — now uses compact separators, with a new
multi-symbol test.

Accepted and implemented: `src/ai_platform/agents/crypto_market_agent/`
(`client.py`'s `BinanceMarketClient`, `agent.py`'s `CryptoMarketAgent`
and strict findings parser), `CryptoMarketRuntimeConfig`
(`runtime/configuration.py`), `build_crypto_market_process`
(`runtime/composition.py`), the `ai-platform-crypto-market-agent` entry
point, and a `crypto-market-agent` Compose service (no secrets beyond
the ones every role already shares — no PAT, per Decision 1). Switched
from the originally-implemented `CoinGeckoMarketClient` to
`BinanceMarketClient` per Decision 1's revision, before any deployment
— no live traffic or deployed state to migrate. Unit tests cover the
findings parser and the Binance client against a fake transport. Ruff,
BasedPyright (strict), and the full unit suite (707 tests) all pass.
Not yet deployed/live-verified against the Mac Docker host.
