"""Component tests for `PrincipalDeveloperAgent.run_cycle` (ADR-0026,
ADR-0031) -- the kill switch, daily budget, PR fetch, AI proposal, and
per-action dispatch/audit flow, all against fakes. Same shape as the
other two autonomous roles' component test suites; no real GitHub/AI
Router/DB call is ever made in this repository's default test suite.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from ai_platform.agents.principal_developer_agent.agent import PrincipalDeveloperAgent
from ai_platform.agents.principal_developer_agent.errors import (
    PullRequestFetchFailedError,
    SourceControlActionFailedError,
)
from ai_platform.agents.principal_developer_agent.source_control import PullRequestSnapshot
from ai_platform.ports.ai_router import (
    AICompletionFailureCode,
    AICompletionRequest,
    AICompletionResult,
    AICompletionUsage,
)
from ai_platform.ports.persistence.autonomous import (
    AutonomousActionRecord,
    DailyBudgetStatus,
    RoleBudgetRecord,
)

_PULL_REQUESTS = (PullRequestSnapshot(number=1, title="Fix bug", mergeable_state="clean"),)

_ONE_MERGE_ACTION_JSON = json.dumps(
    [{"action": "merge", "pull_number": "1", "rationale": "All checks pass."}]
)


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


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
class FakeSourceControl:
    pull_requests: tuple[PullRequestSnapshot, ...] = ()
    fetch_failure: PullRequestFetchFailedError | None = None
    action_failures: dict[str, SourceControlActionFailedError] = field(default_factory=dict)
    fetch_calls: int = 0
    request_changes_calls: list[tuple[int, str]] = field(default_factory=list)
    merge_calls: list[int] = field(default_factory=list)

    async def fetch_open_pull_requests(self) -> tuple[PullRequestSnapshot, ...]:
        self.fetch_calls += 1
        if self.fetch_failure is not None:
            raise self.fetch_failure
        return self.pull_requests

    async def request_changes(self, *, pull_number: int, body: str) -> None:
        if "request_changes" in self.action_failures:
            raise self.action_failures["request_changes"]
        self.request_changes_calls.append((pull_number, body))

    async def merge(self, *, pull_number: int) -> None:
        if "merge" in self.action_failures:
            raise self.action_failures["merge"]
        self.merge_calls.append(pull_number)


@dataclass
class RecordedAction:
    agent_deployment_id: str
    role: str
    action_type: str
    target: str
    inputs: dict[str, object]
    result_status: str
    result_detail: str
    occurred_at: datetime


@dataclass
class InMemoryAutonomousState:
    kill_switch_engaged: bool = False
    budgets: dict[tuple[str, date], DailyBudgetStatus] = field(default_factory=dict)
    recorded_actions: list[RecordedAction] = field(default_factory=list)

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
        inputs: Mapping[str, object],
        result_status: str,
        result_detail: str,
        occurred_at: datetime,
    ) -> None:
        self.recorded_actions.append(
            RecordedAction(
                agent_deployment_id=agent_deployment_id,
                role=role,
                action_type=action_type,
                target=target,
                inputs=dict(inputs),
                result_status=result_status,
                result_detail=result_detail,
                occurred_at=occurred_at,
            )
        )

    async def list_role_budgets(self, *, today: date) -> tuple[RoleBudgetRecord, ...]:
        raise NotImplementedError("not exercised by these cycle tests")

    async def list_recent_actions(self, *, limit: int) -> tuple[AutonomousActionRecord, ...]:
        raise NotImplementedError("not exercised by these cycle tests")


def _build_agent(
    *,
    state: InMemoryAutonomousState | None = None,
    ai_router: Any = None,
    source_control: FakeSourceControl | None = None,
    max_actions_per_day: int = 10,
    max_spend_cents_per_day: int = 100,
) -> tuple[PrincipalDeveloperAgent, InMemoryAutonomousState, FakeSourceControl]:
    state = state or InMemoryAutonomousState()
    source_control = source_control or FakeSourceControl(pull_requests=_PULL_REQUESTS)
    agent = PrincipalDeveloperAgent(
        agent_deployment_id="principal-developer-agent",
        state=state,
        source_control=source_control,
        ai_router=ai_router if ai_router is not None else _UnreachableAIRouter(),
        max_output_tokens=256,
        provider_deadline_seconds=20.0,
        max_actions_per_day=max_actions_per_day,
        max_spend_cents_per_day=max_spend_cents_per_day,
    )
    return agent, state, source_control


def test_kill_switch_engaged_skips_the_whole_cycle() -> None:
    state = InMemoryAutonomousState(kill_switch_engaged=True)
    agent, state, source_control = _build_agent(state=state)

    _run(agent.run_cycle())

    assert source_control.fetch_calls == 0
    assert state.recorded_actions == []


def test_budget_exhausted_by_action_count_skips_the_cycle() -> None:
    state = InMemoryAutonomousState()
    today = datetime.now().date()
    state.budgets[("principal-developer", today)] = DailyBudgetStatus(
        actions_used=10, spend_cents_used=0
    )
    agent, state, source_control = _build_agent(state=state, max_actions_per_day=10)

    _run(agent.run_cycle())

    assert source_control.fetch_calls == 0


def test_budget_exhausted_by_spend_skips_the_cycle() -> None:
    state = InMemoryAutonomousState()
    today = datetime.now().date()
    state.budgets[("principal-developer", today)] = DailyBudgetStatus(
        actions_used=0, spend_cents_used=100
    )
    agent, state, source_control = _build_agent(state=state, max_spend_cents_per_day=100)

    _run(agent.run_cycle())

    assert source_control.fetch_calls == 0


def test_pull_request_fetch_failure_skips_the_ai_call_and_records_nothing() -> None:
    source_control = FakeSourceControl(fetch_failure=PullRequestFetchFailedError("HTTP 401"))
    agent, state, source_control = _build_agent(source_control=source_control)

    _run(agent.run_cycle())

    assert state.recorded_actions == []


def test_happy_path_dispatches_the_proposed_merge_and_records_success() -> None:
    router = FakeAIRouter(
        result=AICompletionResult(
            output_text=_ONE_MERGE_ACTION_JSON,
            usage=AICompletionUsage(
                provider="anthropic",
                model="claude-haiku-4-5",
                input_tokens=500,
                output_tokens=100,
                latency_seconds=0.5,
            ),
        )
    )
    agent, state, source_control = _build_agent(ai_router=router)

    _run(agent.run_cycle())

    assert source_control.merge_calls == [1]
    assert len(state.recorded_actions) == 1
    recorded = state.recorded_actions[0]
    assert recorded.action_type == "merge"
    assert recorded.target == "1"
    assert recorded.result_status == "SUCCEEDED"
    assert recorded.agent_deployment_id == "principal-developer-agent"
    assert recorded.role == "principal-developer"
    today = datetime.now().date()
    assert state.budgets[("principal-developer", today)].actions_used == 1


def test_empty_proposal_dispatches_nothing() -> None:
    router = FakeAIRouter(
        result=AICompletionResult(
            output_text="[]",
            usage=AICompletionUsage(
                provider="anthropic",
                model="m",
                input_tokens=1,
                output_tokens=1,
                latency_seconds=0.1,
            ),
        )
    )
    agent, state, source_control = _build_agent(ai_router=router)

    _run(agent.run_cycle())

    assert state.recorded_actions == []
    assert source_control.merge_calls == []


def test_malformed_ai_response_dispatches_nothing() -> None:
    router = FakeAIRouter(
        result=AICompletionResult(
            output_text="I reviewed the PRs and think...",
            usage=AICompletionUsage(
                provider="anthropic",
                model="m",
                input_tokens=1,
                output_tokens=1,
                latency_seconds=0.1,
            ),
        )
    )
    agent, state, _source_control = _build_agent(ai_router=router)

    _run(agent.run_cycle())

    assert state.recorded_actions == []


def test_ai_router_classified_failure_dispatches_nothing() -> None:
    router = FakeAIRouter(
        result=AICompletionResult(failure_code=AICompletionFailureCode.ALL_PROVIDERS_EXHAUSTED)
    )
    agent, _state, _source_control = _build_agent(ai_router=router)

    _run(agent.run_cycle())


def test_merge_refused_by_the_toctou_recheck_is_recorded_as_failed() -> None:
    """The fake's `merge()` simulates `source_control.py`'s own TOCTOU
    re-check refusing a PR that is no longer clean -- from `agent.py`'s
    point of view this looks like any other action failure."""
    router = FakeAIRouter(
        result=AICompletionResult(
            output_text=_ONE_MERGE_ACTION_JSON,
            usage=AICompletionUsage(
                provider="anthropic",
                model="claude-haiku-4-5",
                input_tokens=500,
                output_tokens=100,
                latency_seconds=0.5,
            ),
        )
    )
    source_control = FakeSourceControl(
        pull_requests=_PULL_REQUESTS,
        action_failures={"merge": SourceControlActionFailedError("merge", "no longer mergeable")},
    )
    agent, state, source_control = _build_agent(ai_router=router, source_control=source_control)

    _run(agent.run_cycle())

    assert source_control.merge_calls == []
    assert len(state.recorded_actions) == 1
    assert state.recorded_actions[0].result_status == "FAILED"


def test_one_action_failure_does_not_block_the_next_actions_dispatch() -> None:
    raw = json.dumps(
        [
            {"action": "merge", "pull_number": "1", "rationale": "a"},
            {
                "action": "request_changes",
                "pull_number": "2",
                "body": "Needs work",
                "rationale": "b",
            },
        ]
    )
    router = FakeAIRouter(
        result=AICompletionResult(
            output_text=raw,
            usage=AICompletionUsage(
                provider="anthropic",
                model="claude-haiku-4-5",
                input_tokens=500,
                output_tokens=100,
                latency_seconds=0.5,
            ),
        )
    )
    source_control = FakeSourceControl(
        pull_requests=_PULL_REQUESTS,
        action_failures={"merge": SourceControlActionFailedError("merge", "boom")},
    )
    agent, state, source_control = _build_agent(ai_router=router, source_control=source_control)

    _run(agent.run_cycle())

    assert source_control.request_changes_calls == [(2, "Needs work")]
    assert [action.result_status for action in state.recorded_actions] == ["FAILED", "SUCCEEDED"]
