"""Bounded Kafka-protocol availability probe using the allowed Admin subset."""

import asyncio

from confluent_kafka import KafkaException
from confluent_kafka.admin import AdminClient

from ai_platform.adapters.event_bus.security import KafkaSecurityConfig


class KafkaBrokerHealth:
    """Check broker metadata without exposing administration to domain code."""

    def __init__(
        self,
        *,
        bootstrap_servers: str,
        client_id: str,
        security: KafkaSecurityConfig,
        timeout_seconds: float,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        config: dict[str, str | int | float | bool] = {
            "bootstrap.servers": bootstrap_servers,
            "client.id": client_id,
        }
        config.update(security.client_properties())
        try:
            self._client = AdminClient(config)
        except KafkaException, ValueError:
            raise RuntimeError("EVENT_BUS_CLIENT_START_FAILED") from None
        self._timeout_seconds = timeout_seconds

    async def check(self) -> bool:
        """Return false on any bounded metadata failure without leaking details."""
        try:
            await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.list_topics,
                    timeout=self._timeout_seconds,
                ),
                timeout=self._timeout_seconds,
            )
        except KafkaException, TimeoutError:
            return False
        return True

    async def require_available(self) -> None:
        if not await self.check():
            raise RuntimeError("EVENT_BUS_UNAVAILABLE")
