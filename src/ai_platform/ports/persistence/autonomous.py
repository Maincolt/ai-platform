"""Durable state for autonomous, non-Workflow-driven Agent write actions
(ADR-0026, ADR-0028).

Deliberately simple CRUD-shaped operations, not an atomic
"reserve-and-check" call: `PeriodicService` runs one cycle to completion
before starting the next (`src/ai_platform/runtime/lifecycle.py`), so
there is never more than one in-flight cycle for a given autonomous role
-- no concurrent-writer race to guard against, unlike the
Workflow/Kafka-redelivery ports elsewhere in this codebase. Business
logic (deciding whether today's budget allows another action) lives in
the calling Agent, not buried in this port.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DailyBudgetStatus:
    """Today's cumulative usage for one autonomous role. Zero counters
    when no row exists yet for (role, today) -- a role with no recorded
    usage today has spent nothing, not an unknown/error state."""

    actions_used: int
    spend_cents_used: int


class AutonomousStatePort(Protocol):
    async def is_kill_switch_engaged(self) -> bool:
        """Platform-wide kill switch (ADR-0026 Decision 7). Checked first,
        before any GitHub call, every cycle. Fails open to `False`
        (not engaged) only when no row exists at all -- migration 0009
        always seeds exactly one row, so this should never be reached
        in practice."""
        ...

    async def get_daily_budget(self, *, role: str, today: date) -> DailyBudgetStatus:
        """Today's cumulative actions/spend for `role`."""
        ...

    async def record_budget_usage(
        self, *, role: str, today: date, actions: int, spend_cents: int
    ) -> None:
        """Add to today's counters, creating the row if absent."""
        ...

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
        """Append one row to the audit log (ADR-0026 Decision 7) -- one
        row per attempted action, win or lose, never updated or deleted."""
        ...
