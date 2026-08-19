"""The read-only forex rate fetch boundary (ADR-0036 Decision 1).

`ExchangeRatePort` is the same narrow-seam pattern every prior
fetch-based role already uses. `FrankfurterExchangeRateClient` is the
only piece of this module that actually reaches Frankfurter's public
API.

Deliberately independent of `crypto_market_agent.client` (ADR-0036
Decision 3): no shared Protocol, no shared HTTP helper, even though the
shapes look similar. Like `crypto_market_agent`, this role needs no
credential -- Frankfurter's `/latest` endpoint is free and
unauthenticated ECB reference-rate data.
"""

from dataclasses import dataclass
from typing import Protocol, cast

import httpx

from ai_platform.agents.forex_market_agent.errors import ExchangeRateFetchFailedError

_FRANKFURTER_LATEST_URL = "https://api.frankfurter.dev/v1/latest"
"""`api.frankfurter.app` (this ADR's original choice) now permanently
redirects here (`301` to `api.frankfurter.dev/v1/latest`, confirmed live
against the Mac Docker deployment) -- calling the canonical host/path
directly avoids an extra redirect hop rather than relying on the HTTP
client to follow it."""
_DEFAULT_REQUEST_TIMEOUT_SECONDS = 10.0
_MAX_CURRENCY_CODE_LENGTH = 10


@dataclass(frozen=True, slots=True)
class CurrencyRate:
    currency: str
    rate: float
    """Units of `currency` per one unit of the snapshot's base currency."""


@dataclass(frozen=True, slots=True)
class ExchangeRateSnapshot:
    base_currency: str
    as_of_date: str
    rates: tuple[CurrencyRate, ...]


class ExchangeRatePort(Protocol):
    async def fetch(self) -> ExchangeRateSnapshot: ...


class FrankfurterExchangeRateClient:
    def __init__(
        self,
        *,
        base_currency: str,
        target_currencies: tuple[str, ...],
        client: httpx.AsyncClient | None = None,
        request_timeout_seconds: float = _DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        if not base_currency or len(base_currency) > _MAX_CURRENCY_CODE_LENGTH:
            raise ValueError(f"invalid base currency: {base_currency!r}")
        if not target_currencies:
            raise ValueError("target_currencies must not be empty")
        for currency in target_currencies:
            if not currency or len(currency) > _MAX_CURRENCY_CODE_LENGTH:
                raise ValueError(f"invalid target currency: {currency!r}")
        self._base_currency = base_currency
        self._target_currencies = target_currencies
        self._client = client
        self._request_timeout_seconds = request_timeout_seconds

    async def fetch(self) -> ExchangeRateSnapshot:
        params = {
            "from": self._base_currency,
            "to": ",".join(self._target_currencies),
        }
        try:
            if self._client is not None:
                response = await self._client.get(
                    _FRANKFURTER_LATEST_URL,
                    params=params,
                    timeout=self._request_timeout_seconds,
                )
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        _FRANKFURTER_LATEST_URL,
                        params=params,
                        timeout=self._request_timeout_seconds,
                    )
        except httpx.HTTPError as error:
            raise ExchangeRateFetchFailedError(str(error)) from error

        if response.status_code != 200:
            raise ExchangeRateFetchFailedError(f"HTTP {response.status_code}")

        try:
            payload = cast(dict[str, object], response.json())
        except ValueError as error:
            raise ExchangeRateFetchFailedError(f"malformed JSON: {error}") from error

        as_of_date = payload.get("date")
        rates_value = payload.get("rates")
        if not isinstance(as_of_date, str) or not isinstance(rates_value, dict):
            raise ExchangeRateFetchFailedError("malformed response shape")
        rates_map = cast(dict[str, object], rates_value)

        rates: list[CurrencyRate] = []
        for currency in self._target_currencies:
            rate_value = rates_map.get(currency)
            if not isinstance(rate_value, int | float):
                continue
            rates.append(CurrencyRate(currency=currency, rate=float(rate_value)))
        if not rates:
            raise ExchangeRateFetchFailedError("no watchlist currencies present in response")
        return ExchangeRateSnapshot(
            base_currency=self._base_currency, as_of_date=as_of_date, rates=tuple(rates)
        )
