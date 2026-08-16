"""Component tests for `ScrumMasterAgent.run_cycle` (ADR-0026, ADR-0028) --
the kill switch, daily budget, board fetch, AI proposal, and per-action
dispatch/audit flow, all against fakes. No real GitHub/AI Router/DB call
is ever made in this repository's default test suite.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from ai_platform.agents.scrum_master_agent.agent import ScrumMasterAgent
from ai_platform.agents.scrum_master_agent.errors import (
    ProjectBoardFetchFailedError,
    TrackerActionFailedError,
)
from ai_platform.agents.scrum_master_agent.tracker import BoardItem, ProjectBoardSnapshot
from ai_platform.ports.ai_router import (
    AICompletionFailureCode,
    AICompletionRequest,
    AICompletionResult,
    AICompletionUsage,
)
from ai_platform.ports.persistence.autonomous import DailyBudgetStatus

_SNAPSHOT = ProjectBoardSnapshot(
    title="Sprint 12",
    items=(BoardItem(item_id="PVTI_1", title="Fix bug", status="Todo", url="https://x/1"),),
)

_ONE_SET_STATUS_ACTION_JSON = json.dumps(
    [
        {
            "action": "set_status",
            "item_id": "PVTI_1",
            "status": "In Progress",
            "rationale": "It has recent activity.",
        }
    ]
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
class FakeProjectTracker:
    snapshot: ProjectBoardSnapshot | None = None
    fetch_failure: ProjectBoardFetchFailedError | None = None
    action_failures: dict[str, TrackerActionFailedError] = field(default_factory=dict)
    fetch_calls: int = 0
    set_status_calls: list[tuple[str, str]] = field(default_factory=list)
    add_comment_calls: list[tuple[str, str]] = field(default_factory=list)
    create_draft_item_calls: list[tuple[str, str]] = field(default_factory=list)

    async def fetch(self) -> ProjectBoardSnapshot:
        self.fetch_calls += 1
        if self.fetch_failure is not None:
            raise self.fetch_failure
        assert self.snapshot is not None
        return self.snapshot

    async def set_status(self, *, item_id: str, status_name: str) -> None:
        if "set_status" in self.action_failures:
            raise self.action_failures["set_status"]
        self.set_status_calls.append((item_id, status_name))

    async def add_comment(self, *, issue_url: str, body: str) -> None:
        if "add_comment" in self.action_failures:
            raise self.action_failures["add_comment"]
        self.add_comment_calls.append((issue_url, body))

    async def create_draft_item(self, *, title: str, body: str) -> None:
        if "create_draft_item" in self.action_failures:
            raise self.action_failures["create_draft_item"]
        self.create_draft_item_calls.append((title, body))


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


def _build_agent(
    *,
    state: InMemoryAutonomousState | None = None,
    ai_router: Any = None,
    tracker: FakeProjectTracker | None = None,
    max_actions_per_day: int = 10,
    max_spend_cents_per_day: int = 100,
) -> tuple[ScrumMasterAgent, InMemoryAutonomousState, FakeProjectTracker]:
    state = state or InMemoryAutonomousState()
    tracker = tracker or FakeProjectTracker(snapshot=_SNAPSHOT)
    agent = ScrumMasterAgent(
        agent_deployment_id="scrum-master-agent",
        state=state,
        project_tracker=tracker,
        ai_router=ai_router if ai_router is not None else _UnreachableAIRouter(),
        max_output_tokens=256,
        max_actions_per_day=max_actions_per_day,
        max_spend_cents_per_day=max_spend_cents_per_day,
    )
    return agent, state, tracker


def test_kill_switch_engaged_skips_the_whole_cycle() -> None:
    state = InMemoryAutonomousState(kill_switch_engaged=True)
    agent, state, tracker = _build_agent(state=state)

    _run(agent.run_cycle())

    assert tracker.fetch_calls == 0
    assert state.recorded_actions == []


def test_budget_exhausted_by_action_count_skips_the_cycle() -> None:
    state = InMemoryAutonomousState()
    today = datetime.now().date()
    state.budgets[("scrum-master", today)] = DailyBudgetStatus(actions_used=10, spend_cents_used=0)
    agent, state, tracker = _build_agent(state=state, max_actions_per_day=10)

    _run(agent.run_cycle())

    assert tracker.fetch_calls == 0


def test_budget_exhausted_by_spend_skips_the_cycle() -> None:
    state = InMemoryAutonomousState()
    today = datetime.now().date()
    state.budgets[("scrum-master", today)] = DailyBudgetStatus(actions_used=0, spend_cents_used=100)
    agent, state, tracker = _build_agent(state=state, max_spend_cents_per_day=100)

    _run(agent.run_cycle())

    assert tracker.fetch_calls == 0


def test_board_fetch_failure_skips_the_ai_call_and_records_nothing() -> None:
    tracker = FakeProjectTracker(fetch_failure=ProjectBoardFetchFailedError("HTTP 401"))
    agent, state, tracker = _build_agent(tracker=tracker)

    _run(agent.run_cycle())

    assert state.recorded_actions == []


def test_happy_path_dispatches_the_proposed_action_and_records_success() -> None:
    router = FakeAIRouter(
        result=AICompletionResult(
            output_text=_ONE_SET_STATUS_ACTION_JSON,
            usage=AICompletionUsage(
                provider="anthropic",
                model="claude-haiku-4-5",
                input_tokens=500,
                output_tokens=100,
                latency_seconds=0.5,
            ),
        )
    )
    agent, state, tracker = _build_agent(ai_router=router)

    _run(agent.run_cycle())

    assert tracker.set_status_calls == [("PVTI_1", "In Progress")]
    assert len(state.recorded_actions) == 1
    recorded = state.recorded_actions[0]
    assert recorded.action_type == "set_status"
    assert recorded.target == "PVTI_1"
    assert recorded.result_status == "SUCCEEDED"
    assert recorded.agent_deployment_id == "scrum-master-agent"
    assert recorded.role == "scrum-master"
    today = datetime.now().date()
    assert state.budgets[("scrum-master", today)].actions_used == 1


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
    agent, state, tracker = _build_agent(ai_router=router)

    _run(agent.run_cycle())

    assert state.recorded_actions == []
    assert tracker.set_status_calls == []


def test_malformed_ai_response_dispatches_nothing() -> None:
    router = FakeAIRouter(
        result=AICompletionResult(
            output_text="here is my plan for the sprint...",
            usage=AICompletionUsage(
                provider="anthropic",
                model="m",
                input_tokens=1,
                output_tokens=1,
                latency_seconds=0.1,
            ),
        )
    )
    agent, state, _tracker = _build_agent(ai_router=router)

    _run(agent.run_cycle())

    assert state.recorded_actions == []


def test_ai_router_classified_failure_dispatches_nothing() -> None:
    router = FakeAIRouter(
        result=AICompletionResult(failure_code=AICompletionFailureCode.ALL_PROVIDERS_EXHAUSTED)
    )
    agent, state, _tracker = _build_agent(ai_router=router)

    _run(agent.run_cycle())

    assert state.recorded_actions == []


def test_a_failed_action_is_recorded_as_failed_not_raised() -> None:
    router = FakeAIRouter(
        result=AICompletionResult(
            output_text=_ONE_SET_STATUS_ACTION_JSON,
            usage=AICompletionUsage(
                provider="anthropic",
                model="m",
                input_tokens=1,
                output_tokens=1,
                latency_seconds=0.1,
            ),
        )
    )
    tracker = FakeProjectTracker(
        snapshot=_SNAPSHOT,
        action_failures={"set_status": TrackerActionFailedError("set_status", "board changed")},
    )
    agent, state, tracker = _build_agent(ai_router=router, tracker=tracker)

    _run(agent.run_cycle())

    assert len(state.recorded_actions) == 1
    assert state.recorded_actions[0].result_status == "FAILED"
    assert "board changed" in state.recorded_actions[0].result_detail


def test_one_failed_action_does_not_block_dispatch_of_the_next() -> None:
    two_actions_json = json.dumps(
        [
            {
                "action": "set_status",
                "item_id": "PVTI_1",
                "status": "In Progress",
                "rationale": "x",
            },
            {
                "action": "create_draft_item",
                "title": "Follow-up task",
                "body": "y",
                "rationale": "z",
            },
        ]
    )
    router = FakeAIRouter(
        result=AICompletionResult(
            output_text=two_actions_json,
            usage=AICompletionUsage(
                provider="anthropic",
                model="m",
                input_tokens=1,
                output_tokens=1,
                latency_seconds=0.1,
            ),
        )
    )
    tracker = FakeProjectTracker(
        snapshot=_SNAPSHOT,
        action_failures={"set_status": TrackerActionFailedError("set_status", "boom")},
    )
    agent, state, tracker = _build_agent(ai_router=router, tracker=tracker)

    _run(agent.run_cycle())

    assert len(state.recorded_actions) == 2
    assert state.recorded_actions[0].result_status == "FAILED"
    assert state.recorded_actions[1].result_status == "SUCCEEDED"
    assert tracker.create_draft_item_calls == [("Follow-up task", "y")]


def test_dispatch_stops_once_the_daily_action_cap_is_reached_mid_cycle() -> None:
    two_actions_json = json.dumps(
        [
            {
                "action": "set_status",
                "item_id": "PVTI_1",
                "status": "In Progress",
                "rationale": "x",
            },
            {
                "action": "create_draft_item",
                "title": "Should not run",
                "body": "y",
                "rationale": "z",
            },
        ]
    )
    router = FakeAIRouter(
        result=AICompletionResult(
            output_text=two_actions_json,
            usage=AICompletionUsage(
                provider="anthropic",
                model="m",
                input_tokens=1,
                output_tokens=1,
                latency_seconds=0.1,
            ),
        )
    )
    state = InMemoryAutonomousState()
    today = datetime.now().date()
    state.budgets[("scrum-master", today)] = DailyBudgetStatus(actions_used=9, spend_cents_used=0)
    agent, state, tracker = _build_agent(state=state, ai_router=router, max_actions_per_day=10)

    _run(agent.run_cycle())

    assert len(state.recorded_actions) == 1
    assert tracker.create_draft_item_calls == []
