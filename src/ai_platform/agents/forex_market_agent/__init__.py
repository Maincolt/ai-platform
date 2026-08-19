"""`forex-market-agent` (ADR-0036): a read-only, action-free autonomous
role watching a configured foreign-exchange watchlist.

Deliberately independent of `crypto_market_agent` (ADR-0036 Decision 3):
no shared base class or module, even though the two roles have a
similar broad shape."""
