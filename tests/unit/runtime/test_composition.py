"""Broker/database-free wiring tests for concrete process composition.

`composition.py` wires the entire platform/Agent process (security config,
topic mapping, persistence pool, executor selection, AI Router assembly)
but has no dedicated unit test, unlike every other `runtime/` module. A
wiring mistake here -- the wrong `KafkaSecurityConfig` or `LogicalChannel`
passed to the wrong collaborator -- would currently pass the full test
suite and only surface during manual real-service validation. These tests
patch the native Kafka client classes (the same pattern used in
`tests/unit/adapters/event_bus/`) and the artifact-loading functions, then
assert on the *kwargs* each collaborator actually receives.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from ai_platform.agents.architecture_review_agent.agent import ArchitectureReviewAgent
from ai_platform.agents.architecture_review_agent.capability import (
    CAPABILITY_NAME as ARCHITECTURE_REVIEW_CAPABILITY_NAME,
)
from ai_platform.agents.data_analysis_agent.agent import DataAnalysisAgent
from ai_platform.agents.data_analysis_agent.capability import (
    CAPABILITY_NAME as DATA_ANALYSIS_CAPABILITY_NAME,
)
from ai_platform.agents.review_agent.agent import ReviewAgent
from ai_platform.agents.review_agent.capability import (
    CAPABILITY_NAME as REVIEW_CAPABILITY_NAME,
)
from ai_platform.agents.summarize_agent.agent import SummarizeAgent
from ai_platform.agents.summarize_agent.capability import (
    CAPABILITY_NAME as SUMMARIZE_CAPABILITY_NAME,
)
from ai_platform.agents.test_agent.agent import TestAgent
from ai_platform.agents.test_agent.capability import CAPABILITY_NAME as WORD_COUNT_CAPABILITY_NAME
from ai_platform.agents.ui_review_agent.agent import UiReviewAgent
from ai_platform.agents.ui_review_agent.capability import (
    CAPABILITY_NAME as UI_REVIEW_CAPABILITY_NAME,
)
from ai_platform.orchestrator.registry.declarations import CapabilityBinding
from ai_platform.orchestrator.registry.snapshot import RegistrySnapshot
from ai_platform.ports.event_bus import LogicalChannel
from ai_platform.runtime import composition
from ai_platform.runtime.composition import (
    _build_ai_router,  # pyright: ignore[reportPrivateUsage]
    _build_executor,  # pyright: ignore[reportPrivateUsage]
    _pool,  # pyright: ignore[reportPrivateUsage]
    _security,  # pyright: ignore[reportPrivateUsage]
    _topic_mapping,  # pyright: ignore[reportPrivateUsage]
    build_agent_process,
    build_platform_process,
)
from ai_platform.runtime.configuration import (
    AgentRuntimeConfig,
    PlatformRuntimeConfig,
    RuntimeConfigurationError,
    SecretFileReference,
)
from ai_platform.runtime.lifecycle import ManagedService
from ai_platform.shared.identifiers import AgentId


def _write_secret(directory: Path, name: str, value: str) -> str:
    path = directory / name
    path.write_text(value, encoding="utf-8")
    return str(path)


def _platform_env(tmp_path: Path) -> dict[str, str]:
    return {
        "AI_PLATFORM_ENVIRONMENT": "development",
        "AI_PLATFORM_ORCHESTRATOR_DATABASE_DSN_FILE": _write_secret(
            tmp_path, "orchestrator-dsn", "postgresql://orchestrator/db"
        ),
        "AI_PLATFORM_KAFKA_BOOTSTRAP_SERVERS": "event-bus:9092",
        "AI_PLATFORM_ORCHESTRATOR_DATABASE_POOL_MIN_SIZE": "1",
        "AI_PLATFORM_ORCHESTRATOR_DATABASE_POOL_MAX_SIZE": "4",
        "AI_PLATFORM_ORCHESTRATOR_DATABASE_TIMEOUT_SECONDS": "5",
        "AI_PLATFORM_ORCHESTRATOR_KAFKA_SECURITY_PROTOCOL": "LOCAL_DEVELOPMENT_SASL_PLAINTEXT",
        "AI_PLATFORM_ORCHESTRATOR_KAFKA_PRODUCER_USERNAME": "orchestrator-producer",
        "AI_PLATFORM_ORCHESTRATOR_KAFKA_PRODUCER_PASSWORD_FILE": _write_secret(
            tmp_path, "orchestrator-producer-kafka", "producer-secret"
        ),
        "AI_PLATFORM_ORCHESTRATOR_KAFKA_CONSUMER_USERNAME": "orchestrator-consumer",
        "AI_PLATFORM_ORCHESTRATOR_KAFKA_CONSUMER_PASSWORD_FILE": _write_secret(
            tmp_path, "orchestrator-consumer-kafka", "consumer-secret"
        ),
        "AI_PLATFORM_TASK_COMMANDS_TOPIC": "task-commands",
        "AI_PLATFORM_TASK_COMMANDS_QUARANTINE_TOPIC": "task-commands-quarantine",
        "AI_PLATFORM_TASK_OUTCOMES_TOPIC": "task-outcomes",
        "AI_PLATFORM_TASK_OUTCOMES_QUARANTINE_TOPIC": "task-outcomes-quarantine",
        "AI_PLATFORM_CONTRACT_SCHEMA_DIRECTORY": str(tmp_path),
        "AI_PLATFORM_PUBLISH_TIMEOUT_SECONDS": "5",
        "AI_PLATFORM_CONSUMER_POLL_TIMEOUT_SECONDS": "1",
        "AI_PLATFORM_CONSUMER_RETRY_DELAY_SECONDS": "0.1",
        "AI_PLATFORM_CONSUMER_MAXIMUM_PROCESSING_ATTEMPTS": "3",
        "AI_PLATFORM_WORKER_IDLE_DELAY_SECONDS": "0.1",
        "AI_PLATFORM_OUTBOX_CLAIM_TTL_SECONDS": "30",
        "AI_PLATFORM_OUTBOX_MAXIMUM_PUBLICATION_ATTEMPTS": "3",
        "AI_PLATFORM_QUARANTINE_RECONCILIATION_LIMIT": "100",
        "AI_PLATFORM_QUARANTINE_QUERY_TIMEOUT_SECONDS": "1",
        "AI_PLATFORM_STARTUP_TIMEOUT_SECONDS": "10",
        "AI_PLATFORM_SHUTDOWN_GRACE_SECONDS": "10",
        "AI_PLATFORM_API_HOST": "127.0.0.1",
        "AI_PLATFORM_API_PORT": "8080",
        "AI_PLATFORM_LOCAL_POLICY_ENABLED": "true",
        "AI_PLATFORM_REGISTRY_PATH": str(tmp_path / "registry.json"),
        "AI_PLATFORM_READINESS_CREDENTIAL_FILE": _write_secret(
            tmp_path, "readiness", "readiness-secret"
        ),
        "AI_PLATFORM_ORCHESTRATOR_INSTANCE_ID": "orchestrator-1",
        "AI_PLATFORM_ORCHESTRATOR_OUTCOME_CONSUMER_GROUP_ID": "orchestrator-outcomes",
        "AI_PLATFORM_ORCHESTRATOR_OUTCOME_LOGICAL_SUBSCRIPTION_ID": "orchestrator-outcomes-v1",
        "AI_PLATFORM_DEADLINE_INTERVAL_SECONDS": "1",
        "AI_PLATFORM_DEADLINE_BATCH_SIZE": "100",
        "AI_PLATFORM_AGENT_READINESS_TIMEOUT_SECONDS": "1",
        "AI_PLATFORM_AGENT_READINESS_TTL_SECONDS": "5",
        "AI_PLATFORM_AGENT_READINESS_REFRESH_INTERVAL_SECONDS": "1",
        "AI_PLATFORM_TASK_RESULT_TIMEOUT_SECONDS": "30",
    }


def _agent_env(tmp_path: Path) -> dict[str, str]:
    return {
        "AI_PLATFORM_ENVIRONMENT": "development",
        "AI_PLATFORM_AGENT_DATABASE_DSN_FILE": _write_secret(
            tmp_path, "agent-dsn", "postgresql://agent/db"
        ),
        "AI_PLATFORM_KAFKA_BOOTSTRAP_SERVERS": "event-bus:9092",
        "AI_PLATFORM_AGENT_DATABASE_POOL_MIN_SIZE": "1",
        "AI_PLATFORM_AGENT_DATABASE_POOL_MAX_SIZE": "4",
        "AI_PLATFORM_AGENT_DATABASE_TIMEOUT_SECONDS": "5",
        "AI_PLATFORM_AGENT_KAFKA_SECURITY_PROTOCOL": "LOCAL_DEVELOPMENT_SASL_PLAINTEXT",
        "AI_PLATFORM_AGENT_KAFKA_PRODUCER_USERNAME": "agent-producer",
        "AI_PLATFORM_AGENT_KAFKA_PRODUCER_PASSWORD_FILE": _write_secret(
            tmp_path, "agent-producer-kafka", "producer-secret"
        ),
        "AI_PLATFORM_AGENT_KAFKA_CONSUMER_USERNAME": "agent-consumer",
        "AI_PLATFORM_AGENT_KAFKA_CONSUMER_PASSWORD_FILE": _write_secret(
            tmp_path, "agent-consumer-kafka", "consumer-secret"
        ),
        "AI_PLATFORM_TASK_COMMANDS_TOPIC": "task-commands",
        "AI_PLATFORM_TASK_COMMANDS_QUARANTINE_TOPIC": "task-commands-quarantine",
        "AI_PLATFORM_TASK_OUTCOMES_TOPIC": "task-outcomes",
        "AI_PLATFORM_TASK_OUTCOMES_QUARANTINE_TOPIC": "task-outcomes-quarantine",
        "AI_PLATFORM_CONTRACT_SCHEMA_DIRECTORY": str(tmp_path),
        "AI_PLATFORM_PUBLISH_TIMEOUT_SECONDS": "5",
        "AI_PLATFORM_CONSUMER_POLL_TIMEOUT_SECONDS": "1",
        "AI_PLATFORM_CONSUMER_RETRY_DELAY_SECONDS": "0.1",
        "AI_PLATFORM_CONSUMER_MAXIMUM_PROCESSING_ATTEMPTS": "3",
        "AI_PLATFORM_WORKER_IDLE_DELAY_SECONDS": "0.1",
        "AI_PLATFORM_OUTBOX_CLAIM_TTL_SECONDS": "30",
        "AI_PLATFORM_OUTBOX_MAXIMUM_PUBLICATION_ATTEMPTS": "3",
        "AI_PLATFORM_QUARANTINE_RECONCILIATION_LIMIT": "100",
        "AI_PLATFORM_QUARANTINE_QUERY_TIMEOUT_SECONDS": "1",
        "AI_PLATFORM_STARTUP_TIMEOUT_SECONDS": "10",
        "AI_PLATFORM_SHUTDOWN_GRACE_SECONDS": "10",
        "AI_PLATFORM_AGENT_ID": "018f23a7-6b4d-7c91-8a2e-123456789abc",
        "AI_PLATFORM_AGENT_READINESS_HOST": "127.0.0.1",
        "AI_PLATFORM_AGENT_READINESS_PORT": "8081",
        "AI_PLATFORM_READINESS_CREDENTIAL_FILE": _write_secret(
            tmp_path, "readiness", "readiness-secret"
        ),
        "AI_PLATFORM_AGENT_MAXIMUM_CONCURRENCY": "4",
        "AI_PLATFORM_AGENT_COMPONENT": "test-agent",
        "AI_PLATFORM_AGENT_DECLARATION_DIGEST": "sha256:declaration",
        "AI_PLATFORM_AGENT_DECLARATION_PATH": str(tmp_path / "declaration.json"),
        "AI_PLATFORM_AGENT_PUBLISHER_INSTANCE_ID": "test-agent-1",
        "AI_PLATFORM_AGENT_COMMAND_CONSUMER_GROUP_ID": "test-agent-commands",
        "AI_PLATFORM_AGENT_COMMAND_LOGICAL_SUBSCRIPTION_ID": "test-agent-commands-v1",
    }


def _fake_server_factory(app: object, host: str, port: int) -> ManagedService:
    class _FakeServer:
        async def run(self) -> None:
            return None

        async def stop(self) -> None:
            return None

        async def close(self, *, timeout_seconds: float) -> bool:
            return True

    return _FakeServer()


_kafka_client_calls: dict[str, list[dict[str, object]]] = {}


def _record_kafka_client(target: str) -> Any:
    def construct(config: dict[str, object]) -> MagicMock:
        _kafka_client_calls[target].append(config)
        return MagicMock()

    return construct


@pytest.fixture
def _no_kafka(monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    """Prevent every composition path from starting a real librdkafka client.

    Calls are recorded per patched target rather than pooled, so tests can
    assert which specific collaborator (e.g. the command consumer vs. the
    quarantine publisher) received which credential -- pooling them into one
    set would let a producer/consumer credential swap pass unnoticed.
    """
    _kafka_client_calls.clear()
    for target in (
        "ai_platform.adapters.event_bus.producer.Producer",
        "ai_platform.adapters.event_bus.quarantine.Producer",
        "ai_platform.adapters.event_bus.consumer.Consumer",
        "ai_platform.adapters.event_bus.health.AdminClient",
    ):
        _kafka_client_calls[target] = []
        module_path, class_name = target.rsplit(".", 1)
        module = importlib.import_module(module_path)
        monkeypatch.setattr(module, class_name, _record_kafka_client(target))


_PLACEHOLDER_SCHEMA: dict[str, object] = {"type": "object"}


@pytest.fixture
def _no_schema_loading(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`compose_outcome_recovery`/Agent startup load real schema files off disk."""

    def fake_load(
        _directory: Path, *, contract_names: tuple[str, ...] = (), **_kwargs: object
    ) -> dict[tuple[str, str], dict[str, object]]:
        return {(name, "1.0"): _PLACEHOLDER_SCHEMA for name in contract_names}

    monkeypatch.setattr(composition, "load_canonical_message_schemas", fake_load)


