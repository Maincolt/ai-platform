"""Component tests: the Workflow API's full HTTP contract, exercised
in-process via FastAPI's TestClient (httpx-based, no running server or
Docker required). Covers the Section 5 error table end-to-end.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from ai_platform.api.app import CORRELATION_HEADER, app, get_app_state
from ai_platform.api.dependencies import build_app_state

VALID_SUBMIT_BODY = {
    "text": "the quick brown fox",
    "capability": "text.word-count",
    "capability_version": "1.0",
}


@pytest.fixture
def client() -> Iterator[TestClient]:
    # Fresh AppState per test so submissions in one test never leak into
    # another (the module-level app singleton is otherwise shared).
    fresh_state = build_app_state()
    app.dependency_overrides[get_app_state] = lambda: fresh_state
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_health_live_always_succeeds(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_health_ready_reports_registry_loaded(client: TestClient) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_unmatched_route_returns_404_not_500(client: TestClient) -> None:
    """Regression test: Starlette's own HTTPException (raised for an
    unmatched route) must not be swallowed by the catch-all Exception
    handler and turned into an opaque 500."""
    response = client.get("/this-route-does-not-exist")
    assert response.status_code == 404
    assert response.status_code != 500


def test_unsupported_method_returns_405_not_500(client: TestClient) -> None:
    response = client.delete("/api/v1/workflows")
    assert response.status_code == 405
    assert response.status_code != 500


def test_submit_new_workflow_returns_202_dispatched(client: TestClient) -> None:
    response = client.post("/api/v1/workflows", json=VALID_SUBMIT_BODY)

    assert response.status_code == 202
    body = response.json()
    assert body["state"] == "DISPATCHED"
    assert "workflow_id" in body
    assert "correlation_id" in body
    assert response.headers[CORRELATION_HEADER] == body["correlation_id"]


def test_submit_missing_correlation_header_generates_one(client: TestClient) -> None:
    response = client.post("/api/v1/workflows", json=VALID_SUBMIT_BODY)
    assert CORRELATION_HEADER in response.headers
    assert len(response.headers[CORRELATION_HEADER]) == 36


def test_submit_valid_correlation_header_is_preserved(client: TestClient) -> None:
    valid_correlation = "019fbdd6-ab3d-77aa-8e61-4c3903e582ad"
    response = client.post(
        "/api/v1/workflows",
        json=VALID_SUBMIT_BODY,
        headers={CORRELATION_HEADER: valid_correlation},
    )
    assert response.headers[CORRELATION_HEADER] == valid_correlation
    assert response.json()["correlation_id"] == valid_correlation


def test_submit_invalid_correlation_header_is_discarded_and_generated(client: TestClient) -> None:
    response = client.post(
        "/api/v1/workflows",
        json=VALID_SUBMIT_BODY,
        headers={CORRELATION_HEADER: "not-a-uuid"},
    )
    assert response.headers[CORRELATION_HEADER] != "not-a-uuid"
    assert len(response.headers[CORRELATION_HEADER]) == 36


def test_submit_invalid_body_returns_400_problem_details(client: TestClient) -> None:
    response = client.post("/api/v1/workflows", json={"text": ""})

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "INVALID_REQUEST"
    assert body["status"] == 400
    assert "correlation_id" in body
    assert response.headers[CORRELATION_HEADER] == body["correlation_id"]


def test_submit_equivalent_replay_returns_200_with_same_workflow(client: TestClient) -> None:
    request_id = "019fbdd6-ab3d-77aa-8e61-4c3a4e21ad64"
    body_with_id = {**VALID_SUBMIT_BODY, "request_id": request_id}

    first = client.post("/api/v1/workflows", json=body_with_id)
    second = client.post("/api/v1/workflows", json=body_with_id)

    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json()["workflow_id"] == first.json()["workflow_id"]
    # The durable body correlation is unchanged even though this is a
    # distinct invocation (ADR-0012 replay semantics).
    assert second.json()["correlation_id"] == first.json()["correlation_id"]


def test_submit_fingerprint_conflict_returns_409(client: TestClient) -> None:
    request_id = "019fbdd6-ab3d-77aa-8e61-4c3bc6d53f69"
    first_body = {**VALID_SUBMIT_BODY, "request_id": request_id, "text": "original text"}
    conflicting_body = {**VALID_SUBMIT_BODY, "request_id": request_id, "text": "different text"}

    first = client.post("/api/v1/workflows", json=first_body)
    second = client.post("/api/v1/workflows", json=conflicting_body)

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["error_code"] == "REQUEST_ID_CONFLICT"


def test_get_missing_workflow_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/workflows/019fbdd6-ab3d-77aa-8e61-4c40d234a3bf")

    assert response.status_code == 404
    body = response.json()
    assert body["error_code"] == "WORKFLOW_NOT_FOUND"


def test_get_existing_workflow_returns_current_state(client: TestClient) -> None:
    submit_response = client.post("/api/v1/workflows", json=VALID_SUBMIT_BODY)
    workflow_id = submit_response.json()["workflow_id"]

    read_response = client.get(f"/api/v1/workflows/{workflow_id}")

    assert read_response.status_code == 200
    body = read_response.json()
    assert body["workflow_id"] == workflow_id
    assert body["state"] == "DISPATCHED"
    assert body["revision"] >= 1
    assert "created_at" in body
    assert "updated_at" in body


def test_submit_no_eligible_agent_returns_503() -> None:
    """Uses an alternate AppState built with an empty Registry snapshot,
    since the default app-wired snapshot always has one eligible binding."""
    state = build_app_state(bindings=[])
    app.dependency_overrides[get_app_state] = lambda: state
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/workflows", json=VALID_SUBMIT_BODY)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["error_code"] == "AGENT_TEMPORARILY_UNAVAILABLE"


def test_public_response_never_exposes_internal_identifiers(client: TestClient) -> None:
    response = client.post("/api/v1/workflows", json=VALID_SUBMIT_BODY)
    body = response.json()

    assert "task_id" not in body
    assert "task_attempt_id" not in body
    assert "idempotency_scope_id" not in body
