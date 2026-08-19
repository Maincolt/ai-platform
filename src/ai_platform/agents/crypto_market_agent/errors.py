"""Crypto Market Agent domain errors (ADR-0035).

Like `scrum_master_agent`, this role never consumes an `ExecuteTask`
command, so none of the standard `ExecuteTask`-lifecycle errors apply.
Its one failure mode is the read-side price fetch.
"""


class CryptoMarketAgentError(Exception):
    """Base class for Crypto Market Agent domain errors."""


class MarketDataFetchFailedError(CryptoMarketAgentError):
    """The read-only price fetch failed (HTTP error, timeout, or
    malformed response shape). Raised before any AI Router call is
    attempted this cycle."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"crypto market data fetch failed: {reason}")
