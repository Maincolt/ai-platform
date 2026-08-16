"""Component tests for GET /api/v1/agents -- read-only Capability Registry
status, exercised in-process via FastAPI's TestClient."""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from ai_platform.api.app import CORRELATION_HEADER, app, get_app_state
from ai_platform.api.dependencies import (
    AppState,
    build_app_state,
    default_test_agent_binding,
)
from ai_platform.orchestrator.registry.availability import (
    AvailabilityClassification,
    AvailabilityObservation,
    AvailabilityPort,
)
from ai_platform.orchestrator.registry.declarations import CapabilityBinding
from ai_platform.orchestrator.registry.snapshot import load_registry_snapshot
from ai_platform.shared.identifiers import AgentId


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


def test_default_state_reports_one_ready_agent(client: TestClient) -> None:
    response = client.get("/api/v1/agents")

    assert response.status_code == 200
    assert CORRELATION_HEADER in response.headers
    body = response.json()
    assert len(body["agents"]) == 1
    agent = body["agents"][0]
    assert agent["capability"] == "text.word-count"
    assert agent["status"] == "READY"
    assert agent["fresh"] is True
    assert agent["enabled"] is True
    assert agent["last_observed_at"] is not None


def test_empty_registry_reports_no_agents_not_an_error() -> None:
    state = build_app_state(bindings=[])
    with _client_with_state(state) as test_client:
        response = test_client.get("/api/v1/agents")

    assert response.status_code == 200
    assert response.json()["agents"] == []


def test_disabled_binding_is_reported_but_marked_disabled() -> None:
    binding = replace(default_test_agent_binding(), enabled=False)
    state = build_app_state(bindings=[binding])
    with _client_with_state(state) as test_client:
        response = test_client.get("/api/v1/agents")

    agent = response.json()["agents"][0]
    assert agent["enabled"] is False


class _FixedAvailability(AvailabilityPort):
    def __init__(self, observation: AvailabilityObservation) -> None:
        self._observation = observation

    def observe(
        self, agent_id: AgentId, capability_name: str, capability_version: str
    ) -> AvailabilityObservation:
        del agent_id, capability_name, capability_version
        return self._observation


def test_unavailable_agent_is_reported_as_not_fresh() -> None:
    binding = default_test_agent_binding()
    snapshot = load_registry_snapshot([binding], revision="test-rev")
    unavailable = _FixedAvailability(
        AvailabilityObservation(
            classification=AvailabilityClassification.UNAVAILABLE,
            observed_at=datetime.now(UTC),
            ttl_seconds=10.0,
        )
    )
    base_state = build_app_state(bindings=[binding])
    state = replace(base_state, registry_snapshot=snapshot, availability_port=unavailable)
    with _client_with_state(state) as test_client:
        response = test_client.get("/api/v1/agents")

    agent = response.json()["agents"][0]
    assert agent["status"] == "UNAVAILABLE"
    assert agent["fresh"] is False


def test_never_observed_agent_reports_unknown_with_no_timestamp() -> None:
    binding: CapabilityBinding = default_test_agent_binding()
    snapshot = load_registry_snapshot([binding], revision="test-rev")
    never_observed = _FixedAvailability(
        AvailabilityObservation(
            classification=AvailabilityClassification.UNKNOWN,
            observed_at=datetime.min.replace(tzinfo=UTC),
            ttl_seconds=10.0,
        )
    )
    base_state = build_app_state(bindings=[binding])
    state = replace(base_state, registry_snapshot=snapshot, availability_port=never_observed)
    with _client_with_state(state) as test_client:
        response = test_client.get("/api/v1/agents")

    agent = response.json()["agents"][0]
    assert agent["status"] == "UNKNOWN"
    assert agent["last_observed_at"] is None


def test_default_state_reports_zero_in_flight_when_idle(client: TestClient) -> None:
    response = client.get("/api/v1/agents")

    agent = response.json()["agents"][0]
    assert agent["in_flight_count"] == 0


def test_in_flight_count_increments_after_a_dispatched_submission(client: TestClient) -> None:
    submit_body = {
        "text": "the quick brown fox",
        "capability": "text.word-count",
        "capability_version": "1.0",
    }
    submit_response = client.post("/api/v1/workflows", json=submit_body)
    assert submit_response.status_code == 202
    assert submit_response.json()["state"] == "DISPATCHED"

    response = client.get("/api/v1/agents")

    agent = response.json()["agents"][0]
    assert agent["in_flight_count"] == 1


def test_registry_not_loaded_reports_no_agents_not_an_error() -> None:
    base_state = build_app_state()
    state = replace(base_state, registry_snapshot=None, availability_port=None)
    with _client_with_state(state) as test_client:
        response = test_client.get("/api/v1/agents")

    assert response.status_code == 200
    assert response.json()["agents"] == []
