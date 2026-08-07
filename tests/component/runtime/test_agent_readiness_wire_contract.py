"""Real `AgentReadinessClient` against the real `create_agent_readiness_app`.

Phase 7 (Section 19 "Agent selection/readiness": revision/digest, bounded
verification, TTL, stale/unknown/draining) continuation. `AgentReadinessClient`
and `create_agent_readiness_app` each have thorough unit coverage
(`tests/unit/runtime/test_runtime_readiness.py`), but only in isolation: the
client's tests feed it hand-built fake JSON documents via `httpx.MockTransport`,
never the server's own real response bytes, and the server's tests only ever
inspect status codes -- never the client's classification of them. The two
halves have never been proven to actually agree on the wire contract between
them (does the client's expected JSON shape match byte-for-byte what the
server emits? does the server's real 404 identity-hiding response actually
classify as UNAVAILABLE, not just a hand-crafted "wrong environment" document?).

This uses `httpx.ASGITransport` to drive the real FastAPI app over the real
HTTP protocol (headers, status codes, JSON encoding, streaming) without
binding a real socket -- the same mechanism `fastapi.testclient.TestClient`
uses internally. No external service is involved, so this is a local
Component test (`docs/testing/README.md`), not `external_service`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any

import httpx

from ai_platform.orchestrator.registry.availability import (
    AvailabilityClassification,
    is_fresh,
)
from ai_platform.runtime.readiness import (
    AgentReadinessClient,
    AgentReadinessSnapshot,
    AgentReadinessState,
    CachedAgentAvailability,
    create_agent_readiness_app,
)
from ai_platform.shared.identifiers import AgentId

AGENT_ID = AgentId("018f23a7-6b4d-7c91-8a2e-abcdef987654")
NOW = datetime(2026, 8, 7, 12, tzinfo=UTC)
ENVIRONMENT = "development"
DECLARATION_REVISION = "sprint-10-wire-contract"
DECLARATION_DIGEST = "sha256:sprint-10-wire-contract"
CAPABILITY_NAME = "text.summarize"
CAPABILITY_VERSION = "1.0"
COMMAND_CONTRACTS = (("ExecuteTask", "1.0"),)
EVENT_CONTRACTS = (("TaskCompleted", "1.0"), ("TaskFailed", "1.0"))
CREDENTIAL = "sprint-10-readiness-credential"  # noqa: S105


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def _snapshot(*, ready: bool, draining: bool = False) -> AgentReadinessSnapshot:
    return AgentReadinessSnapshot(
        environment=ENVIRONMENT,
        agent_id=AGENT_ID,
        declaration_revision=DECLARATION_REVISION,
        declaration_digest=DECLARATION_DIGEST,
        capabilities=((CAPABILITY_NAME, CAPABILITY_VERSION),),
        accepted_command_contracts=COMMAND_CONTRACTS,
        produced_event_contracts=EVENT_CONTRACTS,
        ready=ready,
        draining=draining,
    )


def _wired_client(
    state: AgentReadinessState, *, cache: CachedAgentAvailability, credential: str = CREDENTIAL
) -> tuple[AgentReadinessClient, httpx.AsyncClient]:
    """Pair a real client with the real app, connected only over ASGI transport."""
    app = create_agent_readiness_app(state=state, readiness_credential=CREDENTIAL)
    http_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://agent.local"
    )
    return (
        AgentReadinessClient(
            client=http_client,
            readiness_url="http://agent.local/health/ready",
            credential=credential,
            cache=cache,
            timeout_seconds=1.0,
        ),
        http_client,
    )


async def _refresh(client: AgentReadinessClient, *, now: datetime = NOW) -> Any:
    return await client.refresh(
        environment=ENVIRONMENT,
        agent_id=AGENT_ID,
        declaration_revision=DECLARATION_REVISION,
        declaration_digest=DECLARATION_DIGEST,
        capability_name=CAPABILITY_NAME,
        capability_version=CAPABILITY_VERSION,
        accepted_command_contracts=COMMAND_CONTRACTS,
        produced_event_contracts=EVENT_CONTRACTS,
        now=now,
    )


def test_ready_declaration_is_classified_ready_and_fresh() -> None:
    async def run() -> None:
        state = AgentReadinessState(_snapshot(ready=True))
        cache = CachedAgentAvailability(ttl_seconds=10)
        client, http_client = _wired_client(state, cache=cache)
        async with http_client:
            observation = await _refresh(client)
        assert observation.classification is AvailabilityClassification.READY
        assert is_fresh(observation, now=NOW)

    _run(run())


def test_draining_declaration_is_classified_draining_not_ready() -> None:
    async def run() -> None:
        state = AgentReadinessState(_snapshot(ready=False, draining=True))
        cache = CachedAgentAvailability(ttl_seconds=10)
        client, http_client = _wired_client(state, cache=cache)
        async with http_client:
            observation = await _refresh(client)
        assert observation.classification is AvailabilityClassification.DRAINING
        assert not is_fresh(observation, now=NOW)

    _run(run())


def test_not_yet_ready_declaration_is_classified_unavailable() -> None:
    async def run() -> None:
        state = AgentReadinessState(_snapshot(ready=False, draining=False))
        cache = CachedAgentAvailability(ttl_seconds=10)
        client, http_client = _wired_client(state, cache=cache)
        async with http_client:
            observation = await _refresh(client)
        assert observation.classification is AvailabilityClassification.UNAVAILABLE

    _run(run())


def test_wrong_credential_against_the_real_404_disguise_is_classified_unavailable() -> None:
    """The server hides its own existence (404, not 401/403) from an unauthenticated
    caller. Prove the real client resolves that real disguised response to
    UNAVAILABLE rather than crashing or misreading it as UNKNOWN -- the unit
    tests only ever exercise this 404 shape against the server in isolation
    (status-code assertion only) or against the client with a hand-built
    "wrong environment" document, never this exact real response body."""

    async def run() -> None:
        state = AgentReadinessState(_snapshot(ready=True))
        cache = CachedAgentAvailability(ttl_seconds=10)
        client, http_client = _wired_client(state, cache=cache, credential="not-the-real-secret")
        async with http_client:
            observation = await _refresh(client)
        assert observation.classification is AvailabilityClassification.UNAVAILABLE

    _run(run())


def test_redeployed_agent_with_changed_declaration_digest_is_classified_unavailable() -> None:
    """A real redeploy changes the declaration digest the running process
    reports; the Registry's expectation (built from the Registry artifact,
    not this process) is now stale relative to it. Proves the identity-match
    fail-closed path against a real, differently-declared server -- not a
    hand-edited fake document."""

    async def run() -> None:
        redeployed_state = AgentReadinessState(
            AgentReadinessSnapshot(
                environment=ENVIRONMENT,
                agent_id=AGENT_ID,
                declaration_revision="sprint-10-wire-contract-v2",
                declaration_digest="sha256:sprint-10-wire-contract-v2",
                capabilities=((CAPABILITY_NAME, CAPABILITY_VERSION),),
                accepted_command_contracts=COMMAND_CONTRACTS,
                produced_event_contracts=EVENT_CONTRACTS,
                ready=True,
                draining=False,
            )
        )
        cache = CachedAgentAvailability(ttl_seconds=10)
        client, http_client = _wired_client(redeployed_state, cache=cache)
        async with http_client:
            # Client still expects the pre-redeploy revision/digest (its
            # caller -- refresh_agent_availability -- reads these from the
            # Registry artifact, which is independent of the live process).
            observation = await _refresh(client)
        assert observation.classification is AvailabilityClassification.UNAVAILABLE

    _run(run())


def test_ready_observation_goes_stale_after_ttl_even_though_agent_stays_ready() -> None:
    """The real server keeps answering READY the whole time; staleness is a
    property of the cache's own clock, not of the server. Proves TTL expiry
    against a real refreshed-then-aged observation, not a hand-recorded one."""

    async def run() -> None:
        ticks = [0.0]
        state = AgentReadinessState(_snapshot(ready=True))
        cache = CachedAgentAvailability(ttl_seconds=5, monotonic_clock=lambda: ticks[0])
        client, http_client = _wired_client(state, cache=cache)
        async with http_client:
            fresh_observation = await _refresh(client)
            assert fresh_observation.classification is AvailabilityClassification.READY

            ticks[0] = 5.1  # past the 5-second TTL; no new refresh performed
            stale_observation = cache.observe(AGENT_ID, CAPABILITY_NAME, CAPABILITY_VERSION)
        assert stale_observation.classification is AvailabilityClassification.STALE
        assert not is_fresh(stale_observation, now=NOW)

    _run(run())


def test_never_refreshed_capability_is_unknown_not_unavailable() -> None:
    """A capability the Registry lists but this readiness client has never
    successfully queried (e.g. before the first periodic refresh completes)
    must fail closed as UNKNOWN, not be silently treated as any other state."""
    cache = CachedAgentAvailability(ttl_seconds=10)
    observation = cache.observe(AGENT_ID, CAPABILITY_NAME, CAPABILITY_VERSION)
    assert observation.classification is AvailabilityClassification.UNKNOWN
    assert not is_fresh(observation, now=NOW)
