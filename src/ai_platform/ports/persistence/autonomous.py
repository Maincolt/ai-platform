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


@dataclass(frozen=True, slots=True)
class RoleBudgetRecord:
    """One role's today-usage row, for a caller listing every role at
    once (ADR-0032) rather than asking about one specific role
    (`get_daily_budget`). Only roles with an actual row are included --
    the caller decides how to treat a role with none (zero usage, same
    convention `DailyBudgetStatus` already uses for a single role)."""

    role: str
    actions_used: int
    spend_cents_used: int


@dataclass(frozen=True, slots=True)
class AutonomousActionRecord:
    """One audit-log row, for a caller listing recent actions across
    every role (ADR-0032) rather than dispatching one. Deliberately
    excludes `inputs` -- it can carry arbitrary text sourced from
    untrusted fetched content (ADR-0032 Security) beyond what a single
    display field should hold. `result_detail` is included, bounded/
    truncated by the adapter (ADR-0035/ADR-0036): the market-observer
    roles' whole purpose is to surface this text (their finding
    summary), and it renders as plain, escaped text, not raw HTML, so
    the display-only risk is the same as any other AI-generated finding
    already shown elsewhere on this dashboard. This record is still
    meant for display, not full audit reconstruction (use
    `agent.autonomous_actions` directly via `psql` for that)."""

    occurred_at: datetime
    role: str
    action_type: str
    target: str
    result_status: str
    result_detail: str


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

    async def list_role_budgets(self, *, today: date) -> tuple[RoleBudgetRecord, ...]:
        """Every role with a budget row for `today` (ADR-0032) -- a
        dashboard-facing read across all roles at once, unlike
        `get_daily_budget`'s single-role query."""
        ...

    async def list_recent_actions(self, *, limit: int) -> tuple[AutonomousActionRecord, ...]:
        """The `limit` most recent audit-log rows across every role,
        newest first (ADR-0032)."""
        ...
