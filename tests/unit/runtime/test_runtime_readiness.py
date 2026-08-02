"""Tests for authenticated Agent readiness and bounded Registry observations."""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

import asyncio
import json
from datetime import UTC, datetime

import httpx
from fastapi.testclient import TestClient

from ai_platform.orchestrator.registry.availability import AvailabilityClassification
from ai_platform.runtime.readiness import (
    AgentReadinessClient,
    AgentReadinessSnapshot,
    AgentReadinessState,
    CachedAgentAvailability,
    create_agent_readiness_app,
)
from ai_platform.shared.identifiers import AgentId

AGENT_ID = AgentId("018f23a7-6b4d-7c91-8a2e-123456789abc")
NOW = datetime(2026, 8, 1, 12, tzinfo=UTC)
DECLARATION_REVISION = "sprint-6"
COMMAND_CONTRACTS = (("ExecuteTask", "1.0"),)
EVENT_CONTRACTS = (("TaskCompleted", "1.0"), ("TaskFailed", "1.0"))


def _state() -> AgentReadinessState:
    return AgentReadinessState(
        AgentReadinessSnapshot(
            environment="development",
            agent_id=AGENT_ID,
            declaration_revision=DECLARATION_REVISION,
            declaration_digest="sha256:declaration",
            capabilities=(("text.word-count", "1.0"),),
            accepted_command_contracts=COMMAND_CONTRACTS,
            produced_event_contracts=EVENT_CONTRACTS,
            ready=True,
            draining=False,
        )
    )