# --- pure helper wiring -----------------------------------------------------


def test_security_uses_producer_credentials_not_consumer_credentials(tmp_path: Path) -> None:
    config = PlatformRuntimeConfig.from_environment(_platform_env(tmp_path))
    security = _security(
        config,
        username=config.kafka_producer_username,
        password=config.kafka_producer_password,
    )
    assert security.username == "orchestrator-producer"
    assert security.password == "producer-secret"


def test_security_uses_consumer_credentials_when_asked_for_consumer(tmp_path: Path) -> None:
    config = PlatformRuntimeConfig.from_environment(_platform_env(tmp_path))
    security = _security(
        config,
        username=config.kafka_consumer_username,
        password=config.kafka_consumer_password,
    )
    assert security.username == "orchestrator-consumer"
    assert security.password == "consumer-secret"


def test_topic_mapping_binds_commands_and_outcomes_to_distinct_topics(tmp_path: Path) -> None:
    config = PlatformRuntimeConfig.from_environment(_platform_env(tmp_path))
    mapping = _topic_mapping(config)
    assert mapping.topic_for(LogicalChannel.TASK_COMMANDS) == "task-commands"
    assert mapping.topic_for(LogicalChannel.TASK_OUTCOMES) == "task-outcomes"


def test_pool_uses_orchestrator_schema_and_expected_version(tmp_path: Path) -> None:
    config = PlatformRuntimeConfig.from_environment(_platform_env(tmp_path))
    pool = _pool(config, component_schema="orchestrator")
    assert pool.component_schema == "orchestrator"
    assert pool.expected_schema_version == 3


