"""Platform process entry point."""

import asyncio

from ai_platform.runtime.composition import build_platform_process
from ai_platform.runtime.configuration import PlatformRuntimeConfig
from ai_platform.shared.logging import configure_json_logging


async def _run() -> None:
    process = build_platform_process(PlatformRuntimeConfig.from_environment())
    await process.start()
    try:
        await process.wait_for_exit()
    finally:
        if not await process.stop():
            raise RuntimeError("PLATFORM_SHUTDOWN_INCOMPLETE")


def main() -> None:
    configure_json_logging()
    asyncio.run(_run())


if __name__ == "__main__":
    main()
