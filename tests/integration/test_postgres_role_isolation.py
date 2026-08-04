"""External-service PostgreSQL role-isolation and migration/runtime privilege
separation guarantees against the real local database.

These tests connect as the real least-privilege LOGIN roles provisioned by
`infrastructure/compose/scripts/init-postgres.sh`
(`ai_platform_{orchestrator,agent}_app`, `ai_platform_{orchestrator,agent}_migrator`)
rather than the `postgres` administrator, proving the Section 19 "Security
boundary" guarantee ("separate credentials and grants") that
`infrastructure/postgresql/bootstrap_roles.sql` only describes statically:

- each `_app` runtime login can read and write its own component schema but
  is denied any access to the other component's schema (`test_app_role_*`);
- each `_app` runtime login is denied DDL (`CREATE TABLE`) even in its own
  schema (`test_*_app_role_denied_ddl_in_own_schema`);
- each `_migrator` login cannot perform DDL until it explicitly `SET ROLE`s
  to its matching `NOLOGIN`, `INHERIT FALSE` migration role
  (`test_*_migrator_requires_set_role_for_ddl`).

Every probing DDL statement runs inside a transaction that is always rolled
back (never committed), so no schema change from these tests is ever
persisted against the shared database -- these tests only need the
permission check outcome, not a durable side effect.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest

pytestmark = pytest.mark.external_service


def _new_id() -> str:
    return str(uuid.uuid7())


# -- Runtime (`_app`) role isolation: own schema allowed, other schema denied --


def test_orchestrator_app_role_can_read_write_own_schema(
    postgres_orchestrator_app_dsn: str,
) -> None:
    workflow_id = _new_id()
    with psycopg.connect(postgres_orchestrator_app_dsn, connect_timeout=5) as connection:
        with connection.cursor() as cur:
            cur.execute(
                """
                INSERT INTO orchestrator.workflows
                    (workflow_id, request_id, correlation_id, state, revision,
                     created_at, updated_at)
                VALUES (%s, %s, %s, 'RECEIVED', 1, now(), now())
                """,
                (workflow_id, _new_id(), _new_id()),
            )
            cur.execute(
                "SELECT state FROM orchestrator.workflows WHERE workflow_id = %s",
                (workflow_id,),
            )
            row = cur.fetchone()
        connection.commit()
    assert row == ("RECEIVED",)


def test_orchestrator_app_role_denied_agent_schema(postgres_orchestrator_app_dsn: str) -> None:
    with psycopg.connect(postgres_orchestrator_app_dsn, connect_timeout=5) as connection:
        with (
            connection.cursor() as cur,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            cur.execute("SELECT 1 FROM agent.outcomes LIMIT 1")
        connection.rollback()

        with (
            connection.cursor() as cur,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            cur.execute(
                """
                INSERT INTO agent.terminal_events
                    (message_id, task_attempt_id, workflow_id, logical_channel,
                     ordering_key, payload_bytes, headers, creation_sequence, created_at)
                VALUES (%s, %s, %s, 'task-outcomes', %s, %s, '{}', 1, now())
                """,
                (_new_id(), _new_id(), _new_id(), _new_id(), b"{}"),
            )
        connection.rollback()


def test_agent_app_role_can_read_write_own_schema(postgres_agent_app_dsn: str) -> None:
    message_id = _new_id()
    with psycopg.connect(postgres_agent_app_dsn, connect_timeout=5) as connection:
        with connection.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agent.terminal_events
                    (message_id, task_attempt_id, workflow_id, logical_channel,
                     ordering_key, payload_bytes, headers, creation_sequence, created_at)
                VALUES (%s, %s, %s, 'task-outcomes', %s, %s, '{}', 1, now())
                """,
                (message_id, _new_id(), _new_id(), _new_id(), b"{}"),
            )
            cur.execute(
                "SELECT message_id FROM agent.terminal_events WHERE message_id = %s",
                (message_id,),
            )
            row = cur.fetchone()
        connection.commit()
    assert row == (message_id,)


def test_agent_app_role_denied_orchestrator_schema(postgres_agent_app_dsn: str) -> None:
    with psycopg.connect(postgres_agent_app_dsn, connect_timeout=5) as connection:
        with (
            connection.cursor() as cur,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            cur.execute("SELECT 1 FROM orchestrator.workflows LIMIT 1")
        connection.rollback()

        with (
            connection.cursor() as cur,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            cur.execute(
                """
                INSERT INTO orchestrator.workflows
                    (workflow_id, request_id, correlation_id, state, revision,
                     created_at, updated_at)
                VALUES (%s, %s, %s, 'RECEIVED', 1, now(), now())
                """,
                (_new_id(), _new_id(), _new_id()),
            )
        connection.rollback()


# -- Runtime (`_app`) roles are denied DDL, even in their own schema --


def test_orchestrator_app_role_denied_ddl_in_own_schema(
    postgres_orchestrator_app_dsn: str,
) -> None:
    with psycopg.connect(postgres_orchestrator_app_dsn, connect_timeout=5) as connection:
        with (
            connection.cursor() as cur,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            cur.execute("CREATE TABLE orchestrator._sprint7_ddl_probe (id INT)")
        connection.rollback()


def test_agent_app_role_denied_ddl_in_own_schema(postgres_agent_app_dsn: str) -> None:
    with psycopg.connect(postgres_agent_app_dsn, connect_timeout=5) as connection:
        with (
            connection.cursor() as cur,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            cur.execute("CREATE TABLE agent._sprint7_ddl_probe (id INT)")
        connection.rollback()


# -- Migration logins cannot DDL without an explicit `SET ROLE` --


def test_orchestrator_migrator_requires_set_role_for_ddl(
    postgres_orchestrator_migrator_dsn: str,
) -> None:
    with psycopg.connect(postgres_orchestrator_migrator_dsn, connect_timeout=5) as connection:
        with (
            connection.cursor() as cur,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            cur.execute("CREATE TABLE orchestrator._sprint7_ddl_probe (id INT)")
        connection.rollback()

        with connection.cursor() as cur:
            cur.execute("SET ROLE ai_platform_orchestrator_migration")
            cur.execute("CREATE TABLE orchestrator._sprint7_ddl_probe (id INT)")
            cur.execute("SELECT to_regclass('orchestrator._sprint7_ddl_probe') IS NOT NULL")
            row = cur.fetchone()
        # Never commit: this DDL must not persist past this test.
        connection.rollback()
    assert row == (True,)


def test_agent_migrator_requires_set_role_for_ddl(postgres_agent_migrator_dsn: str) -> None:
    with psycopg.connect(postgres_agent_migrator_dsn, connect_timeout=5) as connection:
        with (
            connection.cursor() as cur,
            pytest.raises(psycopg.errors.InsufficientPrivilege),
        ):
            cur.execute("CREATE TABLE agent._sprint7_ddl_probe (id INT)")
        connection.rollback()

        with connection.cursor() as cur:
            cur.execute("SET ROLE ai_platform_agent_migration")
            cur.execute("CREATE TABLE agent._sprint7_ddl_probe (id INT)")
            cur.execute("SELECT to_regclass('agent._sprint7_ddl_probe') IS NOT NULL")
            row = cur.fetchone()
        # Never commit: this DDL must not persist past this test.
        connection.rollback()
    assert row == (True,)