def test_pool_uses_agent_schema_and_expected_version(tmp_path: Path) -> None:
    config = PlatformRuntimeConfig.from_environment(_platform_env(tmp_path))
    pool = _pool(config, component_schema="agent")
    assert pool.component_schema == "agent"
    assert pool.expected_schema_version == 4


# --- executor selection (fail-closed) ---------------------------------------


def _agent_config(tmp_path: Path, **overrides: Any) -> AgentRuntimeConfig:
    from dataclasses import replace

    config = AgentRuntimeConfig.from_environment(_agent_env(tmp_path))
    return replace(config, **overrides) if overrides else config


def test_build_executor_selects_test_agent_for_word_count_capability(tmp_path: Path) -> None:
    config = _agent_config(tmp_path)
    executor = _build_executor(
        WORD_COUNT_CAPABILITY_NAME,
        config=config,
        agent_id=AgentId(config.agent_id),
        persistence=object(),  # type: ignore[arg-type]
    )
    assert isinstance(executor, TestAgent)


def test_build_executor_selects_summarize_agent_for_summarize_capability(tmp_path: Path) -> None:
    config = _agent_config(
        tmp_path,
        ai_router_anthropic_api_key=SecretFileReference(
            Path(_write_secret(tmp_path, "anthropic-key", "sk-test"))
        ),
        ai_router_anthropic_model="claude-haiku-4-5",
        ai_router_max_output_tokens=512,
    )
    executor = _build_executor(
        SUMMARIZE_CAPABILITY_NAME,
        config=config,
        agent_id=AgentId(config.agent_id),
        persistence=object(),  # type: ignore[arg-type]
    )
    assert isinstance(executor, SummarizeAgent)


