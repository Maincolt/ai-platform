"""Postgres implementation of `AutonomousStatePort` (ADR-0026, ADR-0028).

Reads and writes `agent.autonomous_kill_switch`, `agent.autonomous_role_budget`,
and `agent.autonomous_actions` (migration 0009). See
`src/ai_platform/ports/persistence/autonomous.py` for why this port has
no atomic "reserve" operation.
"""

from collections.abc import Mapping
from datetime import date, datetime

from psycopg.types.json import Jsonb

from ai_platform.adapters.persistence.connection import AsyncPsycopgPool
from ai_platform.ports.persistence.autonomous import DailyBudgetStatus
from ai_platform.ports.persistence.errors import PermanentPersistenceError


class PsycopgAutonomousStatePort:
    def __init__(self, pool: AsyncPsycopgPool) -> None:
        self._pool = pool

    async def is_kill_switch_engaged(self) -> bool:
        async with self._pool.connection() as connection:
            row = await (
                await connection.execute(
                    "SELECT engaged FROM agent.autonomous_kill_switch WHERE singleton_id = TRUE"
                )
            ).fetchone()
        if row is None:
            return False
        engaged = row[0]
        if not isinstance(engaged, bool):
            raise PermanentPersistenceError("Stored kill switch value is invalid.")
        return engaged

    async def get_daily_budget(self, *, role: str, today: date) -> DailyBudgetStatus:
        async with self._pool.connection() as connection:
            row = await (
                await connection.execute(
                    "SELECT actions_used, spend_cents_used "
                    "FROM agent.autonomous_role_budget WHERE role = %s AND day = %s",
                    (role, today),
                )
            ).fetchone()
        if row is None:
            return DailyBudgetStatus(actions_used=0, spend_cents_used=0)
        actions_used, spend_cents_used = row
        if not isinstance(actions_used, int) or not isinstance(spend_cents_used, int):
            raise PermanentPersistenceError("Stored autonomous budget usage is invalid.")
        return DailyBudgetStatus(actions_used=actions_used, spend_cents_used=spend_cents_used)

    async def record_budget_usage(
        self, *, role: str, today: date, actions: int, spend_cents: int
    ) -> None:
        async with self._pool.transaction() as connection:
            await connection.execute(
                """
                INSERT INTO agent.autonomous_role_budget (role, day, actions_used, spend_cents_used)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (role, day) DO UPDATE
                SET actions_used = agent.autonomous_role_budget.actions_used
                        + EXCLUDED.actions_used,
                    spend_cents_used = agent.autonomous_role_budget.spend_cents_used
                        + EXCLUDED.spend_cents_used
                """,
                (role, today, actions, spend_cents),
            )

    async def record_action(
        self,
        *,
        agent_deployment_id: str,
        role: str,
        action_type: str,
        target: str,
        inputs: Mapping[str, object],
        result_status: str,
        result_detail: str,
        occurred_at: datetime,
    ) -> None:
        async with self._pool.transaction() as connection:
            await connection.execute(
                """
                INSERT INTO agent.autonomous_actions (
                    agent_deployment_id, role, action_type, target, inputs,
                    result_status, result_detail, occurred_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    agent_deployment_id,
                    role,
                    action_type,
                    target,
                    Jsonb(dict(inputs)),
                    result_status,
                    result_detail,
                    occurred_at,
                ),
            )
