"""Authenticated local Agent readiness endpoint and bounded observation cache."""

import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from time import monotonic
from typing import cast

import httpx
from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse

from ai_platform.orchestrator.registry.availability import (
    AvailabilityClassification,
    AvailabilityObservation,
    AvailabilityPort,
)
from ai_platform.shared.identifiers import AgentId


@dataclass(frozen=True, slots=True)
class AgentReadinessSnapshot:
    environment: str
    agent_id: AgentId
    declaration_revision: str
    declaration_digest: str
    capabilities: tuple[tuple[str, str], ...]
    accepted_command_contracts: tuple[tuple[str, str], ...]
    produced_event_contracts: tuple[tuple[str, str], ...]
    ready: bool
    draining: bool


class AgentReadinessState:
    """Process-owned status updated by Agent startup and shutdown coordination."""

    def __init__(self, identity: AgentReadinessSnapshot) -> None:
        self._identity = identity
        self._ready = identity.ready
        self._draining = identity.draining
        self._lock = Lock()

    def set_ready(self, ready: bool) -> None:
        with self._lock:
            self._ready = ready

    def start_draining(self) -> None:
        with self._lock:
            self._draining = True
            self._ready = False

    def snapshot(self) -> AgentReadinessSnapshot:
        with self._lock:
            return AgentReadinessSnapshot(
                environment=self._identity.environment,
                agent_id=self._identity.agent_id,
                declaration_revision=self._identity.declaration_revision,
                declaration_digest=self._identity.declaration_digest,
                capabilities=self._identity.capabilities,
                accepted_command_contracts=self._identity.accepted_command_contracts,
                produced_event_contracts=self._identity.produced_event_contracts,
                ready=self._ready,
                draining=self._draining,
            )


