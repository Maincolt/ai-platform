"""Component tests for `CryptoMarketAgent.run_cycle` (ADR-0035, ADR-0038)
-- the kill switch, daily spend cap, price-observation/finding
persistence, and off-watchlist rejection, all against fakes. No real
Binance/AI Router/DB call is ever made in this repository's default
test suite.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from ai_platform.agents.crypto_market_agent.agent import CryptoMarketAgent
from ai_platform.agents.crypto_market_agent.client import MarketSnapshot, SymbolPrice
from ai_platform.ports.ai_router import AICompletionRequest, AICompletionResult, AICompletionUsage
from ai_platform.ports.persistence.autonomous import (
    AutonomousActionRecord,
    DailyBudgetStatus,
    RoleBudgetRecord,
)
from ai_platform.ports.persistence.market_history import FindingRecord, PriceObservation


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


_SNAPSHOT = MarketSnapshot(
    prices=(
        SymbolPrice(symbol="BTCUSDT", price_usd=65000.0, change_24h_percent=3.2),
        SymbolPrice(symbol="ETHUSDT", price_usd=3200.0, change_24h_percent=-1.1),
    )
)

_ONE_FINDING_JSON = json.dumps(
    [{"symbol": "BTCUSDT", "summary": "Up 3.2% in 24h.", "severity": "medium"}]
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
class FakeMarketData:
    snapshot: MarketSnapshot

    async def fetch(self) -> MarketSnapshot:
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
    market_data: FakeMarketData,
    ai_router: FakeAIRouter | _UnreachableAIRouter,
) -> CryptoMarketAgent:
    return CryptoMarketAgent(
        agent_deployment_id="crypto-market-agent-1",
        state=state,
        market_history=market_history,
        market_data=market_data,
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
        market_data=FakeMarketData(_SNAPSHOT),
        ai_router=_UnreachableAIRouter(),
    )

    _run(agent.run_cycle())

    assert market_history.recorded_prices == []


def test_exhausted_daily_spend_skips_the_cycle() -> None:
    today = datetime.now().astimezone().date()
    state = InMemoryAutonomousState(
        budgets={("crypto-market", today): DailyBudgetStatus(actions_used=0, spend_cents_used=100)}
    )
    market_history = InMemoryMarketHistory()
    agent = _agent(
        state=state,
        market_history=market_history,
        market_data=FakeMarketData(_SNAPSHOT),
        ai_router=_UnreachableAIRouter(),
    )

    _run(agent.run_cycle())

    assert market_history.recorded_prices == []


def test_successful_cycle_records_every_price_and_each_finding_twice() -> None:
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
        market_data=FakeMarketData(_SNAPSHOT),
        ai_router=ai_router,
    )

    _run(agent.run_cycle())

    # Every fetched price is recorded, whether or not it produced a finding.
    assert market_history.recorded_prices == [
        ("crypto-market", "BTCUSDT", 65000.0),
        ("crypto-market", "ETHUSDT", 3200.0),
    ]
    # The one finding is recorded both in the structured history table
    # (ADR-0038) and the existing generic audit log (ADR-0026).
    assert market_history.recorded_findings == [
        ("crypto-market", "BTCUSDT", "Up 3.2% in 24h.", "medium")
    ]
    assert state.recorded_actions == [("crypto-market", "record_finding", "BTCUSDT")]


def test_finding_referencing_a_symbol_outside_the_watchlist_is_rejected() -> None:
    state = InMemoryAutonomousState()
    market_history = InMemoryMarketHistory()
    ai_router = FakeAIRouter(
        result=AICompletionResult(
            output_text=json.dumps(
                [{"symbol": "DOGEUSDT", "summary": "Up 40%.", "severity": "high"}]
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
        market_data=FakeMarketData(_SNAPSHOT),
        ai_router=ai_router,
    )

    _run(agent.run_cycle())

    # Prices are still recorded (fetched before the AI call); no finding is.
    assert len(market_history.recorded_prices) == 2
    assert market_history.recorded_findings == []
    assert state.recorded_actions == []
