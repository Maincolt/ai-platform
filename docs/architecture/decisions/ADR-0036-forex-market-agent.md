# ADR-0036: `forex-market-agent` — A Second, Independent Market-Observer Role

- **Status:** Accepted
- **Date:** 2026-08-19
- **Supersedes:** None
- **Superseded by:** None

## Context

Following [ADR-0035](ADR-0035-crypto-market-agent.md) (`crypto-market-agent`,
also Proposed, not yet implemented), the repository owner asked for a
second financial-market observer: a forex specialist. Same shape —
`PeriodicService`-driven, read-only, no action, no credential-bearing
external write — watching currency-pair movement instead of crypto
prices.

Both roles share the same broad shape (fetch a watchlist from a public
price API, one AI Router call, record a finding, no dispatch step), the
same situation [ADR-0033](ADR-0033-frontend-and-postgres-specialist-agents.md)
found with `frontend-specialist-agent`/`postgres-specialist-agent`.
Unlike ADR-0033, this ADR deliberately does **not** follow that
precedent into a shared package: the repository owner's explicit choice
is that each observer role stands on its own, fully self-contained
implementation, not a class parametrized across data sources. This
keeps each role's failure modes, testing, and future divergence
(crypto and forex data are not guaranteed to stay this similar —
per-pair sub-markets, different exchanges, different finding shapes)
fully independent from day one, at the cost of some duplicated
boilerplate between the two.

## Decision

### 1. Data source: Frankfurter's public `/latest` endpoint, no credential

`https://api.frankfurter.app/latest` — free, unauthenticated, ECB
reference exchange rates, updated daily on ECB business days. Same
"no credential of any kind" posture as `crypto-market-agent`'s CoinGecko
source (Decision 1 there): a public GET request, no PAT, no key file,
nothing to place under least privilege because nothing exists to leak.

Noted limitation carried into Consequences: ECB reference rates update
once per business day, not continuously — an hourly poll will often see
the exact same figures across several consecutive cycles. This is a
real difference from crypto's near-continuous movement, not a bug to
fix; the AI Router prompt should be worded to say "no change since last
observation" rather than manufacturing commentary on identical data.

### 2. Watchlist: configuration, currency pairs against a base

A list of target currencies (e.g. `USD`, `GBP`, `JPY`) against a
configured base currency (e.g. `EUR`), read from runtime configuration
— same config-driven-fetch-target precedent `scrum.status` and
`crypto-market-agent` both already establish.

### 3. Standalone implementation: `forex_market_agent`, no shared package

A dedicated `src/ai_platform/agents/forex_market_agent/` package,
independent of `crypto-market-agent`'s own package
(`crypto_market_agent`, per ADR-0035). Each owns its full
`PeriodicService`/kill-switch/budget/fetch/one-AI-call/record-finding
cycle, its own fetch client (Frankfurter here, CoinGecko there), its
own prompt wording, and its own `build_forex_market_agent_process()`
composition function. No shared base class, no parametrized "market
observer" abstraction — each role is fully capable and comprehensible
on its own, matching the repository owner's explicit choice not to
couple the two. ADR-0035 is unchanged by this decision; `crypto-market-agent`
remains exactly the standalone implementation it already specified.

### 4. Same budget tracking, no `SECURITY.md` amendment

`role='forex-market'` in the existing `agent.autonomous_role_budget`
table (ADR-0026 Decision 2's $1.00/day estimated-spend cap, tracked
independently per role, same as every prior role). Same reasoning as
ADR-0035 Decision 4: no external action exists to exempt, so no
`SECURITY.md` change is needed. `record_finding` continues to write
into `agent.autonomous_actions` (zero new migration), findings surfaced
through the existing "Autonomous Agents" dashboard panel (ADR-0032),
`KNOWN_ROLES` extended with `forex-market` alongside `crypto-market`.

## Security

