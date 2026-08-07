"""Smoke tests proving the external-service fixtures work end to end.

These are deliberately minimal: they only prove that `tests/integration/conftest.py`
can reach the real local PostgreSQL and Kafka topology from
`infrastructure/compose/`. The actual Section 19/20 external-service test
scenarios (Phase 7 of docs/implementation/vertical-slice-01.md) are built on
top of this scaffolding in later work.
"""

from __future__ import annotations

from typing import Any

import pytest
from confluent_kafka.admin import AdminClient

pytestmark = pytest.mark.external_service

# ADR-0005 Section 6's topic shape, provisioned by
# infrastructure/compose/scripts/init-kafka.sh. `task-commands` itself is
# capability-scoped at the physical-topic level since Sprint 9 (ADR-0014
# Section 6): one pair per built-in capability, not one shared pair.
_EXPECTED_TOPICS = {
    "ai-platform.development.task-commands.text-word-count.v1",
    "ai-platform.development.task-commands.text-word-count.v1.quarantine",
    "ai-platform.development.task-commands.text-summarize.v1",
    "ai-platform.development.task-commands.text-summarize.v1.quarantine",
    "ai-platform.development.task-outcomes.v1",
    "ai-platform.development.task-outcomes.v1.quarantine",
}


def test_postgres_select_1(postgres_connection: Any) -> None:
    with postgres_connection.cursor() as cur:
        cur.execute("SELECT 1")
        row = cur.fetchone()
    assert row == (1,)


def test_postgres_ai_platform_database_selected(postgres_connection: Any) -> None:
    with postgres_connection.cursor() as cur:
        cur.execute("SELECT current_database()")
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "ai_platform"


def test_kafka_admin_can_list_adr0005_topics(kafka_admin_client: AdminClient) -> None:
    metadata = kafka_admin_client.list_topics(timeout=10)
    topic_names = set(metadata.topics.keys())
    missing = _EXPECTED_TOPICS - topic_names
    assert not missing, (
        f"Expected ADR-0005/ADR-0014 topics missing from Kafka: {missing}. "
        "Has 'podman compose up kafka-init' been run "
        "(see infrastructure/README.md)?"
    )
