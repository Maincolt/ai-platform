"""Adapter-owned Psycopg 3 asynchronous pool lifecycle."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from psycopg import AsyncConnection, sql
from psycopg_pool import AsyncConnectionPool

from ai_platform.adapters.persistence.errors import classify_psycopg_error
from ai_platform.ports.persistence.errors import PermanentPersistenceError

AsyncDbConnection = AsyncConnection[tuple[object, ...]]


class AsyncPsycopgPool:
    """Own one component role's bounded pool and schema compatibility gate."""

    def __init__(
        self,
        conninfo: str,
        *,
        component_schema: str,
        expected_schema_version: int = 1,
        min_size: int = 1,
        max_size: int = 5,
        timeout_seconds: float = 10.0,
    ) -> None:
        if component_schema not in {"orchestrator", "agent"}:
            raise ValueError("component_schema must be orchestrator or agent")
        if expected_schema_version < 1:
            raise ValueError("expected_schema_version must be positive")
        self.component_schema = component_schema
        self.expected_schema_version = expected_schema_version
        self._pool = AsyncConnectionPool(
            conninfo=conninfo,
            min_size=min_size,
            max_size=max_size,
            timeout=timeout_seconds,
            open=False,
            kwargs={"autocommit": False},
        )

    async def open(self) -> None:
        try:
            await self._pool.open(wait=True)
            async with self._pool.connection() as connection:
                row = await (
                    await connection.execute(
                        sql.SQL(
                            "SELECT version FROM {}.schema_version WHERE component = %s"
                        ).format(sql.Identifier(self.component_schema)),
                        (self.component_schema,),
                    )
                ).fetchone()
        except Exception as exc:
            await self._pool.close()
            raise classify_psycopg_error(exc) from exc
        if row is None or row[0] != self.expected_schema_version:
            await self._pool.close()
            actual = None if row is None else row[0]
            raise PermanentPersistenceError(
                f"Incompatible {self.component_schema} schema version: "
                f"expected {self.expected_schema_version}, got {actual}."
            )

    async def close(self) -> None:
        await self._pool.close()

    @asynccontextmanager
    async def connection(self) -> AsyncGenerator[AsyncDbConnection]:
        """Yield a pooled connection; transaction ownership stays in the adapter."""
        try:
            async with self._pool.connection() as connection:
                yield connection
        except Exception as exc:
            from ai_platform.ports.persistence.errors import PersistenceError

            if isinstance(exc, PersistenceError):
                raise
            raise classify_psycopg_error(exc) from exc

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncDbConnection]:
        """Commit one adapter-owned unit; classify connection loss at commit separately."""
        async with self.connection() as connection:
            try:
                yield connection
            except Exception:
                await connection.rollback()
                raise
            try:
                await connection.commit()
            except Exception as exc:
                raise classify_psycopg_error(exc, commit_started=True) from exc