Identical posture to `crypto-market-agent` (ADR-0035's Security
section applies unchanged): no credential to misuse, no external write
path in code, so a successful prompt injection via manipulated rate
data could at most produce a misleading finding string, never an
action. Numeric exchange-rate data narrows this further than even
`crypto-market-agent`'s already-minimal surface.

## Alternatives Considered

### A shared `market_observer_agent` package (mirroring ADR-0033's PR-review specialists)

Considered, and structurally straightforward — both roles differ only
in data source, watchlist shape, and prompt wording, the same signal
ADR-0033 acted on for the two PR-review specialists. Rejected per the
repository owner's explicit instruction: each observer role must be
capable fully on its own, not layered on a shared abstraction, even at
the cost of some duplicated boilerplate between the two packages.

### A commercial forex API with a key (e.g. exchangerate-api.com's paid tier)

Rejected: Frankfurter's free, credential-free, ECB-backed endpoint is
sufficient for advisory commentary and keeps this role's footprint as
small as `crypto-market-agent`'s. Revisit only if intraday (sub-daily)
rate movement is later judged necessary.

## Consequences

### Positive

- No new credential, no new migration, no `SECURITY.md` amendment —
  same minimal footprint as `crypto-market-agent`.
- Fully independent from `crypto-market-agent`: either role can change,
  fail, or be removed without touching the other's code at all.

### Negative

- An eighth autonomous role deployment to operate (following
  `crypto-market-agent`), with its own failure mode (Frankfurter's own
  availability, no SLA).
- ECB reference rates' once-daily update cadence means many hourly
  cycles will produce "no change" findings — expected, not a defect,
  but worth knowing before reading the audit log and expecting
  crypto-like movement.
- Duplicates the `PeriodicService`/kill-switch/budget/record-finding
  boilerplate `crypto-market-agent` also implements — accepted cost of
  keeping the two roles decoupled (Decision 3), not an oversight.

## Related Decisions

- [ADR-0035: `crypto-market-agent`](ADR-0035-crypto-market-agent.md) — the sibling role with the same broad shape; deliberately independent implementations, not a shared base
- [ADR-0033: `frontend-specialist-agent` and `postgres-specialist-agent`](ADR-0033-frontend-and-postgres-specialist-agents.md) — the shared-package precedent this ADR considered and declined to follow (Alternatives)
- [ADR-0026: Autonomous Team Agents](ADR-0026-autonomous-team-agents.md) — the `PeriodicService`/budget pattern both observer roles reuse; no action-exemption grant needed since neither role acts
- [ADR-0032: Autonomous Agent Dashboard Visibility](ADR-0032-autonomous-agent-dashboard-visibility.md) — the dashboard panel this role's findings surface through unchanged

## References

- `src/ai_platform/agents/scrum_master_agent/agent.py` — the `PeriodicService`/kill-switch/budget cycle shape to follow independently, minus the dispatch step

## Implementation Status

The same pre-merge review that covered ADR-0035 (PR #67) applies here
too: `result_detail` dashboard visibility (shared fix, `AutonomousActionRecord`/
API/dashboard table) and the same off-watchlist-`pair` rejection added
to `run_cycle`, independently implemented per Decision 3 (no shared
helper with `crypto_market_agent`'s equivalent check).

Accepted and implemented: `src/ai_platform/agents/forex_market_agent/`
(`client.py`'s `FrankfurterExchangeRateClient`, `agent.py`'s
`ForexMarketAgent` and its own independent findings parser),
`ForexMarketRuntimeConfig` (`runtime/configuration.py`),
`build_forex_market_process` (`runtime/composition.py`), the
`ai-platform-forex-market-agent` entry point, and a
`forex-market-agent` Compose service. Fully standalone from
`crypto-market-agent`'s code, per Decision 3 — no shared module, no
shared config base beyond `_AutonomousRoleRuntimeConfigBase` every
autonomous role already shares. Unit tests cover the findings parser
and the Frankfurter client against a fake transport. Ruff,
BasedPyright (strict), and the full unit suite (707 tests) all pass.
Not yet deployed/live-verified against the Mac Docker host.
