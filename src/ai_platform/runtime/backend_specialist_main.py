"""Backend Specialist Agent process entry point (ADR-0026, ADR-0034)."""

import asyncio

from ai_platform.runtime.composition import build_backend_specialist_process
from ai_platform.runtime.configuration import BackendSpecialistRuntimeConfig
from ai_platform.shared.logging import configure_json_logging


async def _run() -> None:
    process = build_backend_specialist_process(BackendSpecialistRuntimeConfig.from_environment())
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
