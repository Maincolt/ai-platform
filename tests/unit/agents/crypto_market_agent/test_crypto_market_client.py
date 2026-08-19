"""Tests for `crypto_market_agent.client.BinanceMarketClient` -- the
read-only fetch boundary, exercised against a fake transport (same
`httpx.MockTransport` pattern every prior fetch-based role's tests
already use), never a real network call.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

import httpx
import pytest

from ai_platform.agents.crypto_market_agent.client import BinanceMarketClient
from ai_platform.agents.crypto_market_agent.errors import MarketDataFetchFailedError


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def _client(handler: Any, **overrides: Any) -> BinanceMarketClient:
    defaults: dict[str, Any] = {
        "symbols": ("BTCUSDT", "ETHUSDT"),
        "client": httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    }
    defaults.update(overrides)
    return BinanceMarketClient(**defaults)


def test_fetch_returns_prices_for_every_watchlist_symbol_present() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"symbol": "BTCUSDT", "lastPrice": "65000.50", "priceChangePercent": "3.20"},
                {"symbol": "ETHUSDT", "lastPrice": "3200.10", "priceChangePercent": "-1.10"},
            ],
        )

    snapshot = _run(_client(handler).fetch())

    assert {price.symbol: price.price_usd for price in snapshot.prices} == {
        "BTCUSDT": 65000.50,
        "ETHUSDT": 3200.10,
    }
    assert {price.symbol: price.change_24h_percent for price in snapshot.prices} == {
        "BTCUSDT": 3.20,
        "ETHUSDT": -1.10,
    }


def test_missing_24h_change_is_none_not_a_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"symbol": "BTCUSDT", "lastPrice": "65000.50"}])

    snapshot = _run(_client(handler, symbols=("BTCUSDT",)).fetch())

    assert snapshot.prices[0].change_24h_percent is None


def test_non_200_response_raises_fetch_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    with pytest.raises(MarketDataFetchFailedError):
        _run(_client(handler).fetch())


def test_malformed_json_raises_fetch_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    with pytest.raises(MarketDataFetchFailedError):
        _run(_client(handler).fetch())


def test_non_list_response_raises_fetch_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"symbol": "BTCUSDT"})

    with pytest.raises(MarketDataFetchFailedError):
        _run(_client(handler).fetch())


def test_no_watchlist_symbols_present_raises_fetch_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    with pytest.raises(MarketDataFetchFailedError):
        _run(_client(handler).fetch())


def test_empty_symbols_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="symbols"):
        BinanceMarketClient(symbols=())


def test_request_targets_binance_24h_ticker_with_watchlist_symbols() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=[{"symbol": "BTCUSDT", "lastPrice": "1.0"}])

    _run(_client(handler, symbols=("BTCUSDT",)).fetch())

    assert len(captured) == 1
    request = captured[0]
    assert request.url.host == "api.binance.com"
    assert request.url.path == "/api/v3/ticker/24hr"
    assert request.url.params["symbols"] == '["BTCUSDT"]'


def test_multi_symbol_request_has_no_spaces_in_the_json_array_param() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json=[
                {"symbol": "BTCUSDT", "lastPrice": "1.0"},
                {"symbol": "ETHUSDT", "lastPrice": "2.0"},
            ],
        )

    _run(_client(handler, symbols=("BTCUSDT", "ETHUSDT")).fetch())

    assert captured[0].url.params["symbols"] == '["BTCUSDT","ETHUSDT"]'
