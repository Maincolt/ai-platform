"""Session-scoped scaffolding for external-service tests.

Tests under `tests/integration/` are external-service tests as defined by
`docs/testing/README.md`: they exercise the real PostgreSQL + Apache Kafka
topology from `infrastructure/compose/` (see `infrastructure/README.md`),
not fakes or in-process substitutes. They are opt-in via the
`external_service` pytest marker (excluded by default through `addopts` in
`pyproject.toml`).

The topology runs on a dedicated Docker host (a Mac at `192.168.1.123`, see
`infrastructure/README.md`/`docs/operations/README.md` Section 1), not on
whichever machine runs pytest. This module never brings the topology up or
tears it down itself — it only polls the already-running services and skips
with an actionable reason if they are unreachable within the timeout.
Bring the topology up first (over SSH into the Docker host; see
`docs/operations/README.md` Section 1) before running this suite.

Reading `infrastructure/compose/secrets/*.txt` (for the admin/principal
credentials below) requires those files to exist on whichever machine runs
pytest. Either run pytest from an SSH session on the Docker host itself (the
repo and its generated secrets both live there), or copy
`infrastructure/compose/secrets/` down to your own checkout.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
import pytest
from confluent_kafka.admin import AdminClient

pytestmark = pytest.mark.external_service

# psycopg's async mode cannot run under Windows' default ProactorEventLoop
# (raises NotImplementedError on the pipe/socket types it needs); tests here
# call `asyncio.run(...)` directly against AsyncPsycopgPool, so the policy
# must be set once, before any of those calls, for the whole session.
# WindowsSelectorEventLoopPolicy is deprecated (slated for removal in
# Python 3.16); this project pins 3.14 (pyproject.toml), so revisit this
# before any future upgrade past 3.15.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_DIR = REPO_ROOT / "infrastructure" / "compose"
SECRETS_DIR = COMPOSE_DIR / "secrets"

# The Docker host this topology runs on (see docs/operations/README.md
# Section 1) -- overridable for a different host/port layout.
DOCKER_HOST_LAN_IP = "192.168.1.123"

# Must track `ai_platform.runtime.composition._EXPECTED_SCHEMA_VERSION`,
# which is bumped alongside the latest applied
# `infrastructure/migrations/*.sql` for each component. A test-side
# `AsyncPsycopgPool` constructed with a stale value fails closed with
# PermanentPersistenceError against an up-to-date database, rather than
# silently reading data through mismatched assumptions -- see Sprint 10's
# topology re-validation, which caught these three call sites still
# defaulting to the class's `expected_schema_version=1` default after
# Sprint 9's migrations 0003-0007 shipped without these being updated.
EXPECTED_ORCHESTRATOR_SCHEMA_VERSION = 3
EXPECTED_AGENT_SCHEMA_VERSION = 4

# Overridable so this suite can run either against the Docker host's
# published ports (default) or from inside a container attached to the
# `ai-platform-local_default` compose network (internal service names/ports
# -- e.g. AI_PLATFORM_TEST_POSTGRES_HOST=postgres,
# AI_PLATFORM_TEST_POSTGRES_PORT=5432,
# AI_PLATFORM_TEST_KAFKA_BOOTSTRAP_SERVERS=kafka:9092), or against a
# different host entirely. Defaults point at the current Docker host
# (see infrastructure/README.md); when running pytest directly on that host
# (over SSH), "localhost" also works and is often faster.
POSTGRES_HOST = os.environ.get("AI_PLATFORM_TEST_POSTGRES_HOST", DOCKER_HOST_LAN_IP)
POSTGRES_PORT = int(os.environ.get("AI_PLATFORM_TEST_POSTGRES_PORT", "5433"))
POSTGRES_DATABASE = "ai_platform"

# The EXTERNAL SASL_PLAINTEXT/SCRAM-SHA-256 listener published by the Docker
# host -- see infrastructure/compose/kafka/entrypoint.sh. Tests running
# inside the compose network instead use "kafka:9092".
KAFKA_BOOTSTRAP_SERVERS = os.environ.get(
    "AI_PLATFORM_TEST_KAFKA_BOOTSTRAP_SERVERS", f"{DOCKER_HOST_LAN_IP}:19093"
)

READY_TIMEOUT_SECONDS = 120.0
POLL_INTERVAL_SECONDS = 2.0

_REQUIRED_SECRET_FILES = (
    "postgres_admin_password.txt",
    "kafka_admin_password.txt",
)


@dataclass(frozen=True, slots=True)
class ExternalServicesStatus:
    """Outcome of attempting to reach the real local PostgreSQL/Kafka topology."""

    ready: bool
    reason: str | None = None


def _secrets_present() -> bool:
    return all((SECRETS_DIR / name).is_file() for name in _REQUIRED_SECRET_FILES)


def _read_secret(name: str) -> str:
    return (SECRETS_DIR / name).read_text(encoding="utf-8").strip()


def _postgres_dsn() -> str:
    password = _read_secret("postgres_admin_password.txt")
    return f"postgresql://postgres:{password}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DATABASE}"


def _kafka_admin_config() -> dict[str, Any]:
    password = _read_secret("kafka_admin_password.txt")
    return {
        "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
        "security.protocol": "SASL_PLAINTEXT",
        "sasl.mechanism": "SCRAM-SHA-256",
        "sasl.username": "admin",
        "sasl.password": password,
    }


def _wait_for_postgres(deadline: float) -> str | None:
    dsn = _postgres_dsn()
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=5) as conn, conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            return None
        except Exception as exc:  # noqa: BLE001 - broad on purpose while polling
            last_error = exc
            time.sleep(POLL_INTERVAL_SECONDS)
    return f"PostgreSQL not reachable at {POSTGRES_HOST}:{POSTGRES_PORT}: {last_error}"


def _wait_for_kafka(deadline: float) -> str | None:
    config = _kafka_admin_config()
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            admin = AdminClient(config)
            admin.list_topics(timeout=5)
            return None
        except Exception as exc:  # noqa: BLE001 - broad on purpose while polling
            last_error = exc
        time.sleep(POLL_INTERVAL_SECONDS)
    return f"Kafka not reachable at {KAFKA_BOOTSTRAP_SERVERS}: {last_error}"


@pytest.fixture(scope="session")
def external_services_status() -> ExternalServicesStatus:
    """Check that the real PostgreSQL/Kafka topology on the Docker host is reachable.

    This never brings the topology up or tears it down itself -- it is the
    shared dev stack running on a separate Docker host (see
    infrastructure/README.md), managed independently of any single test run.
    It only polls the already-running services and skips with an actionable
    reason if they aren't reachable within the timeout.
    """
    if not _secrets_present():
        return ExternalServicesStatus(
            ready=False,
            reason=(
                f"{SECRETS_DIR} is missing required files. If the topology is running "
                "on the Docker host (see infrastructure/README.md), copy its "
                "infrastructure/compose/secrets/ down to this checkout, or run pytest "
                "from an SSH session on the Docker host itself."
            ),
        )

    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    postgres_error = _wait_for_postgres(deadline)
    kafka_error = _wait_for_kafka(deadline)

    if postgres_error or kafka_error:
        reasons = [reason for reason in (postgres_error, kafka_error) if reason]
        return ExternalServicesStatus(ready=False, reason="; ".join(reasons))

    return ExternalServicesStatus(ready=True)


@pytest.fixture(scope="session", autouse=True)
def _skip_if_external_services_unavailable(  # pyright: ignore[reportUnusedFunction]
    external_services_status: ExternalServicesStatus,
) -> None:
    if not external_services_status.ready:
        pytest.skip(f"external_service tests skipped: {external_services_status.reason}")


@pytest.fixture(scope="session")
def postgres_dsn(external_services_status: ExternalServicesStatus) -> str:
    """DSN for the `ai_platform` database using local compose admin credentials."""
    return _postgres_dsn()


@pytest.fixture
def postgres_connection(postgres_dsn: str) -> Iterator[psycopg.Connection[Any]]:
    """A real psycopg connection to the local compose PostgreSQL instance."""
    conn = psycopg.connect(postgres_dsn, connect_timeout=5)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(scope="session")
def kafka_bootstrap_servers() -> str:
    """Host-reachable Kafka bootstrap servers (the EXTERNAL SASL listener)."""
    return KAFKA_BOOTSTRAP_SERVERS


@pytest.fixture(scope="session")
def kafka_admin_client_config(
    external_services_status: ExternalServicesStatus,
) -> dict[str, Any]:
    """confluent_kafka client config for the `admin` principal."""
    return _kafka_admin_config()


@pytest.fixture(scope="session")
def kafka_admin_client(kafka_admin_client_config: dict[str, Any]) -> AdminClient:
    """A confluent_kafka AdminClient authenticated as the `admin` principal."""
    return AdminClient(kafka_admin_client_config)


def _postgres_role_dsn(login: str, password_secret_file: str) -> str:
    password = _read_secret(password_secret_file)
    return f"postgresql://{login}:{password}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DATABASE}"


@pytest.fixture(scope="session")
def postgres_orchestrator_app_dsn(external_services_status: ExternalServicesStatus) -> str:
    """DSN for the least-privilege `ai_platform_orchestrator_app` runtime login."""
    return _postgres_role_dsn(
        "ai_platform_orchestrator_app", "postgres_orchestrator_app_password.txt"
    )


@pytest.fixture(scope="session")
def postgres_agent_app_dsn(external_services_status: ExternalServicesStatus) -> str:
    """DSN for the least-privilege `ai_platform_agent_app` runtime login."""
    return _postgres_role_dsn("ai_platform_agent_app", "postgres_agent_app_password.txt")


@pytest.fixture(scope="session")
def postgres_orchestrator_migrator_dsn(external_services_status: ExternalServicesStatus) -> str:
    """DSN for the `ai_platform_orchestrator_migrator` login (`SET ROLE`-only DDL)."""
    return _postgres_role_dsn(
        "ai_platform_orchestrator_migrator", "postgres_orchestrator_migrator_password.txt"
    )


@pytest.fixture(scope="session")
def postgres_agent_migrator_dsn(external_services_status: ExternalServicesStatus) -> str:
    """DSN for the `ai_platform_agent_migrator` login (`SET ROLE`-only DDL)."""
    return _postgres_role_dsn("ai_platform_agent_migrator", "postgres_agent_migrator_password.txt")


def _kafka_principal_client_config(principal: str, password_secret_file: str) -> dict[str, Any]:
    password = _read_secret(password_secret_file)
    return {
        "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
        "security.protocol": "SASL_PLAINTEXT",
        "sasl.mechanism": "SCRAM-SHA-256",
        "sasl.username": principal,
        "sasl.password": password,
    }


@pytest.fixture(scope="session")
def kafka_principal_client_configs(
    external_services_status: ExternalServicesStatus,
) -> dict[str, dict[str, Any]]:
    """confluent_kafka client configs for the ten least-privilege application principals
    provisioned by `infrastructure/compose/scripts/init-kafka.sh` (the original four, the
    `summarize-agent-producer`/`summarize-agent-consumer` pair ADR-0014 Section 6 added in
    Sprint 9 for capability-scoped `text-summarize` routing, the
    `review-agent-producer`/`review-agent-consumer` pair ADR-0018 added for
    capability-scoped `code-review` routing, and the
    `ui-review-agent-producer`/`ui-review-agent-consumer` pair ADR-0019 added for
    capability-scoped `ui-review` routing)."""
    return {
        "orchestrator-producer": _kafka_principal_client_config(
            "orchestrator-producer", "kafka_orchestrator_producer_password.txt"
        ),
        "orchestrator-consumer": _kafka_principal_client_config(
            "orchestrator-consumer", "kafka_orchestrator_consumer_password.txt"
        ),
        "agent-producer": _kafka_principal_client_config(
            "agent-producer", "kafka_agent_producer_password.txt"
        ),
        "agent-consumer": _kafka_principal_client_config(
            "agent-consumer", "kafka_agent_consumer_password.txt"
        ),
        "summarize-agent-producer": _kafka_principal_client_config(
            "summarize-agent-producer", "kafka_summarize_agent_producer_password.txt"
        ),
        "summarize-agent-consumer": _kafka_principal_client_config(
            "summarize-agent-consumer", "kafka_summarize_agent_consumer_password.txt"
        ),
        "review-agent-producer": _kafka_principal_client_config(
            "review-agent-producer", "kafka_review_agent_producer_password.txt"
        ),
        "review-agent-consumer": _kafka_principal_client_config(
            "review-agent-consumer", "kafka_review_agent_consumer_password.txt"
        ),
        "ui-review-agent-producer": _kafka_principal_client_config(
            "ui-review-agent-producer", "kafka_ui_review_agent_producer_password.txt"
        ),
        "ui-review-agent-consumer": _kafka_principal_client_config(
            "ui-review-agent-consumer", "kafka_ui_review_agent_consumer_password.txt"
        ),
    }
