"""Testable bounded process lifecycle independent of any ASGI server."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from enum import Enum
from time import monotonic
from typing import Protocol


class AsyncResource(Protocol):
    async def open(self) -> None: ...

    async def close(self) -> None: ...


class ManagedService(Protocol):
    async def run(self) -> None: ...

    async def stop(self) -> None: ...

    async def close(self, *, timeout_seconds: float) -> bool: ...


class LifecycleState(Enum):
    NEW = "NEW"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class LifecycleError(RuntimeError):
    """A bounded lifecycle transition could not complete safely."""


class ProcessLifecycle:
    """Open resources, supervise services, and unwind them in reverse order."""

    def __init__(
        self,
        *,
        resources: Sequence[AsyncResource],
        services: Sequence[ManagedService],
        startup_timeout_seconds: float,
        shutdown_timeout_seconds: float,
        on_started: Callable[[], None] | None = None,
        on_stopping: Callable[[], None] | None = None,
        on_service_failure: Callable[[], None] | None = None,
    ) -> None:
        if startup_timeout_seconds <= 0 or shutdown_timeout_seconds <= 0:
            raise ValueError("lifecycle timeouts must be positive")
        self._resources = tuple(resources)
        self._services = tuple(services)
        self._startup_timeout_seconds = startup_timeout_seconds
        self._shutdown_timeout_seconds = shutdown_timeout_seconds
        self._on_started = on_started
        self._on_stopping = on_stopping
        self._on_service_failure = on_service_failure
        self._state = LifecycleState.NEW
        self._opened_resources: list[AsyncResource] = []
        self._tasks: list[asyncio.Task[None]] = []
        self._transition_lock = asyncio.Lock()
        self._exit_requested = asyncio.Event()

    @property
    def state(self) -> LifecycleState:
        return self._state

    @property
    def healthy(self) -> bool:
        return self._state is LifecycleState.RUNNING and not self._exit_requested.is_set()

    async def start(self) -> None:
        async with self._transition_lock:
            if self._state is not LifecycleState.NEW:
                raise LifecycleError("PROCESS_ALREADY_STARTED")
            self._state = LifecycleState.STARTING
            deadline = monotonic() + self._startup_timeout_seconds
            try:
                for resource in self._resources:
                    await self._within_deadline(resource.open(), deadline)
                    self._opened_resources.append(resource)
                for index, service in enumerate(self._services):
                    task = asyncio.create_task(
                        service.run(),
                        name=f"runtime-service-{index}",
                    )
                    task.add_done_callback(self._service_completed)
                    self._tasks.append(task)
                await asyncio.sleep(0)
                if any(task.done() for task in self._tasks):
                    raise LifecycleError("SERVICE_EXITED_DURING_STARTUP")
                self._state = LifecycleState.RUNNING
                if self._on_started is not None:
                    self._on_started()
            except BaseException:
                self._state = LifecycleState.FAILED
                await self._rollback_startup(monotonic() + self._shutdown_timeout_seconds)
                raise LifecycleError("PROCESS_START_FAILED") from None

    async def wait_for_exit(self) -> None:
        """Wait until a service exits unexpectedly or shutdown is requested."""
        await self._exit_requested.wait()

    async def stop(self) -> bool:
        async with self._transition_lock:
            if self._state is LifecycleState.STOPPED:
                return True
            if self._state is LifecycleState.NEW:
                self._state = LifecycleState.STOPPED
                self._exit_requested.set()
                return True
            self._state = LifecycleState.STOPPING
            self._exit_requested.set()
            if self._on_stopping is not None:
                self._on_stopping()

            deadline = monotonic() + self._shutdown_timeout_seconds
            clean = True
            for service in self._services:
                clean = await self._stop_service(service, deadline) and clean
            clean = await self._finish_tasks(deadline) and clean
            for service in reversed(self._services):
                clean = await self._close_service(service, deadline) and clean
            for resource in reversed(self._opened_resources):
                clean = await self._close_resource(resource, deadline) and clean
            self._opened_resources.clear()
            self._state = LifecycleState.STOPPED if clean else LifecycleState.FAILED
            return clean

    def _service_completed(self, task: asyncio.Task[None]) -> None:
        if self._state is not LifecycleState.RUNNING:
            return
        self._exit_requested.set()
        if self._on_service_failure is not None:
            self._on_service_failure()

    async def _rollback_startup(self, deadline: float) -> None:
        self._exit_requested.set()
        for service in self._services:
            await self._stop_service(service, deadline)
        await self._finish_tasks(deadline)
        for service in reversed(self._services):
            await self._close_service(service, deadline)
        for resource in reversed(self._opened_resources):
            await self._close_resource(resource, deadline)
        self._opened_resources.clear()

    async def _finish_tasks(self, deadline: float) -> bool:
        if not self._tasks:
            return True
        remaining = deadline - monotonic()
        if remaining <= 0:
            for task in self._tasks:
                task.cancel()
            return False
        _done, pending = await asyncio.wait(self._tasks, timeout=remaining)
        clean = not pending
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for task in self._tasks:
            if task.cancelled():
                continue
            try:
                exception = task.exception()
            except asyncio.InvalidStateError:
                clean = False
            else:
                clean = exception is None and clean
        self._tasks.clear()
        return clean

    async def _stop_service(self, service: ManagedService, deadline: float) -> bool:
        try:
            await self._within_deadline(service.stop(), deadline)
        except BaseException:
            return False
        return True

    async def _close_service(self, service: ManagedService, deadline: float) -> bool:
        remaining = deadline - monotonic()
        if remaining <= 0:
            return False
        try:
            return await asyncio.wait_for(
                service.close(timeout_seconds=remaining),
                timeout=remaining,
            )
        except BaseException:
            return False

    async def _close_resource(self, resource: AsyncResource, deadline: float) -> bool:
        try:
            await self._within_deadline(resource.close(), deadline)
        except BaseException:
            return False
        return True

    @staticmethod
    async def _within_deadline(awaitable: Awaitable[object], deadline: float) -> None:
        task = asyncio.ensure_future(awaitable)
        remaining = deadline - monotonic()
        if remaining <= 0:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise TimeoutError
        await asyncio.wait_for(task, timeout=remaining)


class PeriodicService:
    """Run one bounded asynchronous operation immediately and periodically."""

    def __init__(
        self,
        operation: Callable[[], Awaitable[object]],
        *,
        interval_seconds: float,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._operation = operation
        self._interval_seconds = interval_seconds
        self._stopping = asyncio.Event()

    async def run(self) -> None:
        while not self._stopping.is_set():
            await self._operation()
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    self._stopping.wait(),
                    timeout=self._interval_seconds,
                )

    async def stop(self) -> None:
        self._stopping.set()

    async def close(self, *, timeout_seconds: float) -> bool:
        if timeout_seconds <= 0:
            return False
        self._stopping.set()
        return True
