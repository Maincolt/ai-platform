"""Component tests for `DomainReviewAgent.run_cycle` (ADR-0026, ADR-0033)
-- the kill switch, daily budget, domain-path filtering, AI proposal, and
dispatch/audit flow, all against fakes. Parametrized-by-construction
across both roles' real `path_prefixes` (frontend vs. Postgres) to prove
the filter actually discriminates between them, not just in isolation.
No real GitHub/AI Router/DB call is ever made in this repository's
default test suite.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from ai_platform.agents._pull_request_review_shared import PullRequestSnapshot
from ai_platform.agents.domain_review_agent.agent import DomainReviewAgent
from ai_platform.agents.domain_review_agent.errors import (
    PullRequestFetchFailedError,
    ReviewActionFailedError,
)
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

_FRONTEND_PULL_REQUEST = PullRequestSnapshot(
    number=1, title="Add a Vue component", changed_file_paths=("frontend/dashboard/src/App.vue",)
)
_BACKEND_PULL_REQUEST = PullRequestSnapshot(
    number=2, title="Fix a typo in the README", changed_file_paths=("README.md",)
)

_ONE_REQUEST_CHANGES_ACTION_JSON = json.dumps(
    [
        {
            "action": "request_changes",
            "pull_number": "1",
            "body": "Please use the Composition API here.",
            "rationale": "Options API is inconsistent with the rest of the codebase.",
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
class FakePullRequestReview:
    pull_requests: tuple[PullRequestSnapshot, ...] = ()
    fetch_failure: PullRequestFetchFailedError | None = None
    action_failure: ReviewActionFailedError | None = None
    fetch_calls: int = 0
    request_changes_calls: list[tuple[int, str]] = field(default_factory=list)

    async def fetch_open_pull_requests(self) -> tuple[PullRequestSnapshot, ...]:
        self.fetch_calls += 1
        if self.fetch_failure is not None:
            raise self.fetch_failure
        return self.pull_requests

    async def request_changes(self, *, pull_number: int, body: str) -> None:
        if self.action_failure is not None:
            raise self.action_failure
        self.request_changes_calls.append((pull_number, body))


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
    role: str = "frontend-specialist",
    path_prefixes: tuple[str, ...] = ("frontend/",),
    state: InMemoryAutonomousState | None = None,
    ai_router: Any = None,
    pull_request_review: FakePullRequestReview | None = None,
    max_actions_per_day: int = 10,
    max_spend_cents_per_day: int = 100,
) -> tuple[DomainReviewAgent, InMemoryAutonomousState, FakePullRequestReview]:
    state = state or InMemoryAutonomousState()
    pull_request_review = pull_request_review or FakePullRequestReview(
        pull_requests=(_FRONTEND_PULL_REQUEST,)
    )
    agent = DomainReviewAgent(
        role=role,
        domain_label="Vue.js frontend",
        path_prefixes=path_prefixes,
        agent_deployment_id="frontend-specialist-agent",
        state=state,
        pull_request_review=pull_request_review,
        ai_router=ai_router if ai_router is not None else _UnreachableAIRouter(),
        max_output_tokens=256,
        provider_deadline_seconds=20.0,
        max_actions_per_day=max_actions_per_day,
        max_spend_cents_per_day=max_spend_cents_per_day,
    )
    return agent, state, pull_request_review


def test_kill_switch_engaged_skips_the_whole_cycle() -> None:
    state = InMemoryAutonomousState(kill_switch_engaged=True)
    agent, state, pull_request_review = _build_agent(state=state)

    _run(agent.run_cycle())

    assert pull_request_review.fetch_calls == 0
    assert state.recorded_actions == []


def test_budget_exhausted_by_action_count_skips_the_cycle() -> None:
    state = InMemoryAutonomousState()
    today = datetime.now().date()
    state.budgets[("frontend-specialist", today)] = DailyBudgetStatus(
        actions_used=10, spend_cents_used=0
    )
    agent, state, pull_request_review = _build_agent(state=state, max_actions_per_day=10)

    _run(agent.run_cycle())

    assert pull_request_review.fetch_calls == 0


def test_pull_request_fetch_failure_skips_the_ai_call_and_records_nothing() -> None:
    pull_request_review = FakePullRequestReview(
        fetch_failure=PullRequestFetchFailedError("HTTP 401")
    )
    agent, state, pull_request_review = _build_agent(pull_request_review=pull_request_review)

    _run(agent.run_cycle())

    assert state.recorded_actions == []


def test_no_pull_requests_in_domain_skips_the_ai_call() -> None:
    """The frontend role's own filter, exercised with a PR that touches
    only out-of-domain files -- proves filtering happens before any AI
    Router call, not just that the AI declines to act."""
    pull_request_review = FakePullRequestReview(pull_requests=(_BACKEND_PULL_REQUEST,))
    agent, state, pull_request_review = _build_agent(pull_request_review=pull_request_review)

    _run(agent.run_cycle())

    assert state.recorded_actions == []


def test_domain_filter_only_shows_matching_prs_to_the_ai_router() -> None:
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
    pull_request_review = FakePullRequestReview(
        pull_requests=(_FRONTEND_PULL_REQUEST, _BACKEND_PULL_REQUEST)
    )
    agent, _state, pull_request_review = _build_agent(
        ai_router=router, pull_request_review=pull_request_review
    )

    _run(agent.run_cycle())

    assert len(router.calls) == 1
    prompt = router.calls[0].prompt
    assert "Add a Vue component" in prompt
    assert "Fix a typo in the README" not in prompt


def test_happy_path_dispatches_the_proposed_action_and_records_success() -> None:
    router = FakeAIRouter(
        result=AICompletionResult(
            output_text=_ONE_REQUEST_CHANGES_ACTION_JSON,
            usage=AICompletionUsage(
                provider="anthropic",
                model="claude-haiku-4-5",
                input_tokens=500,
                output_tokens=100,
                latency_seconds=0.5,
            ),
        )
    )
    agent, state, pull_request_review = _build_agent(ai_router=router)

    _run(agent.run_cycle())

    assert pull_request_review.request_changes_calls == [
        (1, "Please use the Composition API here.")
    ]
    assert len(state.recorded_actions) == 1
    recorded = state.recorded_actions[0]
    assert recorded.action_type == "request_changes"
    assert recorded.target == "1"
    assert recorded.result_status == "SUCCEEDED"
    assert recorded.agent_deployment_id == "frontend-specialist-agent"
    assert recorded.role == "frontend-specialist"
    today = datetime.now().date()
    assert state.budgets[("frontend-specialist", today)].actions_used == 1


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
    agent, state, pull_request_review = _build_agent(ai_router=router)

    _run(agent.run_cycle())

    assert state.recorded_actions == []
    assert pull_request_review.request_changes_calls == []


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
    agent, state, _pull_request_review = _build_agent(ai_router=router)

    _run(agent.run_cycle())

    assert state.recorded_actions == []


def test_ai_router_classified_failure_dispatches_nothing() -> None:
    router = FakeAIRouter(
        result=AICompletionResult(failure_code=AICompletionFailureCode.ALL_PROVIDERS_EXHAUSTED)
    )
    agent, _state, _pull_request_review = _build_agent(ai_router=router)

    _run(agent.run_cycle())


def test_action_failure_is_recorded_as_failed() -> None:
    router = FakeAIRouter(
        result=AICompletionResult(
            output_text=_ONE_REQUEST_CHANGES_ACTION_JSON,
            usage=AICompletionUsage(
                provider="anthropic",
                model="claude-haiku-4-5",
                input_tokens=500,
                output_tokens=100,
                latency_seconds=0.5,
            ),
        )
    )
    pull_request_review = FakePullRequestReview(
        pull_requests=(_FRONTEND_PULL_REQUEST,),
        action_failure=ReviewActionFailedError("request_changes", "boom"),
    )
    agent, state, pull_request_review = _build_agent(
        ai_router=router, pull_request_review=pull_request_review
    )

    _run(agent.run_cycle())

    assert pull_request_review.request_changes_calls == []
    assert len(state.recorded_actions) == 1
    assert state.recorded_actions[0].result_status == "FAILED"


def test_postgres_specialist_domain_filter_matches_its_own_paths() -> None:
    """Same filter mechanism, exercised with the real Postgres role's
    path_prefixes -- proves the two roles' filters actually discriminate
    differently, not just that frontend's filter works in isolation."""
    postgres_pull_request = PullRequestSnapshot(
        number=3,
        title="Add a migration",
        changed_file_paths=("infrastructure/migrations/0010_x.sql",),
    )
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
    pull_request_review = FakePullRequestReview(
        pull_requests=(_FRONTEND_PULL_REQUEST, postgres_pull_request)
    )
    agent, _state, pull_request_review = _build_agent(
        role="postgres-specialist",
        path_prefixes=(
            "infrastructure/migrations/",
            "src/ai_platform/adapters/persistence/",
            "src/ai_platform/ports/persistence/",
        ),
        ai_router=router,
        pull_request_review=pull_request_review,
    )

    _run(agent.run_cycle())

    assert len(router.calls) == 1
    prompt = router.calls[0].prompt
    assert "Add a migration" in prompt
    assert "Add a Vue component" not in prompt
