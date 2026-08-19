"""Forex Market Agent domain errors (ADR-0036).

Deliberately not imported from `crypto_market_agent.errors` (ADR-0036
Decision 3) -- structurally similar, independently defined.
"""


class ForexMarketAgentError(Exception):
    """Base class for Forex Market Agent domain errors."""


class ExchangeRateFetchFailedError(ForexMarketAgentError):
    """The read-only exchange-rate fetch failed (HTTP error, timeout, or
    malformed response shape). Raised before any AI Router call is
    attempted this cycle."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"forex market data fetch failed: {reason}")