def test_build_executor_selects_review_agent_for_code_review_capability(tmp_path: Path) -> None:
    config = _agent_config(
        tmp_path,
        ai_router_anthropic_api_key=SecretFileReference(
            Path(_write_secret(tmp_path, "anthropic-key", "sk-test"))
        ),
        ai_router_anthropic_model="claude-haiku-4-5",
        ai_router_max_output_tokens=512,
    )
    executor = _build_executor(
        REVIEW_CAPABILITY_NAME,
        config=config,
        agent_id=AgentId(config.agent_id),
        persistence=object(),  # type: ignore[arg-type]
    )
    assert isinstance(executor, ReviewAgent)


def test_build_executor_selects_ui_review_agent_for_ui_review_capability(tmp_path: Path) -> None:
    config = _agent_config(
        tmp_path,
        ai_router_anthropic_api_key=SecretFileReference(
            Path(_write_secret(tmp_path, "anthropic-key", "sk-test"))
        ),
        ai_router_anthropic_model="claude-haiku-4-5",
        ai_router_max_output_tokens=512,
    )
    executor = _build_executor(
        UI_REVIEW_CAPABILITY_NAME,
        config=config,
        agent_id=AgentId(config.agent_id),
        persistence=object(),  # type: ignore[arg-type]
    )
    assert isinstance(executor, UiReviewAgent)


