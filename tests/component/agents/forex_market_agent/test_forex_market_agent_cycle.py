"""Component tests for `ForexMarketAgent.run_cycle` (ADR-0036, ADR-0038)
-- same coverage as `crypto_market_agent`'s equivalent test, a fully
independent test file per ADR-0036 Decision 3's no-shared-code
instruction, not a shared fixture module. No real Frankfurter/AI
Router/DB call is ever made in this repository's default test suite.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from ai_platform.agents.forex_market_agent.agent import ForexMarketAgent
from ai_platform.agents.forex_market_agent.client import CurrencyRate, ExchangeRateSnapshot
from ai_platform.ports.ai_router import AICompletionRequest, AICompletionResult, AICompletionUsage
from ai_platform.ports.persistence.autonomous import (
    AutonomousActionRecord,
    DailyBudgetStatus,
    RoleBudgetRecord,
)
from ai_platform.ports.persistence.market_history import FindingRecord, PriceObservation


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


_SNAPSHOT = ExchangeRateSnapshot(
    base_currency="EUR",
    as_of_date="2026-08-19",
    rates=(CurrencyRate(currency="USD", rate=1.09), CurrencyRate(currency="GBP", rate=0.86)),
)

_ONE_FINDING_JSON = json.dumps(
    [{"pair": "EUR/USD", "summary": "Approaching parity.", "severity": "medium"}]
)


@dataclass
class FakeAIRouter:
    result: AICompletionResult
    calls: list[AICompletionRequest] = field(default_factory=list)

    async def complete(self, request: AICompletionRequest) -> AICompletionResult:
        self.calls.append(request)
        return self.result


class _UnreachableAIRouter:
    async def complete(self, request: AICompletionRequest) -> AICompletionResult:
        del request
        raise AssertionError("The AI Router must not be called on this path")


@dataclass
class FakeExchangeRates:
    snapshot: ExchangeRateSnapshot

    async def fetch(self) -> ExchangeRateSnapshot:
        return self.snapshot


@dataclass
class InMemoryAutonomousState:
    kill_switch_engaged: bool = False
    budgets: dict[tuple[str, date], DailyBudgetStatus] = field(default_factory=dict)
    recorded_actions: list[tuple[str, str, str]] = field(default_factory=list)

    async def is_kill_switch_engaged(self) -> bool:
        return self.kill_switch_engaged

    async def get_daily_budget(self, *, role: str, today: date) -> DailyBudgetStatus:
        return self.budgets.get(
            (role, today), DailyBudgetStatus(actions_used=0, spend_cents_used=0)
        )

    async def record_budget_usage(
        self, *, role: str, today: date, actions: int, spend_cents: int
    ) -> None:
        current = self.budgets.get(
            (role, today), DailyBudgetStatus(actions_used=0, spend_cents_used=0)
        )
        self.budgets[(role, today)] = DailyBudgetStatus(
            actions_used=current.actions_used + actions,
            spend_cents_used=current.spend_cents_used + spend_cents,
        )

    async def record_action(
        self,
        *,
        agent_deployment_id: str,
        role: str,
        action_type: str,
        target: str,
        inputs: object,
        result_status: str,
        result_detail: str,
        occurred_at: datetime,
    ) -> None:
        del agent_deployment_id, inputs, result_status, result_detail, occurred_at
        self.recorded_actions.append((role, action_type, target))

    async def list_role_budgets(self, *, today: date) -> tuple[RoleBudgetRecord, ...]:
        del today
        return ()

    async def list_recent_actions(self, *, limit: int) -> tuple[AutonomousActionRecord, ...]:
        del limit
        return ()


@dataclass
class InMemoryMarketHistory:
    recorded_prices: list[tuple[str, str, float]] = field(default_factory=list)
    recorded_findings: list[tuple[str, str, str, str]] = field(default_factory=list)

    async def record_price_observation(
        self,
        *,
        role: str,
        symbol: str,
        price: float,
        change_24h_percent: float | None,
        observed_at: datetime,
    ) -> None:
        del change_24h_percent, observed_at
        self.recorded_prices.append((role, symbol, price))

    async def record_finding(
        self,
        *,
        role: str,
        symbol: str,
        summary: str,
        severity: str,
        observed_at: datetime,
    ) -> None:
        del observed_at
        self.recorded_findings.append((role, symbol, summary, severity))

    async def list_recent_prices(
        self, *, role: str, symbol: str, since: datetime
    ) -> tuple[PriceObservation, ...]:
        del role, symbol, since
        return ()

    async def list_recent_findings(
        self, *, role: str, since: datetime
    ) -> tuple[FindingRecord, ...]:
        del role, since
        return ()


def _agent(
    *,
    state: InMemoryAutonomousState,
    market_history: InMemoryMarketHistory,
    exchange_rates: FakeExchangeRates,
    ai_router: FakeAIRouter | _UnreachableAIRouter,
) -> ForexMarketAgent:
    return ForexMarketAgent(
        agent_deployment_id="forex-market-agent-1",
        state=state,
        market_history=market_history,
        exchange_rates=exchange_rates,
        ai_router=ai_router,
        max_output_tokens=512,
        provider_deadline_seconds=20.0,
        max_spend_cents_per_day=100,
    )


def test_kill_switch_skips_the_cycle_before_any_fetch() -> None:
    state = InMemoryAutonomousState(kill_switch_engaged=True)
    market_history = InMemoryMarketHistory()
    agent = _agent(
        state=state,
        market_history=market_history,
        exchange_rates=FakeExchangeRates(_SNAPSHOT),
        ai_router=_UnreachableAIRouter(),
    )

    _run(agent.run_cycle())

    assert market_history.recorded_prices == []


def test_successful_cycle_records_every_rate_and_each_finding_twice() -> None:
    state = InMemoryAutonomousState()
    market_history = InMemoryMarketHistory()
    ai_router = FakeAIRouter(
        result=AICompletionResult(
            output_text=_ONE_FINDING_JSON,
            usage=AICompletionUsage(
                provider="anthropic",
                model="claude-haiku-4-5",
                input_tokens=100,
                output_tokens=20,
                latency_seconds=0.5,
            ),
            failure_code=None,
        )
    )
    agent = _agent(
        state=state,
        market_history=market_history,
        exchange_rates=FakeExchangeRates(_SNAPSHOT),
        ai_router=ai_router,
    )

    _run(agent.run_cycle())

    assert market_history.recorded_prices == [
        ("forex-market", "EUR/USD", 1.09),
        ("forex-market", "EUR/GBP", 0.86),
    ]
    assert market_history.recorded_findings == [
        ("forex-market", "EUR/USD", "Approaching parity.", "medium")
    ]
    assert state.recorded_actions == [("forex-market", "record_finding", "EUR/USD")]


def test_finding_referencing_a_pair_outside_the_watchlist_is_rejected() -> None:
    state = InMemoryAutonomousState()
    market_history = InMemoryMarketHistory()
    ai_router = FakeAIRouter(
        result=AICompletionResult(
            output_text=json.dumps(
                [{"pair": "EUR/JPY", "summary": "Notable move.", "severity": "low"}]
            ),
            usage=AICompletionUsage(
                provider="anthropic",
                model="claude-haiku-4-5",
                input_tokens=100,
                output_tokens=20,
                latency_seconds=0.5,
            ),
            failure_code=None,
        )
    )
    agent = _agent(
        state=state,
        market_history=market_history,
        exchange_rates=FakeExchangeRates(_SNAPSHOT),
        ai_router=ai_router,
    )

    _run(agent.run_cycle())

    assert len(market_history.recorded_prices) == 2
    assert market_history.recorded_findings == []
    assert state.recorded_actions == []
