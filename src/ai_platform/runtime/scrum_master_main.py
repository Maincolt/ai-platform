"""Scrum Master Agent process entry point (ADR-0026 Phase 2, ADR-0028)."""

import asyncio

from ai_platform.runtime.composition import build_scrum_master_process
from ai_platform.runtime.configuration import ScrumMasterRuntimeConfig
from ai_platform.shared.logging import configure_json_logging


async def _run() -> None:
    process = build_scrum_master_process(ScrumMasterRuntimeConfig.from_environment())
    await process.start()
    try:
        await process.wait_for_exit()
    finally:
        if not await process.stop():
            raise RuntimeError("AGENT_SHUTDOWN_INCOMPLETE")


def main() -> None:
    configure_json_logging()
    asyncio.run(_run())


if __name__ == "__main__":
    main()