def test_readiness_endpoint_hides_itself_without_the_scoped_credential() -> None:
    app = create_agent_readiness_app(state=_state(), readiness_credential="secret")
    with TestClient(app) as client:
        assert client.get("/health/ready").status_code == 404
        response = client.get("/health/ready", headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 404


def test_readiness_endpoint_returns_bounded_declaration_identity() -> None:
    state = _state()
    app = create_agent_readiness_app(state=state, readiness_credential="secret")
    with TestClient(app) as client:
        response = client.get("/health/ready", headers={"Authorization": "Bearer secret"})
        assert response.status_code == 200
        assert response.json()["agent_id"] == AGENT_ID
        state.start_draining()
        assert (
            client.get("/health/ready", headers={"Authorization": "Bearer secret"}).status_code
            == 503
        )


def test_client_records_ready_only_when_all_trusted_identity_fields_match() -> None:
    async def run() -> None:
        document = {
            "environment": "development",
            "agent_id": str(AGENT_ID),
            "declaration_revision": DECLARATION_REVISION,
            "declaration_digest": "sha256:declaration",
            "capabilities": [{"name": "text.word-count", "version": "1.0"}],
            "accepted_command_contracts": [{"name": "ExecuteTask", "version": "1.0"}],
            "produced_event_contracts": [
                {"name": "TaskCompleted", "version": "1.0"},
                {"name": "TaskFailed", "version": "1.0"},
            ],
            "ready": True,
            "draining": False,
        }

        async def respond(request: httpx.Request) -> httpx.Response:
            assert request.headers["Authorization"] == "Bearer secret"
            return httpx.Response(200, content=json.dumps(document).encode())

        cache = CachedAgentAvailability(ttl_seconds=2)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
            client = AgentReadinessClient(
                client=http_client,
                readiness_url="http://127.0.0.1/health/ready",
                credential="secret",
                cache=cache,
                timeout_seconds=0.1,
            )
            observation = await client.refresh(
                environment="development",
                agent_id=AGENT_ID,
                declaration_revision=DECLARATION_REVISION,
                declaration_digest="sha256:declaration",
                capability_name="text.word-count",
                capability_version="1.0",
                accepted_command_contracts=COMMAND_CONTRACTS,
                produced_event_contracts=EVENT_CONTRACTS,
                now=NOW,
            )
        assert observation.classification is AvailabilityClassification.READY

    asyncio.run(run())


def test_identity_mismatch_fails_closed_and_replaces_previous_ready_observation() -> None:
    async def run() -> None:
        cache = CachedAgentAvailability(ttl_seconds=2)
        cache.record(
            AGENT_ID,
            "text.word-count",
            "1.0",
            AvailabilityClassification.READY,
            observed_at=NOW,
        )

        async def respond(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "environment": "wrong",
                    "agent_id": str(AGENT_ID),
                    "declaration_revision": DECLARATION_REVISION,
                    "declaration_digest": "sha256:declaration",
                    "capabilities": [{"name": "text.word-count", "version": "1.0"}],
                    "accepted_command_contracts": [{"name": "ExecuteTask", "version": "1.0"}],
                    "produced_event_contracts": [
                        {"name": "TaskCompleted", "version": "1.0"},
                        {"name": "TaskFailed", "version": "1.0"},
                    ],
                    "ready": True,
                    "draining": False,
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
            client = AgentReadinessClient(
                client=http_client,
                readiness_url="http://127.0.0.1/health/ready",
                credential="secret",
                cache=cache,
                timeout_seconds=0.1,
            )
            observation = await client.refresh(
                environment="development",
                agent_id=AGENT_ID,
                declaration_revision=DECLARATION_REVISION,
                declaration_digest="sha256:declaration",
                capability_name="text.word-count",
                capability_version="1.0",
                accepted_command_contracts=COMMAND_CONTRACTS,
                produced_event_contracts=EVENT_CONTRACTS,
                now=NOW,
            )
        assert observation.classification is AvailabilityClassification.UNAVAILABLE

    asyncio.run(run())


def test_network_failure_becomes_unknown_without_extending_ready_state() -> None:
    async def run() -> None:
        async def fail(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("offline", request=request)

        cache = CachedAgentAvailability(ttl_seconds=2)
        async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as http_client:
            client = AgentReadinessClient(
                client=http_client,
                readiness_url="http://127.0.0.1/health/ready",
                credential="secret",
                cache=cache,
                timeout_seconds=0.1,
            )
            observation = await client.refresh(
                environment="development",
                agent_id=AGENT_ID,
                declaration_revision=DECLARATION_REVISION,
                declaration_digest="sha256:declaration",
                capability_name="text.word-count",
                capability_version="1.0",
                accepted_command_contracts=COMMAND_CONTRACTS,
                produced_event_contracts=EVENT_CONTRACTS,
                now=NOW,
            )
        assert observation.classification is AvailabilityClassification.UNKNOWN

    asyncio.run(run())


def test_cache_uses_monotonic_expiry_and_fails_closed_on_clock_backstep() -> None:
    ticks = [10.0]
    cache = CachedAgentAvailability(ttl_seconds=2, monotonic_clock=lambda: ticks[0])
    cache.record(
        AGENT_ID,
        "text.word-count",
        "1.0",
        AvailabilityClassification.READY,
        observed_at=NOW,
    )
    ticks[0] = 9.0

    assert (
        cache.observe(AGENT_ID, "text.word-count", "1.0").classification
        is AvailabilityClassification.STALE
    )


def test_chunked_oversized_or_compressed_readiness_response_fails_closed() -> None:
    async def classify(headers: dict[str, str], content: bytes) -> AvailabilityClassification:
        async def respond(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers=headers, content=content)

        cache = CachedAgentAvailability(ttl_seconds=2)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
            client = AgentReadinessClient(
                client=http_client,
                readiness_url="http://127.0.0.1/health/ready",
                credential="secret",
                cache=cache,
                timeout_seconds=0.1,
                maximum_response_bytes=8,
            )
            observation = await client.refresh(
                environment="development",
                agent_id=AGENT_ID,
                declaration_revision=DECLARATION_REVISION,
                declaration_digest="sha256:declaration",
                capability_name="text.word-count",
                capability_version="1.0",
                accepted_command_contracts=COMMAND_CONTRACTS,
                produced_event_contracts=EVENT_CONTRACTS,
                now=NOW,
            )
        return observation.classification

    assert asyncio.run(classify({}, b"0123456789")) is AvailabilityClassification.UNKNOWN
    assert (
        asyncio.run(classify({"Content-Encoding": "gzip"}, b"{}"))
        is AvailabilityClassification.UNKNOWN
    )
