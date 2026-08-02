"""Mocked PostgreSQL tests for authorization-safe accepted-request access audit."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import cast

from ai_platform.adapters.persistence.connection import AsyncDbConnection, AsyncPsycopgPool
from ai_platform.adapters.persistence.orchestrator import PsycopgOrchestratorPersistence
from ai_platform.orchestrator.domain.accepted_request import AcceptedRequestKey
from ai_platform.ports.persistence.transactions import (
    AcceptedRequestAccessAuditRecord,
    AcceptedRequestAccessDisposition,
)
from ai_platform.shared.identifiers import (
    ActorId,
    CorrelationId,
    IdempotencyScopeId,
    OwnerSubjectId,
    RequestId,
    WorkflowId,
)

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


class _Cursor:
    rowcount = 1


class _Connection:
    def __init__(self) -> None:
        self.query = ""
        self.params: object = None

    async def execute(self, query: object, params: object = None) -> _Cursor:
        self.query = str(query)
        self.params = params
        return _Cursor()


class _Pool:
    component_schema = "orchestrator"

    def __init__(self, connection: _Connection) -> None:
        self.connection = connection
        self.transaction_entries = 0

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncDbConnection]:
        self.transaction_entries += 1
        yield cast(AsyncDbConnection, self.connection)


def test_access_evidence_is_appended_in_its_own_durable_transaction() -> None:
    connection = _Connection()
    pool = _Pool(connection)
    adapter = PsycopgOrchestratorPersistence(cast(AsyncPsycopgPool, pool))
    record = AcceptedRequestAccessAuditRecord(
        key=AcceptedRequestKey(
            environment="development",
            operation="workflow.submit",
            idempotency_scope_id=IdempotencyScopeId("scope-1"),
            request_id=RequestId("request-1"),
        ),
        workflow_id=WorkflowId("workflow-1"),
        current_actor_id=ActorId("actor-2"),
        resolved_owner_subject_id=OwnerSubjectId("owner-1"),
        effective_correlation_id=CorrelationId("correlation-2"),
        policy_identity="local-policy",
        policy_revision="2",
        policy_decision="allow",
        scope_mapping_revision="1",
        authorization_evidence="authorized",
        disposition=AcceptedRequestAccessDisposition.EQUIVALENT_REPLAY_AUTHORIZED,
        occurred_at=NOW,
    )

    asyncio.run(adapter.record_request_access(record))

    assert pool.transaction_entries == 1
    assert "INSERT INTO orchestrator.request_access_audit" in connection.query
    assert isinstance(connection.params, tuple)
    params = cast(tuple[object, ...], connection.params)
    assert record.current_actor_id in params
    assert record.disposition.value in params
