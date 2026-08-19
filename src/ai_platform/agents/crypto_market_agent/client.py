"""The read-only crypto price fetch boundary (ADR-0035 Decision 1).

`MarketDataPort` is the same narrow-seam pattern every prior fetch-based
role already uses (`scrum_status_agent.board.ProjectBoardPort`,
`scrum_master_agent.tracker.ProjectTrackerPort`): `agent.py` and its
tests depend only on this Protocol, never on a real HTTP call.
`BinanceMarketClient` is the only piece of this module that actually
reaches Binance's public API.

Unlike every prior fetch-based role, this one needs no credential at
all -- Binance's `/api/v3/ticker/24hr` endpoint is a free, unauthenticated
public market-data feed (ADR-0035 Decision 1, revised from the ADR's
original CoinGecko choice: same no-credential shape, an exchange's own
public feed instead of a third-party aggregator).
"""

import json
from dataclasses import dataclass
from typing import Protocol, cast

import httpx

from ai_platform.agents.crypto_market_agent.errors import MarketDataFetchFailedError

_BINANCE_24H_TICKER_URL = "https://api.binance.com/api/v3/ticker/24hr"
_DEFAULT_REQUEST_TIMEOUT_SECONDS = 10.0
_MAX_SYMBOL_LENGTH = 20


@dataclass(frozen=True, slots=True)
class SymbolPrice:
    symbol: str
    """A Binance trading-pair symbol, e.g. "BTCUSDT"."""
    price_usd: float
    """`lastPrice` from the ticker -- exact in USD only for a `*USDT`/`*USD`
    pair; a caller configuring a non-dollar-quoted pair gets that pair's
    own quote currency here, unconverted."""
    change_24h_percent: float | None
    """`None` when Binance has no 24h-change figure for this symbol."""


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    prices: tuple[SymbolPrice, ...]


class MarketDataPort(Protocol):
    async def fetch(self) -> MarketSnapshot: ...


class BinanceMarketClient:
    def __init__(
        self,
        *,
        symbols: tuple[str, ...],
        client: httpx.AsyncClient | None = None,
        request_timeout_seconds: float = _DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        if not symbols:
            raise ValueError("symbols must not be empty")
        for symbol in symbols:
            if not symbol or len(symbol) > _MAX_SYMBOL_LENGTH:
                raise ValueError(f"invalid symbol: {symbol!r}")
        self._symbols = symbols
        self._client = client
        self._request_timeout_seconds = request_timeout_seconds

    async def fetch(self) -> MarketSnapshot:
        # Binance's multi-symbol form takes a JSON-array-encoded query
        # parameter (documented shape: symbols=["BTCUSDT","ETHUSDT"]) --
        # httpx percent-encodes the raw string value for us. Compact
        # separators (no space after the comma), matching this
        # codebase's existing precedent for a JSON string embedded
        # elsewhere (shared/logging), since the space is untested and
        # not confirmed accepted by Binance's parser.
        params = {"symbols": json.dumps(list(self._symbols), separators=(",", ":"))}
        try:
            if self._client is not None:
                response = await self._client.get(
                    _BINANCE_24H_TICKER_URL,
                    params=params,
                    timeout=self._request_timeout_seconds,
                )
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        _BINANCE_24H_TICKER_URL,
                        params=params,
                        timeout=self._request_timeout_seconds,
                    )
        except httpx.HTTPError as error:
            raise MarketDataFetchFailedError(str(error)) from error

        if response.status_code != 200:
            raise MarketDataFetchFailedError(f"HTTP {response.status_code}")

        try:
            payload = cast(object, response.json())
        except ValueError as error:
            raise MarketDataFetchFailedError(f"malformed JSON: {error}") from error
        if not isinstance(payload, list):
            raise MarketDataFetchFailedError("malformed response shape")
        entries = cast(list[object], payload)

        by_symbol: dict[str, dict[str, object]] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            entry_map = cast(dict[str, object], entry)
            symbol_value = entry_map.get("symbol")
            if isinstance(symbol_value, str):
                by_symbol[symbol_value] = entry_map

        prices: list[SymbolPrice] = []
        for symbol in self._symbols:
            entry_map = by_symbol.get(symbol)
            if entry_map is None:
                continue
            last_price = entry_map.get("lastPrice")
            if not isinstance(last_price, str):
                continue
            try:
                price_usd = float(last_price)
            except ValueError:
                continue
            change_24h_percent = _parse_optional_float(entry_map.get("priceChangePercent"))
            prices.append(
                SymbolPrice(
                    symbol=symbol, price_usd=price_usd, change_24h_percent=change_24h_percent
                )
            )
        if not prices:
            raise MarketDataFetchFailedError("no watchlist symbols present in response")
        return MarketSnapshot(prices=tuple(prices))


def _parse_optional_float(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return float(value)
    except ValueError:
        return None
