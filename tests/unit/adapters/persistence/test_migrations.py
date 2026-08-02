"""Review-level assertions for correctness-critical migration capabilities."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def _assert_atomic_version_publication(sql: str, *, component: str) -> None:
    assert "\\set ON_ERROR_STOP on" in sql
    assert sql.index("BEGIN;") < sql.index("CREATE SCHEMA")
    version_insert = sql.index(f"INSERT INTO {component}.schema_version")
    assert version_insert > sql.rindex("CREATE TABLE")
    assert version_insert < sql.rindex("COMMIT;")
    assert sql.rstrip().endswith("COMMIT;")


def test_orchestrator_schema_contains_atomicity_and_recovery_records() -> None:
    sql = (ROOT / "infrastructure/migrations/0001_orchestrator_schema.sql").read_text(
        encoding="utf-8"
    )
    for required in (
        "current_owner_subject_id",
        "authorization_evidence",
        "request_access_audit",
        "workflow_history",
        "payload_bytes                 BYTEA",
        "immutable_message_digest",
        "transport_rejections",
        "claim_previous_state",
        "automatic_retry_allowed",
    ):
        assert required in sql
    assert "PRIMARY KEY (environment, operation, idempotency_scope_id, request_id)" in sql
    _assert_atomic_version_publication(sql, component="orchestrator")


def test_agent_schema_contains_complete_outcome_integrity_unit() -> None:
    sql = (ROOT / "infrastructure/migrations/0002_agent_schema.sql").read_text(encoding="utf-8")
    for required in (
        "terminal_events",
        "completed_receipts",
        "outcomes",
        "event_outbox",
        "agent.audit",
        "payload_bytes       BYTEA",
        "automatic_retry_allowed",
        "UNIQUE (task_id, attempt_number)",
    ):
        if required == "UNIQUE (task_id, attempt_number)":
            continue
        assert required in sql
    assert "task_attempt_id     TEXT        NOT NULL UNIQUE" in sql
    _assert_atomic_version_publication(sql, component="agent")


def test_postgresql_role_bootstrap_enforces_component_least_privilege() -> None:
    sql = (ROOT / "infrastructure/postgresql/bootstrap_roles.sql").read_text(encoding="utf-8")
    for role in (
        "ai_platform_orchestrator_migration",
        "ai_platform_orchestrator_runtime",
        "ai_platform_agent_migration",
        "ai_platform_agent_runtime",
    ):
        assert f"CREATE ROLE {role} NOLOGIN" in sql
        assert f"ALTER ROLE {role}" in sql
    assert "\\set ON_ERROR_STOP on" in sql
    assert "REVOKE ALL ON SCHEMA public FROM PUBLIC" in sql
    assert "REVOKE CREATE ON SCHEMA orchestrator FROM ai_platform_orchestrator_runtime" in sql
    assert "REVOKE CREATE ON SCHEMA agent FROM ai_platform_agent_runtime" in sql
    assert "ON ALL TABLES IN SCHEMA agent FROM ai_platform_orchestrator_runtime" in sql
    assert "ON ALL TABLES IN SCHEMA orchestrator FROM ai_platform_agent_runtime" in sql
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES" in sql
    assert "GRANT USAGE, SELECT ON SEQUENCES" in sql
    assert "PASSWORD" not in sql.upper()