def create_agent_readiness_app(*, state: AgentReadinessState, readiness_credential: str) -> FastAPI:
    """Create the restricted one-way-authenticated development endpoint."""

    if not readiness_credential:
        raise ValueError("readiness_credential must not be empty")
    app = FastAPI(title="AI Platform Test Agent Readiness", docs_url=None, redoc_url=None)

    @app.get("/health/ready")
    async def readiness(  # pyright: ignore[reportUnusedFunction]
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        expected = f"Bearer {readiness_credential}"
        if authorization is None or not hmac.compare_digest(authorization, expected):
            return JSONResponse(status_code=404, content={"status": "not_found"})
        snapshot = state.snapshot()
        status_code = 200 if snapshot.ready and not snapshot.draining else 503
        return JSONResponse(
            status_code=status_code,
            content={
                "environment": snapshot.environment,
                "agent_id": str(snapshot.agent_id),
                "declaration_revision": snapshot.declaration_revision,
                "declaration_digest": snapshot.declaration_digest,
                "capabilities": [
                    {"name": name, "version": version} for name, version in snapshot.capabilities
                ],
                "accepted_command_contracts": [
                    {"name": name, "version": version}
                    for name, version in snapshot.accepted_command_contracts
                ],
                "produced_event_contracts": [
                    {"name": name, "version": version}
                    for name, version in snapshot.produced_event_contracts
                ],
                "ready": snapshot.ready,
                "draining": snapshot.draining,
            },
        )

    return app


class CachedAgentAvailability(AvailabilityPort):
    """Synchronous Registry port backed by asynchronously refreshed observations."""

    def __init__(
        self,
        *,
        ttl_seconds: float,
        monotonic_clock: Callable[[], float] = monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._ttl_seconds = ttl_seconds
        self._monotonic_clock = monotonic_clock
        self._observations: dict[
            tuple[AgentId, str, str], tuple[AvailabilityObservation, float]
        ] = {}
        self._lock = Lock()

    def record(
        self,
        agent_id: AgentId,
        capability_name: str,
        capability_version: str,
        classification: AvailabilityClassification,
        *,
        observed_at: datetime,
    ) -> None:
        with self._lock:
            self._observations[(agent_id, capability_name, capability_version)] = (
                AvailabilityObservation(
                    classification=classification,
                    observed_at=observed_at,
                    ttl_seconds=self._ttl_seconds,
                ),
                self._monotonic_clock(),
            )

    def observe(
        self, agent_id: AgentId, capability_name: str, capability_version: str
    ) -> AvailabilityObservation:
        with self._lock:
            stored = self._observations.get((agent_id, capability_name, capability_version))
            if stored is None:
                return AvailabilityObservation(
                    classification=AvailabilityClassification.UNKNOWN,
                    observed_at=datetime.min.replace(tzinfo=UTC),
                    ttl_seconds=self._ttl_seconds,
                )
            observation, recorded_monotonic = stored
            elapsed = self._monotonic_clock() - recorded_monotonic
            if elapsed < 0 or elapsed > self._ttl_seconds:
                return AvailabilityObservation(
                    classification=AvailabilityClassification.STALE,
                    observed_at=observation.observed_at,
                    ttl_seconds=observation.ttl_seconds,
                )
            return observation


class AgentReadinessClient:
    """Refresh one trusted declaration-bound readiness observation."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        readiness_url: str,
        credential: str,
        cache: CachedAgentAvailability,
        timeout_seconds: float,
        maximum_response_bytes: int = 16_384,
    ) -> None:
        if not credential or timeout_seconds <= 0 or maximum_response_bytes < 1:
            raise ValueError("invalid readiness client bounds")
        self._client = client
        self._readiness_url = readiness_url
        self._credential = credential
        self._cache = cache
        self._timeout_seconds = timeout_seconds
        self._maximum_response_bytes = maximum_response_bytes

    async def refresh(
        self,
        *,
        environment: str,
        agent_id: AgentId,
        declaration_revision: str,
        declaration_digest: str,
        capability_name: str,
        capability_version: str,
        accepted_command_contracts: tuple[tuple[str, str], ...],
        produced_event_contracts: tuple[tuple[str, str], ...],
        now: datetime,
    ) -> AvailabilityObservation:
        classification = AvailabilityClassification.UNKNOWN
        try:
            raw = bytearray()
            async with self._client.stream(
                "GET",
                self._readiness_url,
                headers={
                    "Authorization": f"Bearer {self._credential}",
                    "Accept-Encoding": "identity",
                },
                timeout=self._timeout_seconds,
            ) as response:
                encoding = response.headers.get("Content-Encoding", "identity").lower()
                if encoding not in {"", "identity"}:
                    raise ValueError("readiness response encoding is not allowed")
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    try:
                        declared_length = int(content_length)
                    except ValueError:
                        raise ValueError("invalid readiness content length") from None
                    if declared_length < 0 or declared_length > self._maximum_response_bytes:
                        raise ValueError("readiness response exceeds configured bound")
                # Identity encoding makes decoded and wire bytes equivalent while
                # retaining streaming behavior for real transports and test doubles.
                async for chunk in response.aiter_bytes():
                    if len(raw) + len(chunk) > self._maximum_response_bytes:
                        raise ValueError("readiness response exceeds configured bound")
                    raw.extend(chunk)
            document_object: object = json.loads(
                raw.decode("utf-8", errors="strict"),
                object_pairs_hook=_reject_duplicate_properties,
            )
            if not isinstance(document_object, dict):
                raise ValueError("readiness response is not an object")
            document = cast(dict[str, object], document_object)
            capabilities = document.get("capabilities")
            expected_capability = {"name": capability_name, "version": capability_version}
            expected_commands = [
                {"name": name, "version": version} for name, version in accepted_command_contracts
            ]
            expected_events = [
                {"name": name, "version": version} for name, version in produced_event_contracts
            ]
            identity_matches = (
                document.get("environment") == environment
                and document.get("agent_id") == str(agent_id)
                and document.get("declaration_revision") == declaration_revision
                and document.get("declaration_digest") == declaration_digest
                and capabilities == [expected_capability]
                and document.get("accepted_command_contracts") == expected_commands
                and document.get("produced_event_contracts") == expected_events
            )
            if not identity_matches:
                classification = AvailabilityClassification.UNAVAILABLE
            elif response.status_code == 200 and document.get("ready") is True:
                classification = AvailabilityClassification.READY
            elif document.get("draining") is True:
                classification = AvailabilityClassification.DRAINING
            else:
                classification = AvailabilityClassification.UNAVAILABLE
        except httpx.HTTPError, UnicodeDecodeError, json.JSONDecodeError, ValueError:
            classification = AvailabilityClassification.UNKNOWN

        self._cache.record(
            agent_id,
            capability_name,
            capability_version,
            classification,
            observed_at=now,
        )
        return self._cache.observe(agent_id, capability_name, capability_version)


def _reject_duplicate_properties(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate readiness response property")
        result[key] = value
    return result
