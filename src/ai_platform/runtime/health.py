"""Backend-neutral liveness/readiness state."""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ReadinessSnapshot:
    ready: bool
    components: Mapping[str, bool]


class CoreReadinessPort(Protocol):
    async def snapshot(self) -> ReadinessSnapshot: ...


@dataclass(frozen=True, slots=True)
class StaticReadiness:
    ready: bool = True

    async def snapshot(self) -> ReadinessSnapshot:
        return ReadinessSnapshot(ready=self.ready, components={"reference": self.ready})


class CoreReadiness:
    """Bounded probes for core dependencies; Agent availability is excluded."""

    def __init__(
        self,
        probes: Mapping[str, Callable[[], Awaitable[bool]]],
        *,
        timeout_seconds: float,
    ) -> None:
        if not probes:
            raise ValueError("at least one core readiness probe is required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._probes = dict(probes)
        self._timeout_seconds = timeout_seconds

    async def snapshot(self) -> ReadinessSnapshot:
        names = tuple(self._probes)

        async def check(name: str) -> bool:
            try:
                return await asyncio.wait_for(self._probes[name](), timeout=self._timeout_seconds)
            except Exception:
                return False

        results = await asyncio.gather(*(check(name) for name in names))
        components = dict(zip(names, results, strict=True))
        return ReadinessSnapshot(ready=all(results), components=components)
