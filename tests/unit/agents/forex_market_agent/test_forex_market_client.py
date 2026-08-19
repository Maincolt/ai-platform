"""Tests for `forex_market_agent.client.FrankfurterExchangeRateClient` --
same `httpx.MockTransport` pattern as `crypto_market_agent`'s client
tests, deliberately independent code (ADR-0036 Decision 3).
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

import httpx
import pytest

from ai_platform.agents.forex_market_agent.client import FrankfurterExchangeRateClient
from ai_platform.agents.forex_market_agent.errors import ExchangeRateFetchFailedError


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def _client(handler: Any, **overrides: Any) -> FrankfurterExchangeRateClient:
    defaults: dict[str, Any] = {
        "base_currency": "EUR",
        "target_currencies": ("USD", "GBP"),
        "client": httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    }
    defaults.update(overrides)
    return FrankfurterExchangeRateClient(**defaults)


def test_fetch_returns_rates_for_every_watchlist_currency_present() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "amount": 1.0,
                "base": "EUR",
                "date": "2026-08-19",
                "rates": {"USD": 1.09, "GBP": 0.86},
            },
        )

    snapshot = _run(_client(handler).fetch())

    assert snapshot.base_currency == "EUR"
    assert snapshot.as_of_date == "2026-08-19"
    assert {rate.currency: rate.rate for rate in snapshot.rates} == {"USD": 1.09, "GBP": 0.86}


def test_non_200_response_raises_fetch_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    with pytest.raises(ExchangeRateFetchFailedError):
        _run(_client(handler).fetch())


def test_malformed_json_raises_fetch_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    with pytest.raises(ExchangeRateFetchFailedError):
        _run(_client(handler).fetch())


def test_missing_rates_key_raises_fetch_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"amount": 1.0, "base": "EUR", "date": "2026-08-19"})

    with pytest.raises(ExchangeRateFetchFailedError):
        _run(_client(handler).fetch())


def test_no_watchlist_currencies_present_raises_fetch_failed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"amount": 1.0, "base": "EUR", "date": "2026-08-19", "rates": {}}
        )

    with pytest.raises(ExchangeRateFetchFailedError):
        _run(_client(handler).fetch())


def test_empty_target_currencies_rejected_at_construction() -> None:
    with pytest.raises(ValueError, match="target_currencies"):
        FrankfurterExchangeRateClient(base_currency="EUR", target_currencies=())


def test_request_targets_frankfurter_latest_with_watchlist_params() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200, json={"amount": 1.0, "base": "EUR", "date": "2026-08-19", "rates": {"USD": 1.09}}
        )

    _run(_client(handler, target_currencies=("USD",)).fetch())

    assert len(captured) == 1
    request = captured[0]
    assert request.url.host == "api.frankfurter.app"
    assert request.url.path == "/latest"
    query = request.url.params
    assert query["from"] == "EUR"
    assert query["to"] == "USD"
