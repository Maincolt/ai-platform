"""Focused SQL-boundary tests for terminal inbox identity and coupled audit."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

from ai_platform.adapters.persistence.connection import AsyncDbConnection, AsyncPsycopgPool
from ai_platform.adapters.persistence.orchestrator import PsycopgOrchestratorPersistence
from ai_platform.orchestrator.domain.audit import AuditRecord
from ai_platform.ports.persistence.transactions import (
    TerminalOutcomeIntent,
    TerminalPersistenceDisposition,
)
from ai_platform.shared.identifiers import (
    ActorId,
    CorrelationId,
    MessageId,
    TaskAttemptId,
    TaskId,
    WorkflowId,
)
from ai_platform.shared.outcomes import AgentOutcome

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)


class _Cursor:
    def __init__(
        self,
        row: tuple[object, ...] | None = None,
        rows: list[tuple[object, ...]] | None = None,
    ) -> None:
        self._row = row
        self._rows = rows or []
        self.rowcount = 1

    async def fetchone(self) -> tuple[object, ...] | None:
        return self._row

    async def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows


class _TerminalConnection:
    def __init__(
        self,
        *,
        workflow_row: tuple[object, ...] | None,
        history_rows: list[tuple[object, ...]] | None = None,
        inbox_row: tuple[object, ...] | None = None,
        attempt_row: tuple[object, ...] | None = None,
    ) -> None:
        self.workflow_row = workflow_row
        self.history_rows = history_rows or []
        self.inbox_row = inbox_row
        self.attempt_row = attempt_row
        self.queries: list[str] = []

    async def execute(self, query: object, params: object = None) -> _Cursor:
        del params
        rendered = str(query)
        self.queries.append(rendered)
        if "FROM orchestrator.workflows WHERE" in rendered:
            return _Cursor(self.workflow_row)
        if "FROM orchestrator.workflow_history" in rendered:
            return _Cursor(rows=self.history_rows)
        if "FROM orchestrator.inbox" in rendered:
            return _Cursor(self.inbox_row)
        if "FROM orchestrator.tasks t" in rendered:
            return _Cursor(self.attempt_row)
        return _Cursor()


class _AttemptConnection:
    def __init__(self, row: tuple[object, ...]) -> None:
        self.row = row
        self.queries: list[str] = []

    async def execute(self, query: object, params: object = None) -> _Cursor:
        del params
        self.queries.append(str(query))
        return _Cursor(self.row)


class _Pool:
    component_schema = "orchestrator"

    def __init__(self, connection: object) -> None:
        self.connection = connection
        self.transaction_entries = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncDbConnection]:
        self.transaction_entries += 1
        yield cast(AsyncDbConnection, self.connection)


class _IdentityTestAdapter(PsycopgOrchestratorPersistence):
    async def matches_attempt_for_test(
        self,
        connection: AsyncDbConnection,
        intent: TerminalOutcomeIntent,
    ) -> bool:
        return await self._matches_attempt(connection, intent)


def _intent() -> TerminalOutcomeIntent:
    workflow_id = WorkflowId("workflow-1")
    attempt_id = TaskAttemptId("attempt-1")
    return TerminalOutcomeIntent(
        environment="test",
        logical_consumer_id="orchestrator-outcomes-v1",
        validated_message_id=MessageId("event-1"),
        immutable_message_digest="digest-1",
        workflow_id=workflow_id,
        task_id=TaskId("task-1"),
        task_attempt_id=attempt_id,
        correlation_id=CorrelationId("correlation-1"),
        causation_message_id=MessageId("command-1"),
        producer_component="test-agent",
        producer_instance_id="agent-1",
        capability_name="text.word-count",
        capability_version="1.0",
        result_text="one two three",
        agent_evidence_component="test-agent",
        agent_evidence_instance_id="agent-1",
        outcome=AgentOutcome(
            task_attempt_id=attempt_id, completed_at=NOW, result_data={"word_count": 3}
        ),
        occurred_at=NOW,
        audit=AuditRecord(
            kind="workflow_terminal_outcome",
            workflow_id=workflow_id,
            occurred_at=NOW,
            actor_id=ActorId("system:outcome-consumer"),
        ),
    )


def test_first_seen_permanent_rejection_inbox_and_audit_share_transaction() -> None:
    connection = _TerminalConnection(workflow_row=None)
    pool = _Pool(connection)
    adapter = PsycopgOrchestratorPersistence(cast(AsyncPsycopgPool, pool))

    result = asyncio.run(adapter.apply_terminal_outcome(_intent()))

    assert result.disposition is TerminalPersistenceDisposition.PERMANENT_CONFLICT
    assert pool.transaction_entries == 1
    assert sum("INSERT INTO orchestrator.inbox" in query for query in connection.queries) == 1
    assert sum("audit (" in query for query in connection.queries) == 1


def test_first_seen_late_inbox_and_audit_share_transaction() -> None:
    connection = _TerminalConnection(
        workflow_row=(
            "workflow-1",
            "request-1",
            "correlation-1",
            "COMPLETED",
            4,
            {"word_count": 3},
            None,
            None,
        ),
        history_rows=[("DISPATCHED", "COMPLETED", 4, NOW, "task_completed")],
        attempt_row=(
            "test-agent",
            "agent-1",
            "text.word-count",
            "1.0",
            "command-1",
            b'{"payload":{"input":"one two three"}}',
        ),
    )
    pool = _Pool(connection)
    adapter = PsycopgOrchestratorPersistence(cast(AsyncPsycopgPool, pool))

    result = asyncio.run(adapter.apply_terminal_outcome(_intent()))

    assert result.disposition is TerminalPersistenceDisposition.LATE_AFTER_TERMINAL
    assert pool.transaction_entries == 1
    assert sum("INSERT INTO orchestrator.inbox" in query for query in connection.queries) == 1
    assert sum("audit (" in query for query in connection.queries) == 1


def test_duplicate_inbox_does_not_append_another_audit() -> None:
    intent = _intent()
    connection = _TerminalConnection(
        workflow_row=None,
        inbox_row=(
            intent.immutable_message_digest,
            str(intent.workflow_id),
            str(intent.task_attempt_id),
            "permanent_conflict",
        ),
    )
    pool = _Pool(connection)
    adapter = PsycopgOrchestratorPersistence(cast(AsyncPsycopgPool, pool))

    result = asyncio.run(adapter.apply_terminal_outcome(intent))

    assert result.disposition is TerminalPersistenceDisposition.DUPLICATE
    assert all("INSERT INTO orchestrator.audit" not in query for query in connection.queries)


def test_attempt_match_uses_recorded_component_instance_and_causation() -> None:
    connection = _AttemptConnection(
        (
            "test-agent",
            "agent-1",
            "text.word-count",
            "1.0",
            "command-1",
            b'{"payload":{"input":"one two three"}}',
        )
    )
    intent = _intent()
    adapter = _IdentityTestAdapter(cast(AsyncPsycopgPool, _Pool(connection)))

    assert asyncio.run(
        adapter.matches_attempt_for_test(cast(AsyncDbConnection, connection), intent)
    )
    for mismatch in (
        replace(intent, producer_component="other-component"),
        replace(intent, producer_instance_id="other-agent"),
        replace(intent, capability_name="other-capability"),
        replace(intent, capability_version="2.0"),
        replace(intent, causation_message_id=MessageId("other-command")),
        replace(intent, result_text="changed text"),
        replace(intent, agent_evidence_component="other-component"),
        replace(intent, agent_evidence_instance_id="other-agent"),
    ):
        assert not asyncio.run(
            adapter.matches_attempt_for_test(cast(AsyncDbConnection, connection), mismatch)
        )
    assert all("a.implementation_identity" in query for query in connection.queries)
