"""The Forex Market Agent's cycle logic (ADR-0036).

Same broad shape as `crypto_market_agent.agent` (`PeriodicService`-driven,
fetch, one AI Router call, record findings, no dispatch step, no
external write action of any kind) but a fully independent
implementation, per ADR-0036 Decision 3 -- no shared base class or
module between the two roles.

ECB reference rates (Frankfurter's data source) update once per
business day, not continuously (ADR-0036 Decision 1): the prompt is
worded to expect "no change since last observation" as a normal, common
outcome, not something to manufacture commentary around.
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import cast

from ai_platform.agents._autonomous_shared import estimate_spend_cents, strip_markdown_json_fence
from ai_platform.agents.forex_market_agent.client import ExchangeRatePort, ExchangeRateSnapshot
from ai_platform.agents.forex_market_agent.errors import ExchangeRateFetchFailedError
from ai_platform.ports.ai_router import AICompletionRequest, AIRouterPort, DataClassification
from ai_platform.ports.persistence.autonomous import AutonomousStatePort

logger = logging.getLogger(__name__)

_ROLE = "forex-market"
_VALID_SEVERITIES = frozenset({"low", "medium", "high"})
_MAX_FINDING_SUMMARY_LENGTH = 2000
_MAX_FINDING_PAIR_LENGTH = 20
_MAX_FINDINGS = 50
_REQUIRED_FINDING_KEYS = frozenset({"pair", "summary", "severity"})


def _build_findings_prompt(snapshot: ExchangeRateSnapshot) -> str:
    rate_lines = "\n".join(
        f"- {snapshot.base_currency}/{rate.currency}: {rate.rate:.4f}"
        for rate in snapshot.rates
    )
    return (
        "You are a foreign-exchange market observer. Review the "
        "following current ECB reference rates (updated once per ECB "
        "business day, not continuously -- unchanged figures since your "
        "last observation are normal, not a data error) and respond "
        "with ONLY a JSON array (no prose, no markdown fences) of "
        'finding objects. Each object must have exactly these keys: '
        '"pair" (string, exactly as shown below, e.g. '
        f'"{snapshot.base_currency}/USD"), "summary" (string, one '
        "sentence noting a genuinely notable level, threshold, or "
        'trend), and "severity" (one of "low", "medium", "high" -- how '
        "much attention this deserves). Only include a finding for a "
        "pair if there is something worth noting; return an empty array "
        "[] if nothing stands out, which will often be the case given "
        "the daily update cadence. Never recommend a trade or hedging "
        "action -- observation only."
        f"\n\nAs of {snapshot.as_of_date}, base currency "
        f"{snapshot.base_currency}:\n{rate_lines}"
    )


def _parse_findings(output_text: str) -> list[dict[str, str]] | None:
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
        pair_value = item["pair"]
        summary_value = item["summary"]
        severity_value = item["severity"]
        if (
            not isinstance(pair_value, str)
            or not pair_value
            or len(pair_value) > _MAX_FINDING_PAIR_LENGTH
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
                "pair": pair_value,
                "summary": summary_value,
                "severity": cast(str, severity_value),
            }
        )
    return findings


class ForexMarketAgent:
    def __init__(
        self,
        *,
        agent_deployment_id: str,
        state: AutonomousStatePort,
        exchange_rates: ExchangeRatePort,
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
        self._exchange_rates = exchange_rates
        self._ai_router = ai_router
        self._max_output_tokens = max_output_tokens
        self._provider_deadline_seconds = provider_deadline_seconds
        self._max_spend_cents_per_day = max_spend_cents_per_day

    async def run_cycle(self) -> None:
        if await self._state.is_kill_switch_engaged():
            logger.info("forex-market-agent: kill switch engaged, skipping cycle")
            return

        now = datetime.now(UTC)
        today = now.date()
        budget = await self._state.get_daily_budget(role=_ROLE, today=today)
        # ADR-0036 Decision 4 (mirroring ADR-0035 Decision 5): no action
        # to rate-limit -- only the estimated-spend cap gates this role.
        if budget.spend_cents_used >= self._max_spend_cents_per_day:
            logger.info("forex-market-agent: daily spend cap exhausted, skipping cycle")
            return

        try:
            snapshot = await self._exchange_rates.fetch()
        except ExchangeRateFetchFailedError as error:
            logger.warning("forex-market-agent: exchange-rate fetch failed: %s", error.reason)
            return

        completion = await self._ai_router.complete(
            AICompletionRequest(
                prompt=_build_findings_prompt(snapshot),
                max_output_tokens=self._max_output_tokens,
                idempotency_key=f"forex-market-{now.isoformat()}",
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
            logger.warning("forex-market-agent: AI Router returned a classified failure")
            return

        findings = _parse_findings(completion.output_text)
        if findings is None:
            logger.warning("forex-market-agent: findings response did not parse")
            return

        for finding in findings:
            await self._state.record_action(
                agent_deployment_id=self._agent_deployment_id,
                role=_ROLE,
                action_type="record_finding",
                target=finding["pair"],
                inputs={"summary": finding["summary"], "severity": finding["severity"]},
                result_status="SUCCEEDED",
                result_detail=finding["summary"],
                occurred_at=now,
            )
