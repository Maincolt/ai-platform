"""Postgres implementation of `MarketHistoryPort` (ADR-0038).

Reads and writes `agent.market_price_observations`/`agent.market_findings`
(migration 0010).
"""

from datetime import datetime
from decimal import Decimal

from ai_platform.adapters.persistence.connection import AsyncPsycopgPool
from ai_platform.ports.persistence.errors import PermanentPersistenceError
from ai_platform.ports.persistence.market_history import FindingRecord, PriceObservation


class PsycopgMarketHistoryPort:
    def __init__(self, pool: AsyncPsycopgPool) -> None:
        self._pool = pool

    async def record_price_observation(
        self,
        *,
        role: str,
        symbol: str,
        price: float,
        change_24h_percent: float | None,
        observed_at: datetime,
    ) -> None:
        async with self._pool.transaction() as connection:
            await connection.execute(
                """
                INSERT INTO agent.market_price_observations (
                    role, symbol, price, change_24h_percent, observed_at
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (role, symbol, price, change_24h_percent, observed_at),
            )

    async def record_finding(
        self,
        *,
        role: str,
        symbol: str,
        summary: str,
        severity: str,
        observed_at: datetime,
    ) -> None:
        async with self._pool.transaction() as connection:
            await connection.execute(
                """
                INSERT INTO agent.market_findings (
                    role, symbol, summary, severity, observed_at
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (role, symbol, summary, severity, observed_at),
            )

    async def list_recent_prices(
        self, *, role: str, symbol: str, since: datetime
    ) -> tuple[PriceObservation, ...]:
        async with self._pool.connection() as connection:
            rows = await (
                await connection.execute(
                    "SELECT price, change_24h_percent, observed_at "
                    "FROM agent.market_price_observations "
                    "WHERE role = %s AND symbol = %s AND observed_at >= %s "
                    "ORDER BY observed_at, id",
                    (role, symbol, since),
                )
            ).fetchall()
        observations: list[PriceObservation] = []
        for price, change_24h_percent, observed_at in rows:
            if not isinstance(price, Decimal | int | float) or not isinstance(
                observed_at, datetime
            ):
                raise PermanentPersistenceError("Stored price observation is invalid.")
            if change_24h_percent is not None and not isinstance(
                change_24h_percent, Decimal | int | float
            ):
                raise PermanentPersistenceError("Stored price observation is invalid.")
            observations.append(
                PriceObservation(
                    role=role,
                    symbol=symbol,
                    price=float(price),
                    change_24h_percent=(
                        float(change_24h_percent) if change_24h_percent is not None else None
                    ),
                    observed_at=observed_at,
                )
            )
        return tuple(observations)

    async def list_recent_findings(
        self, *, role: str, since: datetime
    ) -> tuple[FindingRecord, ...]:
        async with self._pool.connection() as connection:
            rows = await (
                await connection.execute(
                    "SELECT symbol, summary, severity, observed_at "
                    "FROM agent.market_findings "
                    "WHERE role = %s AND observed_at >= %s "
                    "ORDER BY observed_at, id",
                    (role, since),
                )
            ).fetchall()
        findings: list[FindingRecord] = []
        for symbol, summary, severity, observed_at in rows:
            if (
                not isinstance(symbol, str)
                or not isinstance(summary, str)
                or not isinstance(severity, str)
                or not isinstance(observed_at, datetime)
            ):
                raise PermanentPersistenceError("Stored market finding is invalid.")
            findings.append(
                FindingRecord(
                    role=role,
                    symbol=symbol,
                    summary=summary,
                    severity=severity,
                    observed_at=observed_at,
                )
            )
        return tuple(findings)
