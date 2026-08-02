"""Focused tests for bounded process lifecycle coordination."""

import asyncio
from collections.abc import Awaitable

import pytest

from ai_platform.runtime.lifecycle import LifecycleError, LifecycleState, ProcessLifecycle
from ai_platform.runtime.readiness import AgentReadinessSnapshot, AgentReadinessState
from ai_platform.shared.identifiers import AgentId


class _Resource:
    def __init__(self, name: str, events: list[str], *, fail: bool = False) -> None:
        self._name = name
        self._events = events
        self._fail = fail

    async def open(self) -> None:
        self._events.append(f"open:{self._name}")
        if self._fail:
            raise RuntimeError("unavailable")

    async def close(self) -> None:
        self._events.append(f"close:{self._name}")


class _Service:
    def __init__(self, name: str, events: list[str]) -> None:
        self._name = name
        self._events = events
        self._stopping = asyncio.Event()

    async def run(self) -> None:
        self._events.append(f"run:{self._name}")
        await self._stopping.wait()

    async def stop(self) -> None:
        self._events.append(f"stop:{self._name}")
        self._stopping.set()

    async def close(self, *, timeout_seconds: float) -> bool:
        self._events.append(f"close:{self._name}")
        return timeout_seconds > 0


def _run(awaitable: Awaitable[object]) -> object:
    return asyncio.run(awaitable)


def test_platform_lifecycle_starts_from_durable_dependencies_without_agent_gate() -> None:
    events: list[str] = []
    lifecycle = ProcessLifecycle(
        resources=(_Resource("database", events), _Resource("event-bus", events)),
        services=(_Service("workflow-api", events),),
        startup_timeout_seconds=1,
        shutdown_timeout_seconds=1,
    )

    async def exercise() -> None:
        await lifecycle.start()
        assert lifecycle.state is LifecycleState.RUNNING
        assert events[:3] == ["open:database", "open:event-bus", "run:workflow-api"]
        assert await lifecycle.stop()

    _run(exercise())


def test_agent_readiness_is_set_after_start_and_draining_before_stop() -> None:
    events: list[str] = []
    state = AgentReadinessState(
        AgentReadinessSnapshot(
            environment="development",
            agent_id=AgentId("018f23a7-6b4d-7c91-8a2e-123456789abc"),
            declaration_revision="sprint-6",
            declaration_digest="sha256:declaration",
            capabilities=(("test.echo", "1.0"),),
            accepted_command_contracts=(("ExecuteTask", "1.0"),),
            produced_event_contracts=(
                ("TaskCompleted", "1.0"),
                ("TaskFailed", "1.0"),
            ),
            ready=False,
            draining=False,
        )
    )
    lifecycle = ProcessLifecycle(
        resources=(_Resource("database", events), _Resource("event-bus", events)),
        services=(_Service("agent-worker", events),),
        startup_timeout_seconds=1,
        shutdown_timeout_seconds=1,
        on_started=lambda: state.set_ready(True),
        on_stopping=state.start_draining,
        on_service_failure=lambda: state.set_ready(False),
    )

    async def exercise() -> None:
        assert not state.snapshot().ready
        await lifecycle.start()
        assert state.snapshot().ready
        assert await lifecycle.stop()
        snapshot = state.snapshot()
        assert not snapshot.ready
        assert snapshot.draining

    _run(exercise())


def test_startup_failure_unwinds_opened_resources_in_reverse_order() -> None:
    events: list[str] = []
    lifecycle = ProcessLifecycle(
        resources=(
            _Resource("database", events),
            _Resource("event-bus", events, fail=True),
        ),
        services=(),
        startup_timeout_seconds=1,
        shutdown_timeout_seconds=1,
    )

    with pytest.raises(LifecycleError, match="PROCESS_START_FAILED"):
        _run(lifecycle.start())

    assert lifecycle.state is LifecycleState.FAILED
    assert events == ["open:database", "open:event-bus", "close:database"]