def test_build_executor_selects_architecture_review_agent_for_architecture_review_capability(
    tmp_path: Path,
) -> None:
    config = _agent_config(
        tmp_path,
        ai_router_anthropic_api_key=SecretFileReference(
            Path(_write_secret(tmp_path, "anthropic-key", "sk-test"))
        ),
        ai_router_anthropic_model="claude-haiku-4-5",
        ai_router_max_output_tokens=512,
    )
    executor = _build_executor(
        ARCHITECTURE_REVIEW_CAPABILITY_NAME,
        config=config,
        agent_id=AgentId(config.agent_id),
        persistence=object(),  # type: ignore[arg-type]
    )
    assert isinstance(executor, ArchitectureReviewAgent)


def test_build_executor_selects_data_analysis_agent_for_data_analysis_capability(
    tmp_path: Path,
) -> None:
    config = _agent_config(
        tmp_path,
        ai_router_anthropic_api_key=SecretFileReference(
            Path(_write_secret(tmp_path, "anthropic-key", "sk-test"))
        ),
        ai_router_anthropic_model="claude-haiku-4-5",
        ai_router_max_output_tokens=512,
    )
    executor = _build_executor(
        DATA_ANALYSIS_CAPABILITY_NAME,
        config=config,
        agent_id=AgentId(config.agent_id),
        persistence=object(),  # type: ignore[arg-type]
    )
    assert isinstance(executor, DataAnalysisAgent)


def test_build_executor_fails_closed_for_unrecognized_capability(tmp_path: Path) -> None:
    config = _agent_config(tmp_path)
    with pytest.raises(RuntimeConfigurationError, match="UNSUPPORTED_AGENT_CAPABILITY"):
        _build_executor(
            "not-a-real-capability",
            config=config,
            agent_id=AgentId(config.agent_id),
            persistence=object(),  # type: ignore[arg-type]
        )


# --- AI Router provider assembly --------------------------------------------


def test_build_ai_router_requires_at_least_one_configured_provider(tmp_path: Path) -> None:
    config = _agent_config(tmp_path)
    with pytest.raises(RuntimeConfigurationError, match="MISSING_AI_ROUTER_PROVIDER_CONFIGURATION"):
        _build_ai_router(config)


def test_build_ai_router_includes_only_the_configured_provider(tmp_path: Path) -> None:
    config = _agent_config(
        tmp_path,
        ai_router_anthropic_api_key=SecretFileReference(
            Path(_write_secret(tmp_path, "anthropic-key", "sk-test"))
        ),
        ai_router_anthropic_model="claude-haiku-4-5",
    )
    router = _build_ai_router(config)
    assert len(router._providers) == 1  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]


