"""Structured, queryable price/finding history for `crypto-market-agent`/
`forex-market-agent` (ADR-0038).

Additive to `AutonomousStatePort.record_action`'s existing audit-log
row -- both roles still write that row unchanged (ADR-0026 Decision 7's
"one row per attempted action, in one place" invariant), and separately
write through this port so the same content is also queryable as a
time series. One shared Protocol/adapter (like `AutonomousStatePort`
itself) -- both roles call it independently, mirroring how they already
both depend on `AutonomousStatePort` without that implying a shared
domain package between them (ADR-0035/ADR-0036 Decision 3/4 is about
`crypto_market_agent`/`forex_market_agent`'s own business logic staying
separate, not about shared infrastructure ports).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PriceObservation:
    """One raw price-tick row -- no AI interpretation, exactly what was
    fetched."""

    role: str
    symbol: str
    price: float
    change_24h_percent: float | None
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class FindingRecord:
    """One AI-generated finding row, the same content already written to
    `agent.autonomous_actions`, now first-class and queryable."""

    role: str
    symbol: str
    summary: str
    severity: str
    observed_at: datetime


class MarketHistoryPort(Protocol):
    async def record_price_observation(
        self,
        *,
        role: str,
        symbol: str,
        price: float,
        change_24h_percent: float | None,
        observed_at: datetime,
    ) -> None:
        """Append one raw price-tick row. Called once per watchlist
        symbol/pair per cycle, independent of whether that symbol
        produced a finding this cycle."""
        ...

    async def record_finding(
        self,
        *,
        role: str,
        symbol: str,
        summary: str,
        severity: str,
        observed_at: datetime,
    ) -> None:
        """Append one finding row. Called once per finding, alongside
        (not instead of) the existing `AutonomousStatePort.record_action`
        call for the same finding."""
        ...

    async def list_recent_prices(
        self, *, role: str, symbol: str, since: datetime
    ) -> tuple[PriceObservation, ...]:
        """Every price observation for `symbol` under `role` at or after
        `since`, oldest first -- the trend window a trader role's AI
        Router prompt is built from (ADR-0037/ADR-0039)."""
        ...

    async def list_recent_findings(
        self, *, role: str, since: datetime
    ) -> tuple[FindingRecord, ...]:
        """Every finding for `role` at or after `since`, oldest first --
        across every symbol/pair that role covers."""
        ...
