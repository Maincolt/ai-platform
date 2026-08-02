"""Tests for bounded core readiness aggregation."""

import asyncio

from ai_platform.runtime.health import CoreReadiness


def test_all_core_probes_must_pass() -> None:
    async def run() -> None:
        async def available() -> bool:
            return True

        async def unavailable() -> bool:
            return False

        readiness = CoreReadiness(
            {"database": available, "event_bus": unavailable, "registry": available},
            timeout_seconds=0.1,
        )
        snapshot = await readiness.snapshot()
        assert not snapshot.ready
        assert snapshot.components == {
            "database": True,
            "event_bus": False,
            "registry": True,
        }

    asyncio.run(run())


def test_probe_timeout_fails_readiness_without_blocking() -> None:
    async def run() -> None:
        async def slow() -> bool:
            await asyncio.sleep(1)
            return True

        readiness = CoreReadiness({"database": slow}, timeout_seconds=0.001)
        snapshot = await readiness.snapshot()
        assert not snapshot.ready

    asyncio.run(run())