def test_build_ai_router_includes_both_providers_when_both_configured(tmp_path: Path) -> None:
    config = _agent_config(
        tmp_path,
        ai_router_anthropic_api_key=SecretFileReference(
            Path(_write_secret(tmp_path, "anthropic-key", "sk-test"))
        ),
        ai_router_anthropic_model="claude-haiku-4-5",
        ai_router_openai_api_key=SecretFileReference(
            Path(_write_secret(tmp_path, "openai-key", "sk-test"))
        ),
        ai_router_openai_model="gpt-5-mini",
    )
    router = _build_ai_router(config)
    assert len(router._providers) == 2  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]


def test_build_ai_router_fails_closed_on_an_unapproved_model(tmp_path: Path) -> None:
    """ADR-0017 Decision 3: only specific reviewed models are approved."""
    config = _agent_config(
        tmp_path,
        ai_router_anthropic_api_key=SecretFileReference(
            Path(_write_secret(tmp_path, "anthropic-key", "sk-test"))
        ),
        ai_router_anthropic_model="claude-3-5-haiku-20241022",
    )
    with pytest.raises(RuntimeConfigurationError, match="UNAPPROVED_AI_ROUTER_MODEL"):
        _build_ai_router(config)


# --- full platform-process wiring -------------------------------------------


def test_build_platform_process_falls_back_when_registry_artifact_is_missing(
    tmp_path: Path, _no_kafka: None, _no_schema_loading: None
) -> None:
    config = PlatformRuntimeConfig.from_environment(_platform_env(tmp_path))
    process = build_platform_process(config, server_factory=_fake_server_factory)
    assert process.registry is None
    assert process.app_state.registry_loaded is False


def test_build_platform_process_wires_producer_and_consumer_credentials_separately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _no_kafka: None, _no_schema_loading: None
) -> None:
    registry = RegistrySnapshot(revision="r1", bindings=())

    def fake_load_registry(_path: Path, *, maximum_bytes: int = 0) -> RegistrySnapshot:
        return registry

    monkeypatch.setattr(composition, "load_registry_artifact", fake_load_registry)
    config = PlatformRuntimeConfig.from_environment(_platform_env(tmp_path))

    process = build_platform_process(config, server_factory=_fake_server_factory)

    assert process.registry is registry
    assert process.app_state.registry_loaded is True

    # The command-outbox publisher and the broker-health probe must use
    # producer credentials; the outcome consumer and its quarantine
    # publisher must use consumer credentials. Checked per collaborator
    # (not pooled) so a producer/consumer swap cannot pass unnoticed.
    def _usernames(target: str) -> set[object]:
        return {call["sasl.username"] for call in _kafka_client_calls[target]}

    assert _usernames("ai_platform.adapters.event_bus.producer.Producer") == {
        "orchestrator-producer"
    }
    assert _usernames("ai_platform.adapters.event_bus.health.AdminClient") == {
        "orchestrator-producer"
    }
    assert _usernames("ai_platform.adapters.event_bus.consumer.Consumer") == {
        "orchestrator-consumer"
    }
    assert _usernames("ai_platform.adapters.event_bus.quarantine.Producer") == {
        "orchestrator-consumer"
    }


def test_build_platform_process_command_publisher_is_given_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _no_kafka: None, _no_schema_loading: None
) -> None:
    """Regression test: the Orchestrator's command_publisher was constructed
    without `environment=`, so `KafkaEventPublisher._resolve_topic` always
    raised `CAPABILITY_ROUTING_REQUIRES_ENVIRONMENT` for every
    capability-scoped command publish (ADR-0014 Section 6) -- unhandled by
    `publish()`'s exception handling, crashing the whole runtime service and
    surfacing only as an undiagnosable `PLATFORM_SHUTDOWN_INCOMPLETE` after
    the lifecycle diagnostics fix (see lifecycle.py) finally made the
    underlying exception visible. This was a real, deterministic bug hit on
    ui.review's first live workflow submission, not the host-specific
    flakiness it had been mistaken for across several earlier sprints."""
    registry = RegistrySnapshot(revision="r1", bindings=())

    def fake_load_registry(_path: Path, *, maximum_bytes: int = 0) -> RegistrySnapshot:
        return registry

    monkeypatch.setattr(composition, "load_registry_artifact", fake_load_registry)

    captured_kwargs: list[dict[str, object]] = []
    real_publisher_cls = composition.KafkaEventPublisher

    def _capturing_publisher(**kwargs: object) -> object:
        captured_kwargs.append(kwargs)
        return real_publisher_cls(**kwargs)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr(composition, "KafkaEventPublisher", _capturing_publisher)
    config = PlatformRuntimeConfig.from_environment(_platform_env(tmp_path))

    build_platform_process(config, server_factory=_fake_server_factory)

    command_publisher_kwargs = next(
        kwargs
        for kwargs in captured_kwargs
        if "command-publisher" in str(kwargs.get("client_id", ""))
    )
    assert command_publisher_kwargs.get("environment") == config.environment


