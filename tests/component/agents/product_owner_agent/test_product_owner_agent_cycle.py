"""Component tests for `ProductOwnerAgent.run_cycle` (ADR-0026, ADR-0030)
-- the kill switch, daily budget, board fetch, AI proposal, and per-action
dispatch/audit flow, all against fakes. Same shape as
`scrum_master_agent`'s component test suite; no real GitHub/AI Router/DB
call is ever made in this repository's default test suite.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from ai_platform.agents.product_owner_agent.agent import ProductOwnerAgent
from ai_platform.agents.product_owner_agent.errors import (
    BacklogFetchFailedError,
    TrackerActionFailedError,
)
from ai_platform.agents.product_owner_agent.tracker import BoardItem, ProjectBoardSnapshot
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

_SNAPSHOT = ProjectBoardSnapshot(
    title="Backlog",
    items=(BoardItem(item_id="PVTI_1", title="Write docs", status="Backlog", url=""),),
)

_ONE_ARCHIVE_ACTION_JSON = json.dumps(
    [
        {
            "action": "archive_draft_ticket",
            "item_id": "PVTI_1",
            "rationale": "Duplicate of an existing ticket.",
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
class FakeBacklogTracker:
    snapshot: ProjectBoardSnapshot | None = None
    fetch_failure: BacklogFetchFailedError | None = None
    action_failures: dict[str, TrackerActionFailedError] = field(default_factory=dict)
    fetch_calls: int = 0
    create_ticket_calls: list[tuple[str, str]] = field(default_factory=list)
    edit_ticket_calls: list[tuple[str, str, str]] = field(default_factory=list)
    close_ticket_calls: list[str] = field(default_factory=list)
    archive_draft_ticket_calls: list[str] = field(default_factory=list)
    reprioritize_calls: list[tuple[str, str | None]] = field(default_factory=list)
    adjust_sprint_scope_calls: list[tuple[str, str]] = field(default_factory=list)

    async def fetch(self) -> ProjectBoardSnapshot:
        self.fetch_calls += 1
        if self.fetch_failure is not None:
            raise self.fetch_failure
        assert self.snapshot is not None
        return self.snapshot

    async def create_ticket(self, *, title: str, body: str) -> None:
        if "create_ticket" in self.action_failures:
            raise self.action_failures["create_ticket"]
        self.create_ticket_calls.append((title, body))

    async def edit_ticket(self, *, issue_url: str, title: str, body: str) -> None:
        if "edit_ticket" in self.action_failures:
            raise self.action_failures["edit_ticket"]
        self.edit_ticket_calls.append((issue_url, title, body))

    async def close_ticket(self, *, issue_url: str) -> None:
        if "close_ticket" in self.action_failures:
            raise self.action_failures["close_ticket"]
        self.close_ticket_calls.append(issue_url)

    async def archive_draft_ticket(self, *, item_id: str) -> None:
        if "archive_draft_ticket" in self.action_failures:
            raise self.action_failures["archive_draft_ticket"]
        self.archive_draft_ticket_calls.append(item_id)

    async def reprioritize(self, *, item_id: str, after_item_id: str | None) -> None:
        if "reprioritize" in self.action_failures:
            raise self.action_failures["reprioritize"]
        self.reprioritize_calls.append((item_id, after_item_id))

    async def adjust_sprint_scope(self, *, item_id: str, status_name: str) -> None:
        if "adjust_sprint_scope" in self.action_failures:
            raise self.action_failures["adjust_sprint_scope"]
        self.adjust_sprint_scope_calls.append((item_id, status_name))


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
    tracker: FakeBacklogTracker | None = None,
    max_actions_per_day: int = 10,
    max_spend_cents_per_day: int = 100,
) -> tuple[ProductOwnerAgent, InMemoryAutonomousState, FakeBacklogTracker]:
    state = state or InMemoryAutonomousState()
    tracker = tracker or FakeBacklogTracker(snapshot=_SNAPSHOT)
    agent = ProductOwnerAgent(
        agent_deployment_id="product-owner-agent",
        state=state,
        backlog_tracker=tracker,
        ai_router=ai_router if ai_router is not None else _UnreachableAIRouter(),
        max_output_tokens=256,
        provider_deadline_seconds=20.0,
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
    state.budgets[("product-owner", today)] = DailyBudgetStatus(actions_used=10, spend_cents_used=0)
    agent, state, tracker = _build_agent(state=state, max_actions_per_day=10)

    _run(agent.run_cycle())

    assert tracker.fetch_calls == 0


def test_budget_exhausted_by_spend_skips_the_cycle() -> None:
    state = InMemoryAutonomousState()
    today = datetime.now().date()
    state.budgets[("product-owner", today)] = DailyBudgetStatus(
        actions_used=0, spend_cents_used=100
    )
    agent, state, tracker = _build_agent(state=state, max_spend_cents_per_day=100)

    _run(agent.run_cycle())

    assert tracker.fetch_calls == 0


def test_board_fetch_failure_skips_the_ai_call_and_records_nothing() -> None:
    tracker = FakeBacklogTracker(fetch_failure=BacklogFetchFailedError("HTTP 401"))
    agent, state, tracker = _build_agent(tracker=tracker)

    _run(agent.run_cycle())

    assert state.recorded_actions == []


def test_happy_path_dispatches_the_proposed_action_and_records_success() -> None:
    router = FakeAIRouter(
        result=AICompletionResult(
            output_text=_ONE_ARCHIVE_ACTION_JSON,
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

    assert tracker.archive_draft_ticket_calls == ["PVTI_1"]
    assert len(state.recorded_actions) == 1
    recorded = state.recorded_actions[0]
    assert recorded.action_type == "archive_draft_ticket"
    assert recorded.target == "PVTI_1"
    assert recorded.result_status == "SUCCEEDED"
    assert recorded.agent_deployment_id == "product-owner-agent"
    assert recorded.role == "product-owner"
    today = datetime.now().date()
    assert state.budgets[("product-owner", today)].actions_used == 1


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
    assert tracker.archive_draft_ticket_calls == []


def test_malformed_ai_response_dispatches_nothing() -> None:
    router = FakeAIRouter(
        result=AICompletionResult(
            output_text="here is my plan for the backlog...",
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
    agent, _state, _tracker = _build_agent(ai_router=router)

    _run(agent.run_cycle())


def test_all_six_action_types_dispatch_and_record_success() -> None:
    raw = json.dumps(
        [
            {"action": "create_ticket", "title": "New ticket", "body": "x", "rationale": "a"},
            {
                "action": "edit_ticket",
                "issue_url": "https://x/1",
                "title": "t",
                "body": "b",
                "rationale": "b",
            },
            {"action": "close_ticket", "issue_url": "https://x/1", "rationale": "c"},
            {"action": "archive_draft_ticket", "item_id": "PVTI_1", "rationale": "d"},
            {
                "action": "reprioritize",
                "item_id": "PVTI_1",
                "after_item_id": "TOP",
                "rationale": "e",
            },
            {
                "action": "adjust_sprint_scope",
                "item_id": "PVTI_1",
                "status": "Backlog",
                "rationale": "f",
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
    agent, state, tracker = _build_agent(ai_router=router)

    _run(agent.run_cycle())

    assert tracker.create_ticket_calls == [("New ticket", "x")]
    assert tracker.edit_ticket_calls == [("https://x/1", "t", "b")]
    assert tracker.close_ticket_calls == ["https://x/1"]
    assert tracker.archive_draft_ticket_calls == ["PVTI_1"]
    assert tracker.reprioritize_calls == [("PVTI_1", None)]
    assert tracker.adjust_sprint_scope_calls == [("PVTI_1", "Backlog")]
    assert len(state.recorded_actions) == 6
    assert all(action.result_status == "SUCCEEDED" for action in state.recorded_actions)


def test_one_action_failure_does_not_block_the_next_actions_dispatch() -> None:
    raw = json.dumps(
        [
            {"action": "close_ticket", "issue_url": "https://x/1", "rationale": "a"},
            {"action": "archive_draft_ticket", "item_id": "PVTI_1", "rationale": "b"},
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
    tracker = FakeBacklogTracker(
        snapshot=_SNAPSHOT,
        action_failures={"close_ticket": TrackerActionFailedError("close_ticket", "boom")},
    )
    agent, state, tracker = _build_agent(ai_router=router, tracker=tracker)

    _run(agent.run_cycle())

    assert tracker.archive_draft_ticket_calls == ["PVTI_1"]
    assert [action.result_status for action in state.recorded_actions] == ["FAILED", "SUCCEEDED"]
