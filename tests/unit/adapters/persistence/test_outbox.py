"""Mocked async SQL tests for fenced outbox recovery."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from ai_platform.adapters.persistence._outbox_common import (
    claim_next,
    record_publication_result,
    release_claim,
)
from ai_platform.adapters.persistence.connection import AsyncDbConnection
from ai_platform.ports.persistence.errors import PersistenceConflictError
from ai_platform.ports.persistence.outbox import PublicationDisposition
from ai_platform.shared.identifiers import MessageId
from ai_platform.shared.recovery import PublicationState

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


class _Cursor:
    def __init__(self, row: tuple[object, ...] | None, *, rowcount: int = 1) -> None:
        self._row = row
        self.rowcount = rowcount

    async def fetchone(self) -> tuple[object, ...] | None:
        return self._row


class _Connection:
    def __init__(self, cursors: list[_Cursor]) -> None:
        self._cursors = cursors
        self.queries: list[str] = []
        self.parameters: list[object] = []

    async def execute(self, query: object, params: object = None) -> _Cursor:
        self.queries.append(str(query))
        self.parameters.append(params)
        return self._cursors.pop(0)


def test_claim_uses_database_time_skip_locked_and_preserves_exact_bytes() -> None:
    row: tuple[object, ...] = (
        "message-1",
        "workflow-1",
        "task-commands",
        "workflow-1",
        b'{"stable":true}',
        [["content-type", "YXBwbGljYXRpb24vanNvbg=="]],
        1,
        NOW,
        NOW + timedelta(seconds=30),
        2,
        "text.word-count",
    )
    fake = _Connection([_Cursor(None), _Cursor(row)])

    claimed = asyncio.run(
        claim_next(
            cast(AsyncDbConnection, fake),
            schema="orchestrator",
            logical_channel="task-commands",
            publisher_instance_id="publisher-1",
            fencing_token="fence-1",
            claim_ttl=timedelta(seconds=30),
        )
    )

    assert claimed is not None
    assert claimed.record.payload_bytes == b'{"stable":true}'
    assert claimed.record.headers == (("content-type", b"application/json"),)
    assert "publication_state = 'ATTEMPTED_UNKNOWN'" in fake.queries[0]
    assert "FOR UPDATE SKIP LOCKED" in fake.queries[1]
    assert "CURRENT_TIMESTAMP" in fake.queries[1]
    assert "current.automatic_retry_allowed" in fake.queries[1]
    assert "'FAILED'" not in fake.queries[1]
    assert "publication_attempts = claimed.publication_attempts + 1" in fake.queries[1]
    assert cast(tuple[object, ...], fake.parameters[1])[1] == 3


def test_stale_fencing_token_is_a_stable_conflict() -> None:
    fake = _Connection([_Cursor(None, rowcount=0)])
    disposition = PublicationDisposition(
        state=PublicationState.ACKNOWLEDGED,
        attempted_at=NOW,
        retryable=False,
    )

    with pytest.raises(PersistenceConflictError):
        asyncio.run(
            record_publication_result(
                cast(AsyncDbConnection, fake),
                schema="agent",
                message_id=MessageId("message-1"),
                disposition=disposition,
                fencing_token="stale",
            )
        )


def test_nonretryable_publication_result_is_stored_as_nonclaimable() -> None:
    fake = _Connection([_Cursor(None)])
    disposition = PublicationDisposition(
        state=PublicationState.ATTEMPTED_UNKNOWN,
        attempted_at=NOW,
        retryable=False,
        safe_failure_code="PERMANENT_FAILURE",
    )

    asyncio.run(
        record_publication_result(
            cast(AsyncDbConnection, fake),
            schema="orchestrator",
            message_id=MessageId("message-1"),
            disposition=disposition,
            fencing_token="fence-1",
        )
    )

    assert "automatic_retry_allowed = %s" in fake.queries[0]
    parameters = cast(tuple[object, ...], fake.parameters[0])
    assert parameters[0] == PublicationState.ATTEMPTED_UNKNOWN.value
    assert parameters[3] is False


def test_releasing_unattempted_claim_restores_attempt_budget() -> None:
    fake = _Connection([_Cursor(None)])

    asyncio.run(
        release_claim(
            cast(AsyncDbConnection, fake),
            schema="agent",
            message_id=MessageId("message-1"),
            fencing_token="fence-1",
        )
    )

    assert "publication_attempts = publication_attempts - 1" in fake.queries[0]