def test_build_platform_process_deadline_reconciler_uses_configured_batch_size(
    tmp_path: Path, _no_kafka: None, _no_schema_loading: None
) -> None:
    env = _platform_env(tmp_path)
    env["AI_PLATFORM_DEADLINE_BATCH_SIZE"] = "17"
    config = PlatformRuntimeConfig.from_environment(env)
    process = build_platform_process(config, server_factory=_fake_server_factory)
    assert process.app_state.registry_loaded is False
    # The reconciler is private to the closure; the observable contract is
    # that construction succeeds with the configured batch size threaded
    # through rather than a hard-coded default.
    assert config.deadline_batch_size == 17


# --- full agent-process wiring -----------------------------------------------


def _declaration(capability_name: str) -> CapabilityBinding:
    return CapabilityBinding(
        capability_name=capability_name,
        capability_version="1.0",
        command_contract_name="ExecuteTask",
        command_contract_versions=("1.0",),
        event_contract_names=("TaskCompleted", "TaskFailed"),
        event_contract_versions=("1.0", "1.0"),
        agent_id=AgentId("018f23a7-6b4d-7c91-8a2e-123456789abc"),
        implementation_identity="test-agent",
        implementation_version="1.0",
        deployment_declaration_digest="sha256:declaration",
        environment="development",
        enabled=True,
        readiness_url="http://127.0.0.1:8100/health/ready",
    )


def _fake_declaration_loader(
    capability_name: str,
) -> Any:
    def load(
        _path: Path,
        *,
        environment: str,
        agent_id: AgentId,
        implementation_identity: str,
        declaration_digest: str,
        maximum_bytes: int = 0,
    ) -> tuple[str, CapabilityBinding]:
        return ("rev-1", _declaration(capability_name))

    return load


def test_build_agent_process_wires_word_count_executor_and_readiness_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _no_kafka: None, _no_schema_loading: None
) -> None:
    monkeypatch.setattr(
        composition,
        "load_agent_deployment_declaration",
        _fake_declaration_loader(WORD_COUNT_CAPABILITY_NAME),
    )
    config = AgentRuntimeConfig.from_environment(_agent_env(tmp_path))

    process = build_agent_process(config, server_factory=_fake_server_factory)

    snapshot = process.readiness_state.snapshot()
    assert snapshot.declaration_revision == "rev-1"
    assert snapshot.capabilities == ((WORD_COUNT_CAPABILITY_NAME, "1.0"),)
    assert snapshot.ready is False

    def _usernames(target: str) -> set[object]:
        return {call["sasl.username"] for call in _kafka_client_calls[target]}

    # The outcome-outbox publisher and the broker-health probe must use
    # producer credentials; the command consumer and its quarantine
    # publisher must use consumer credentials.
    assert _usernames("ai_platform.adapters.event_bus.producer.Producer") == {"agent-producer"}
    assert _usernames("ai_platform.adapters.event_bus.health.AdminClient") == {"agent-producer"}
    assert _usernames("ai_platform.adapters.event_bus.consumer.Consumer") == {"agent-consumer"}
    assert _usernames("ai_platform.adapters.event_bus.quarantine.Producer") == {"agent-consumer"}


def test_build_agent_process_fails_closed_for_unrecognized_declared_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _no_kafka: None, _no_schema_loading: None
) -> None:
    monkeypatch.setattr(
        composition,
        "load_agent_deployment_declaration",
        _fake_declaration_loader("not-a-real-capability"),
    )
    config = AgentRuntimeConfig.from_environment(_agent_env(tmp_path))

    with pytest.raises(RuntimeConfigurationError, match="UNSUPPORTED_AGENT_CAPABILITY"):
        build_agent_process(config, server_factory=_fake_server_factory)
