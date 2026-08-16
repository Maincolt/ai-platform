"""Component tests for GET /api/v1/autonomous-agents -- read-only status
for the ADR-0026 autonomous roles (ADR-0032), exercised in-process via
FastAPI's TestClient. Same `_client_with_state` pattern as
`test_agents_api.py`."""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

from ai_platform.api.app import CORRELATION_HEADER, app, get_app_state
from ai_platform.api.dependencies import AppState, build_app_state
from ai_platform.ports.persistence.autonomous import AutonomousActionRecord, RoleBudgetRecord


@pytest.fixture
def client() -> Iterator[TestClient]:
    fresh_state = build_app_state()
    app.dependency_overrides[get_app_state] = lambda: fresh_state
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@contextmanager
def _client_with_state(state: AppState) -> Generator[TestClient]:
    app.dependency_overrides[get_app_state] = lambda: state
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


class _FakeAutonomousState:
    def __init__(
        self,
        *,
        kill_switch_engaged: bool = False,
        role_budgets: tuple[RoleBudgetRecord, ...] = (),
        recent_actions: tuple[AutonomousActionRecord, ...] = (),
    ) -> None:
        self._kill_switch_engaged = kill_switch_engaged
        self._role_budgets = role_budgets
        self._recent_actions = recent_actions

    async def is_kill_switch_engaged(self) -> bool:
        return self._kill_switch_engaged

    async def list_role_budgets(self, *, today: date) -> tuple[RoleBudgetRecord, ...]:
        del today
        return self._role_budgets

    async def list_recent_actions(self, *, limit: int) -> tuple[AutonomousActionRecord, ...]:
        return self._recent_actions[:limit]


def test_default_state_returns_an_inert_response(client: TestClient) -> None:
    """`build_app_state()` never sets `autonomous_state` -- the endpoint
    must degrade gracefully, not 500."""
    response = client.get("/api/v1/autonomous-agents")

    assert response.status_code == 200
    assert CORRELATION_HEADER in response.headers
    body = response.json()
    assert body["kill_switch_engaged"] is False
    assert body["role_budgets"] == []
    assert body["recent_actions"] == []


def test_kill_switch_engaged_is_reported() -> None:
    base_state = build_app_state()
    state = replace(base_state, autonomous_state=_FakeAutonomousState(kill_switch_engaged=True))
    with _client_with_state(state) as test_client:
        response = test_client.get("/api/v1/autonomous-agents")

    assert response.json()["kill_switch_engaged"] is True


def test_role_budgets_are_reported() -> None:
    base_state = build_app_state()
    fake = _FakeAutonomousState(
        role_budgets=(
            RoleBudgetRecord(role="scrum-master", actions_used=3, spend_cents_used=8),
            RoleBudgetRecord(role="product-owner", actions_used=0, spend_cents_used=0),
        )
    )
    state = replace(base_state, autonomous_state=fake)
    with _client_with_state(state) as test_client:
        response = test_client.get("/api/v1/autonomous-agents")

    budgets = response.json()["role_budgets"]
    assert budgets == [
        {"role": "scrum-master", "actions_used": 3, "spend_cents_used": 8},
        {"role": "product-owner", "actions_used": 0, "spend_cents_used": 0},
    ]


def test_recent_actions_are_reported_without_inputs_or_result_detail() -> None:
    base_state = build_app_state()
    fake = _FakeAutonomousState(
        recent_actions=(
            AutonomousActionRecord(
                occurred_at=datetime(2026, 8, 16, 12, 0, 0, tzinfo=UTC),
                role="scrum-master",
                action_type="set_status",
                target="PVTI_1",
                result_status="SUCCEEDED",
            ),
        )
    )
    state = replace(base_state, autonomous_state=fake)
    with _client_with_state(state) as test_client:
        response = test_client.get("/api/v1/autonomous-agents")

    actions = response.json()["recent_actions"]
    assert actions == [
        {
            "occurred_at": "2026-08-16T12:00:00Z",
            "role": "scrum-master",
            "action_type": "set_status",
            "target": "PVTI_1",
            "result_status": "SUCCEEDED",
        }
    ]
    assert "inputs" not in actions[0]
    assert "result_detail" not in actions[0]
