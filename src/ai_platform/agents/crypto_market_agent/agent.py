"""The Crypto Market Agent's cycle logic (ADR-0035, ADR-0038).

Like `scrum_master_agent`, `run_cycle()` is the operation a
`PeriodicService` invokes on a fixed interval, not a reaction to one
`ExecuteTask` command. Unlike every prior autonomous role, there is no
propose-then-dispatch step: this role never acts on anything external.
Each cycle: check the kill switch, check today's spend, fetch the
watchlist, make one AI Router call producing findings, strictly parse/
validate them, then record every fetched price (ADR-0038, structured
history for `coinbase-trader-agent`/`fxcm-trader-agent` to read later)
and each finding as one `agent.autonomous_actions` row
(`action_type="record_finding"`) plus one `agent.market_findings` row
-- those writes are the cycle's only side effect, always local, never a
call back out to any external system.
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import cast

from ai_platform.agents._autonomous_shared import estimate_spend_cents, strip_markdown_json_fence
from ai_platform.agents.crypto_market_agent.client import (
    MarketDataPort,
    MarketSnapshot,
    SymbolPrice,
)
from ai_platform.agents.crypto_market_agent.errors import MarketDataFetchFailedError
from ai_platform.ports.ai_router import AICompletionRequest, AIRouterPort, DataClassification
from ai_platform.ports.persistence.autonomous import AutonomousStatePort
from ai_platform.ports.persistence.market_history import MarketHistoryPort

logger = logging.getLogger(__name__)

_ROLE = "crypto-market"
_VALID_SEVERITIES = frozenset({"low", "medium", "high"})
_MAX_FINDING_SUMMARY_LENGTH = 2000
_MAX_FINDING_SYMBOL_LENGTH = 20
_MAX_FINDINGS = 50
_REQUIRED_FINDING_KEYS = frozenset({"symbol", "summary", "severity"})


def _build_findings_prompt(snapshot: MarketSnapshot) -> str:
    price_lines = "\n".join(
        f"- {price.symbol}: ${price.price_usd:,.2f}"
        + (
            f" ({price.change_24h_percent:+.2f}% 24h)"
            if price.change_24h_percent is not None
            else " (24h change unavailable)"
        )
        for price in snapshot.prices
    )
    return (
        "You are a cryptocurrency market observer. Review the following "
        "current prices for a fixed watchlist and respond with ONLY a "
        "JSON array (no prose, no markdown fences) of finding objects. "
        'Each object must have exactly these keys: "symbol" (string, the '
        'trading-pair symbol exactly as shown below), "summary" (string, '
        "one sentence noting a genuinely notable movement, trend, or lack "
        'of one), and "severity" (one of "low", "medium", "high" -- '
        "how much attention this movement deserves, not a judgment on "
        "the asset itself). Only include a finding for a symbol if there "
        "is something worth noting; return an empty array [] if nothing "
        "stands out. Never recommend buying, selling, or any trading "
        "action -- observation only."
        f"\n\nWatchlist prices:\n{price_lines}"
    )


def _parse_findings(output_text: str) -> list[dict[str, str]] | None:
    """Same strict-parse discipline as every prior AI-backed
    capability's finding list (see `technical_review_agent.agent
    ._parse_findings`): any shape/content mismatch anywhere in the
    batch means "no findings this cycle," never a partial acceptance."""
    try:
        parsed: object = json.loads(strip_markdown_json_fence(output_text))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list):
        return None
    candidates = cast(list[object], parsed)
    if len(candidates) > _MAX_FINDINGS:
        return None

    findings: list[dict[str, str]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            return None
        item = cast(dict[str, object], candidate)
        if frozenset(item.keys()) != _REQUIRED_FINDING_KEYS:
            return None
        symbol_value = item["symbol"]
        summary_value = item["summary"]
        severity_value = item["severity"]
        if (
            not isinstance(symbol_value, str)
            or not symbol_value
            or len(symbol_value) > _MAX_FINDING_SYMBOL_LENGTH
        ):
            return None
        if (
            not isinstance(summary_value, str)
            or not summary_value
            or len(summary_value) > _MAX_FINDING_SUMMARY_LENGTH
        ):
            return None
        if severity_value not in _VALID_SEVERITIES:
            return None
        findings.append(
            {
                "symbol": symbol_value,
                "summary": summary_value,
                "severity": cast(str, severity_value),
            }
        )
    return findings


class CryptoMarketAgent:
    def __init__(
        self,
        *,
        agent_deployment_id: str,
        state: AutonomousStatePort,
        market_history: MarketHistoryPort,
        market_data: MarketDataPort,
        ai_router: AIRouterPort,
        max_output_tokens: int,
        provider_deadline_seconds: float,
        max_spend_cents_per_day: int,
    ) -> None:
        if max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        if provider_deadline_seconds <= 0:
            raise ValueError("provider_deadline_seconds must be positive")
        if max_spend_cents_per_day <= 0:
            raise ValueError("max_spend_cents_per_day must be positive")
        self._agent_deployment_id = agent_deployment_id
        self._state = state
        self._market_history = market_history
        self._market_data = market_data
        self._ai_router = ai_router
        self._max_output_tokens = max_output_tokens
        self._provider_deadline_seconds = provider_deadline_seconds
        self._max_spend_cents_per_day = max_spend_cents_per_day

    async def run_cycle(self) -> None:
        if await self._state.is_kill_switch_engaged():
            logger.info("crypto-market-agent: kill switch engaged, skipping cycle")
            return

        now = datetime.now(UTC)
        today = now.date()
        budget = await self._state.get_daily_budget(role=_ROLE, today=today)
        # ADR-0035 Decision 5: this role has no action to rate-limit --
        # only the estimated-spend cap gates it, not an action count.
        if budget.spend_cents_used >= self._max_spend_cents_per_day:
            logger.info("crypto-market-agent: daily spend cap exhausted, skipping cycle")
            return

        try:
            snapshot = await self._market_data.fetch()
        except MarketDataFetchFailedError as error:
            logger.warning("crypto-market-agent: price fetch failed: %s", error.reason)
            return

        for price in snapshot.prices:
            await self._record_price_observation_best_effort(price=price, now=now)

        completion = await self._ai_router.complete(
            AICompletionRequest(
                prompt=_build_findings_prompt(snapshot),
                max_output_tokens=self._max_output_tokens,
                idempotency_key=f"crypto-market-{now.isoformat()}",
                deadline=now + timedelta(seconds=self._provider_deadline_seconds),
                classification=DataClassification.NO_SPECIAL_HANDLING,
            )
        )
        if completion.usage is not None:
            spend_cents = estimate_spend_cents(completion.usage)
            if spend_cents:
                await self._state.record_budget_usage(
                    role=_ROLE, today=today, actions=0, spend_cents=spend_cents
                )

        if completion.output_text is None:
            logger.warning("crypto-market-agent: AI Router returned a classified failure")
            return

        findings = _parse_findings(completion.output_text)
        if findings is None:
            logger.warning("crypto-market-agent: findings response did not parse")
            return

        watchlist_symbols = {price.symbol for price in snapshot.prices}
        if any(finding["symbol"] not in watchlist_symbols for finding in findings):
            logger.warning(
                "crypto-market-agent: findings referenced a symbol outside the fetched watchlist"
            )
            return

        for finding in findings:
            await self._state.record_action(
                agent_deployment_id=self._agent_deployment_id,
                role=_ROLE,
                action_type="record_finding",
                target=finding["symbol"],
                inputs={"summary": finding["summary"], "severity": finding["severity"]},
                result_status="SUCCEEDED",
                result_detail=finding["summary"],
                occurred_at=now,
            )
            await self._record_finding_history_best_effort(finding=finding, now=now)

    async def _record_price_observation_best_effort(
        self, *, price: SymbolPrice, now: datetime
    ) -> None:
        # ADR-0038: purely additive/non-critical relative to
        # `agent.autonomous_actions` -- unlike that call, a transient
        # failure here must never propagate and kill `PeriodicService`'s
        # loop (it has no retry of its own, so an uncaught exception
        # here would silently end every future cycle, including the
        # audit-critical `record_action` path).
        try:
            await self._market_history.record_price_observation(
                role=_ROLE,
                symbol=price.symbol,
                price=price.price_usd,
                change_24h_percent=price.change_24h_percent,
                observed_at=now,
            )
        except Exception:  # noqa: BLE001 - deliberately broad, see comment above
            logger.warning(
                "crypto-market-agent: failed to record price observation for %s",
                price.symbol,
                exc_info=True,
            )

    async def _record_finding_history_best_effort(
        self, *, finding: dict[str, str], now: datetime
    ) -> None:
        try:
            await self._market_history.record_finding(
                role=_ROLE,
                symbol=finding["symbol"],
                summary=finding["summary"],
                severity=finding["severity"],
                observed_at=now,
            )
        except Exception:  # noqa: BLE001 - deliberately broad, see comment above
            logger.warning(
                "crypto-market-agent: failed to record finding history for %s",
                finding["symbol"],
                exc_info=True,
            )
