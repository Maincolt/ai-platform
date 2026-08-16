"""External-service test: `PsycopgAutonomousStatePort` (ADR-0026,
ADR-0028) round-trips against the real database -- the kill switch seed
row, budget accumulation across multiple calls, and the audit log.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest

from ai_platform.adapters.persistence.autonomous import PsycopgAutonomousStatePort
from ai_platform.adapters.persistence.connection import AsyncPsycopgPool

pytestmark = pytest.mark.external_service

# Must track `ai_platform.runtime.composition._EXPECTED_SCHEMA_VERSION`
# (see tests/integration/conftest.py's copy of this same constant/comment).
_EXPECTED_AGENT_SCHEMA_VERSION = 5


async def _open_agent_pool(dsn: str) -> AsyncPsycopgPool:
    pool = AsyncPsycopgPool(
        dsn,
        component_schema="agent",
        expected_schema_version=_EXPECTED_AGENT_SCHEMA_VERSION,
        min_size=1,
        max_size=3,
    )
    await pool.open()
    return pool


def test_kill_switch_seed_row_is_not_engaged_by_default(postgres_agent_app_dsn: str) -> None:
    async def run() -> None:
        pool = await _open_agent_pool(postgres_agent_app_dsn)
        try:
            state = PsycopgAutonomousStatePort(pool)
            assert await state.is_kill_switch_engaged() is False
        finally:
            await pool.close()

    asyncio.run(run())


def test_budget_usage_accumulates_across_calls(postgres_agent_app_dsn: str) -> None:
    async def run() -> None:
        pool = await _open_agent_pool(postgres_agent_app_dsn)
        try:
            state = PsycopgAutonomousStatePort(pool)
            role = f"sprint-test-role-{uuid.uuid7()}"
            today = datetime.now(UTC).date()

            initial = await state.get_daily_budget(role=role, today=today)
            assert initial.actions_used == 0
            assert initial.spend_cents_used == 0

            await state.record_budget_usage(role=role, today=today, actions=1, spend_cents=5)
            await state.record_budget_usage(role=role, today=today, actions=2, spend_cents=3)

            status = await state.get_daily_budget(role=role, today=today)
            assert status.actions_used == 3
            assert status.spend_cents_used == 8
        finally:
            await pool.close()

    asyncio.run(run())


def test_budget_is_isolated_per_day(postgres_agent_app_dsn: str) -> None:
    async def run() -> None:
        pool = await _open_agent_pool(postgres_agent_app_dsn)
        try:
            state = PsycopgAutonomousStatePort(pool)
            role = f"sprint-test-role-{uuid.uuid7()}"

            await state.record_budget_usage(
                role=role, today=datetime(2026, 1, 1, tzinfo=UTC).date(), actions=5, spend_cents=10
            )
            status_other_day = await state.get_daily_budget(
                role=role, today=datetime(2026, 1, 2, tzinfo=UTC).date()
            )

            assert status_other_day.actions_used == 0
            assert status_other_day.spend_cents_used == 0
        finally:
            await pool.close()

    asyncio.run(run())


def test_record_action_writes_a_durable_audit_row(postgres_agent_app_dsn: str) -> None:
    async def run() -> None:
        pool = await _open_agent_pool(postgres_agent_app_dsn)
        try:
            state = PsycopgAutonomousStatePort(pool)
            now = datetime.now(UTC)

            await state.record_action(
                agent_deployment_id="scrum-master-agent",
                role="scrum-master",
                action_type="set_status",
                target="PVTI_test",
                inputs={"status": "Done", "rationale": "integration test"},
                result_status="SUCCEEDED",
                result_detail="ok",
                occurred_at=now,
            )

            async with pool.connection() as connection:
                row = await (
                    await connection.execute(
                        "SELECT agent_deployment_id, role, action_type, target, "
                        "result_status, result_detail "
                        "FROM agent.autonomous_actions "
                        "WHERE target = %s ORDER BY id DESC LIMIT 1",
                        ("PVTI_test",),
                    )
                ).fetchone()
            assert row is not None
            assert row[0] == "scrum-master-agent"
            assert row[1] == "scrum-master"
            assert row[2] == "set_status"
            assert row[3] == "PVTI_test"
            assert row[4] == "SUCCEEDED"
            assert row[5] == "ok"
        finally:
            await pool.close()

    asyncio.run(run())
