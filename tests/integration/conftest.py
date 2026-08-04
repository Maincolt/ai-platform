"""Session-scoped scaffolding for external-service tests.

Tests under `tests/integration/` are external-service tests as defined by
`docs/testing/README.md`: they exercise the real, locally isolated
PostgreSQL + Apache Kafka topology from `infrastructure/compose/` (see
`infrastructure/README.md`), not fakes or in-process substitutes. They are
opt-in via the `external_service` pytest marker (excluded by default through
`addopts` in `pyproject.toml`).

This module never tears the topology down: it is the same shared local dev
stack other Sprint 6/7 work depends on staying up, and Kafka's startup time
makes repeated teardown/setup between test runs impractical. If the topology
cannot be reached (Podman unavailable, secrets not generated, services not
healthy in time), every test collected under this directory is skipped with
an actionable reason rather than failing deep inside test bodies.
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
import pytest
from confluent_kafka.admin import AdminClient

pytestmark = pytest.mark.external_service

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_DIR = REPO_ROOT / "infrastructure" / "compose"
SECRETS_DIR = COMPOSE_DIR / "secrets"
GENERATE_SECRETS_SCRIPT = COMPOSE_DIR / "scripts" / "generate-secrets.sh"

# Overridable so this suite can run either from the host (default: the
# published host ports) or from inside a container attached to the
# `ai-platform-local_default` compose network (internal service names/ports
# -- e.g. AI_PLATFORM_TEST_POSTGRES_HOST=postgres,
# AI_PLATFORM_TEST_POSTGRES_PORT=5432,
# AI_PLATFORM_TEST_KAFKA_BOOTSTRAP_SERVERS=kafka:9092). Running inside the
# network is the more reliable option on hosts where the Windows/WSL2 host
# port-forwarding path is flaky -- TCP connect can succeed while the actual
# protocol handshake still hangs on some setups; see infrastructure/README.md.
POSTGRES_HOST = os.environ.get("AI_PLATFORM_TEST_POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.environ.get("AI_PLATFORM_TEST_POSTGRES_PORT", "5433"))
POSTGRES_DATABASE = "ai_platform"

# The EXTERNAL SASL_PLAINTEXT/SCRAM-SHA-256 listener published to the host --
# see infrastructure/compose/kafka/entrypoint.sh. Tests running inside the
# compose network instead use "kafka:9092".
KAFKA_BOOTSTRAP_SERVERS = os.environ.get(
    "AI_PLATFORM_TEST_KAFKA_BOOTSTRAP_SERVERS", "localhost:19093"
)

# When set, skip the podman-compose bring-up entirely and just poll the
# already-running services directly -- for use inside a container that
# cannot/should not manage its sibling containers via the podman CLI.
_SKIP_COMPOSE_MANAGEMENT = bool(os.environ.get("AI_PLATFORM_TEST_SKIP_COMPOSE_UP"))

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


def _podman_available() -> bool:
    try:
        result = subprocess.run(
            ["podman", "version"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except OSError, subprocess.TimeoutExpired:
        return False
    return result.returncode == 0


def _generate_secrets() -> tuple[bool, str | None]:
    try:
        result = subprocess.run(
            ["bash", str(GENERATE_SECRETS_SCRIPT)],
            cwd=str(COMPOSE_DIR),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"failed to run generate-secrets.sh: {exc}"
    if result.returncode != 0:
        return False, (
            f"generate-secrets.sh failed (exit {result.returncode}): {result.stderr.strip()[:500]}"
        )
    return True, None


def _compose_up() -> tuple[bool, str | None]:
    try:
        result = subprocess.run(
            ["podman", "compose", "up", "-d", "postgres", "kafka"],
            cwd=str(COMPOSE_DIR),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"failed to run 'podman compose up -d postgres kafka': {exc}"
    if result.returncode != 0:
        return False, (
            "'podman compose up -d postgres kafka' failed (exit "
            f"{result.returncode}): {result.stderr.strip()[:500]}"
        )
    return True, None


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
    """Ensure the real local PostgreSQL/Kafka topology is reachable.

    Brings the topology up if it is not already running (generating secrets
    first if necessary) but deliberately never tears it down: it is the
    shared local dev stack, and other work depends on it staying up between
    test runs.

    When AI_PLATFORM_TEST_SKIP_COMPOSE_UP is set (running inside a container
    attached to the compose network, which cannot/should not manage its
    sibling containers), this skips straight to polling the already-running
    services directly.
    """
    if not _SKIP_COMPOSE_MANAGEMENT:
        if not _podman_available():
            return ExternalServicesStatus(
                ready=False,
                reason=(
                    "Podman is not available on PATH. Install/start Podman, then "
                    "re-run 'uv run pytest -m external_service'."
                ),
            )

        if not _secrets_present():
            generated, error = _generate_secrets()
            if not generated:
                return ExternalServicesStatus(
                    ready=False,
                    reason=(
                        "infrastructure/compose/secrets/ is missing required files and "
                        f"automatic generation failed: {error}. Run "
                        "'bash infrastructure/compose/scripts/generate-secrets.sh' "
                        "manually."
                    ),
                )

        started, error = _compose_up()
        if not started:
            return ExternalServicesStatus(
                ready=False,
                reason=(
                    "Could not start the compose topology: "
                    f"{error}. Run 'podman compose up -d postgres kafka' from "
                    "infrastructure/compose/ manually and inspect the output."
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
    """confluent_kafka client configs for the four least-privilege application principals
    provisioned by `infrastructure/compose/scripts/init-kafka.sh`."""
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
    }
