"""Managed-service adapters used by concrete process composition."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Protocol

import uvicorn
from fastapi import FastAPI

from ai_platform.ports.event_bus import ShutdownResult
from ai_platform.runtime.publisher import OutboxPublisherWorker


class StartupGateResource:
    """Require one bounded dependency check before service tasks start."""

    def __init__(self, require_available: Callable[[], Awaitable[None]]) -> None:
        self._require_available = require_available

    async def open(self) -> None:
        await self._require_available()

    async def close(self) -> None:
        return None


class OutboxPublisherService:
    """Adapt the publisher worker's synchronous stop signal to lifecycle shape."""

    def __init__(self, worker: OutboxPublisherWorker) -> None:
        self._worker = worker

    async def run(self) -> None:
        await self._worker.run()

    async def stop(self) -> None:
        self._worker.stop()

    async def close(self, *, timeout_seconds: float) -> bool:
        return await self._worker.close(timeout_seconds=timeout_seconds)


class PublisherLifecyclePort(Protocol):
    def stop_accepting(self) -> None: ...

    def close(self, *, timeout_seconds: float) -> ShutdownResult: ...


class PassivePublisherService:
    """Give a coordinator-owned publisher a bounded process lifecycle."""

    def __init__(self, publisher: PublisherLifecyclePort) -> None:
        self._publisher = publisher
        self._stopping = asyncio.Event()

    async def run(self) -> None:
        await self._stopping.wait()

    async def stop(self) -> None:
        self._publisher.stop_accepting()
        self._stopping.set()

    async def close(self, *, timeout_seconds: float) -> bool:
        if timeout_seconds <= 0:
            return False
        result = await asyncio.to_thread(
            self._publisher.close,
            timeout_seconds=timeout_seconds,
        )
        return result.drained


class UvicornService:
    """ASGI server service; lifecycle orchestration remains server-independent."""

    def __init__(self, *, app: FastAPI, host: str, port: int) -> None:
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            loop="asyncio",
            lifespan="off",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        self._finished = False

    async def run(self) -> None:
        try:
            await self._server.serve()
        finally:
            self._finished = True

    async def stop(self) -> None:
        self._server.should_exit = True

    async def close(self, *, timeout_seconds: float) -> bool:
        return timeout_seconds > 0 and self._finished
