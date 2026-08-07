"""Security-boundary tests for runtime environment configuration."""

from pathlib import Path

import pytest

from ai_platform.runtime.configuration import (
    AgentRuntimeConfig,
    PlatformRuntimeConfig,
    RuntimeConfigurationError,
    SecretFileReference,
)


def _platform_values() -> dict[str, str]:
    return {
        "AI_PLATFORM_ENVIRONMENT": "development",
        "AI_PLATFORM_ORCHESTRATOR_DATABASE_DSN_FILE": "secrets/orchestrator-dsn",
        "AI_PLATFORM_KAFKA_BOOTSTRAP_SERVERS": "event-bus:9092",
        "AI_PLATFORM_ORCHESTRATOR_DATABASE_POOL_MIN_SIZE": "1",
        "AI_PLATFORM_ORCHESTRATOR_DATABASE_POOL_MAX_SIZE": "4",
        "AI_PLATFORM_ORCHESTRATOR_DATABASE_TIMEOUT_SECONDS": "5",
        "AI_PLATFORM_ORCHESTRATOR_KAFKA_SECURITY_PROTOCOL": ("LOCAL_DEVELOPMENT_SASL_PLAINTEXT"),
        "AI_PLATFORM_ORCHESTRATOR_KAFKA_PRODUCER_USERNAME": "orchestrator-producer",
        "AI_PLATFORM_ORCHESTRATOR_KAFKA_PRODUCER_PASSWORD_FILE": (
            "secrets/orchestrator-producer-kafka"
        ),
        "AI_PLATFORM_ORCHESTRATOR_KAFKA_CONSUMER_USERNAME": "orchestrator-consumer",
        "AI_PLATFORM_ORCHESTRATOR_KAFKA_CONSUMER_PASSWORD_FILE": (
            "secrets/orchestrator-consumer-kafka"
        ),
        "AI_PLATFORM_TASK_COMMANDS_TOPIC": "task-commands",
        "AI_PLATFORM_TASK_COMMANDS_QUARANTINE_TOPIC": "task-commands-quarantine",
        "AI_PLATFORM_TASK_OUTCOMES_TOPIC": "task-outcomes",
        "AI_PLATFORM_TASK_OUTCOMES_QUARANTINE_TOPIC": "task-outcomes-quarantine",
        "AI_PLATFORM_CONTRACT_SCHEMA_DIRECTORY": "contracts/events",
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
        "AI_PLATFORM_REGISTRY_PATH": "config/registry.json",
        "AI_PLATFORM_READINESS_CREDENTIAL_FILE": "secrets/readiness",
        "AI_PLATFORM_ORCHESTRATOR_INSTANCE_ID": "orchestrator-1",
        "AI_PLATFORM_ORCHESTRATOR_OUTCOME_CONSUMER_GROUP_ID": "orchestrator-outcomes",
        "AI_PLATFORM_ORCHESTRATOR_OUTCOME_LOGICAL_SUBSCRIPTION_ID": ("orchestrator-outcomes-v1"),
        "AI_PLATFORM_DEADLINE_INTERVAL_SECONDS": "1",
        "AI_PLATFORM_DEADLINE_BATCH_SIZE": "100",
        "AI_PLATFORM_AGENT_READINESS_TIMEOUT_SECONDS": "1",
        "AI_PLATFORM_AGENT_READINESS_TTL_SECONDS": "5",
        "AI_PLATFORM_AGENT_READINESS_REFRESH_INTERVAL_SECONDS": "1",
        "AI_PLATFORM_TASK_RESULT_TIMEOUT_SECONDS": "30",
    }


def test_platform_configuration_accepts_explicit_loopback_development_boundary() -> None:
    config = PlatformRuntimeConfig.from_environment(_platform_values())
    assert config.api_host == "127.0.0.1"
    assert config.local_policy_enabled
    assert config.task_result_timeout_seconds == 30
    assert config.consumer_maximum_processing_attempts == 3
    assert config.outbox_maximum_publication_attempts == 3


@pytest.mark.parametrize("host", ["0.0.0.0", "localhost", "192.168.1.5"])
def test_platform_configuration_rejects_nonliteral_or_nonloopback_api_host(host: str) -> None:
    values = _platform_values()
    values["AI_PLATFORM_API_HOST"] = host
    with pytest.raises(RuntimeConfigurationError, match="API_HOST_MUST_BE_LOOPBACK"):
        PlatformRuntimeConfig.from_environment(values)


def test_platform_configuration_requires_explicit_local_policy_opt_in() -> None:
    values = _platform_values()
    values["AI_PLATFORM_LOCAL_POLICY_ENABLED"] = "false"
    with pytest.raises(RuntimeConfigurationError, match="EXPLICIT_OPT_IN"):
        PlatformRuntimeConfig.from_environment(values)


def _agent_values() -> dict[str, str]:
    return {
        "AI_PLATFORM_ENVIRONMENT": "development",
        "AI_PLATFORM_AGENT_DATABASE_DSN_FILE": "secrets/agent-dsn",
        "AI_PLATFORM_KAFKA_BOOTSTRAP_SERVERS": "event-bus:9092",
        "AI_PLATFORM_AGENT_DATABASE_POOL_MIN_SIZE": "1",
        "AI_PLATFORM_AGENT_DATABASE_POOL_MAX_SIZE": "4",
        "AI_PLATFORM_AGENT_DATABASE_TIMEOUT_SECONDS": "5",
        "AI_PLATFORM_AGENT_KAFKA_SECURITY_PROTOCOL": ("LOCAL_DEVELOPMENT_SASL_PLAINTEXT"),
        "AI_PLATFORM_AGENT_KAFKA_PRODUCER_USERNAME": "agent-producer",
        "AI_PLATFORM_AGENT_KAFKA_PRODUCER_PASSWORD_FILE": "secrets/agent-producer-kafka",
        "AI_PLATFORM_AGENT_KAFKA_CONSUMER_USERNAME": "agent-consumer",
        "AI_PLATFORM_AGENT_KAFKA_CONSUMER_PASSWORD_FILE": "secrets/agent-consumer-kafka",
        "AI_PLATFORM_TASK_COMMANDS_TOPIC": "task-commands",
        "AI_PLATFORM_TASK_COMMANDS_QUARANTINE_TOPIC": "task-commands-quarantine",
        "AI_PLATFORM_TASK_OUTCOMES_TOPIC": "task-outcomes",
        "AI_PLATFORM_TASK_OUTCOMES_QUARANTINE_TOPIC": "task-outcomes-quarantine",
        "AI_PLATFORM_CONTRACT_SCHEMA_DIRECTORY": "contracts/events",
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
        "AI_PLATFORM_READINESS_CREDENTIAL_FILE": "secrets/readiness",
        "AI_PLATFORM_AGENT_MAXIMUM_CONCURRENCY": "4",
        "AI_PLATFORM_AGENT_COMPONENT": "test-agent",
        "AI_PLATFORM_AGENT_DECLARATION_DIGEST": "sha256:declaration",
        "AI_PLATFORM_AGENT_DECLARATION_PATH": "config/test-agent-declaration.json",
        "AI_PLATFORM_AGENT_PUBLISHER_INSTANCE_ID": "test-agent-1",
        "AI_PLATFORM_AGENT_COMMAND_CONSUMER_GROUP_ID": "test-agent-commands",
        "AI_PLATFORM_AGENT_COMMAND_LOGICAL_SUBSCRIPTION_ID": "test-agent-commands-v1",
    }


def test_agent_configuration_is_separate_and_loopback_bound() -> None:
    config = AgentRuntimeConfig.from_environment(_agent_values())
    assert config.maximum_concurrency == 4
    assert config.kafka_producer_username == "agent-producer"
    assert config.kafka_consumer_username == "agent-consumer"


def test_agent_configuration_accepts_all_interfaces_readiness_host() -> None:
    """An Agent not sharing the platform process's network namespace
    (ADR-0017 Decision 5, e.g. summarize-agent) must bind every interface to
    be reachable from the platform container over the Compose network --
    loopback there is only reachable from inside the Agent's own container."""
    values = _agent_values()
    values["AI_PLATFORM_AGENT_READINESS_HOST"] = "0.0.0.0"
    config = AgentRuntimeConfig.from_environment(values)
    assert config.readiness_host == "0.0.0.0"


def test_agent_configuration_rejects_other_nonloopback_readiness_hosts() -> None:
    values = _agent_values()
    values["AI_PLATFORM_AGENT_READINESS_HOST"] = "192.168.1.5"
    with pytest.raises(
        RuntimeConfigurationError, match="READINESS_HOST_MUST_BE_LOOPBACK_OR_ALL_INTERFACES"
    ):
        AgentRuntimeConfig.from_environment(values)


def test_agent_configuration_ai_router_fields_are_absent_by_default() -> None:
    config = AgentRuntimeConfig.from_environment(_agent_values())
    assert config.ai_router_anthropic_api_key is None
    assert config.ai_router_anthropic_model is None
    assert config.ai_router_openai_api_key is None
    assert config.ai_router_openai_model is None
    assert config.ai_router_max_output_tokens is None
    assert config.ai_router_provider_timeout_seconds is None


def test_agent_configuration_accepts_full_ai_router_configuration() -> None:
    values = _agent_values()
    values.update(
        {
            "AI_PLATFORM_AGENT_AI_ROUTER_ANTHROPIC_API_KEY_FILE": "secrets/anthropic-key",
            "AI_PLATFORM_AGENT_AI_ROUTER_ANTHROPIC_MODEL": "claude-sonnet-test",
            "AI_PLATFORM_AGENT_AI_ROUTER_OPENAI_API_KEY_FILE": "secrets/openai-key",
            "AI_PLATFORM_AGENT_AI_ROUTER_OPENAI_MODEL": "gpt-test",
            "AI_PLATFORM_AGENT_AI_ROUTER_MAX_OUTPUT_TOKENS": "512",
            "AI_PLATFORM_AGENT_AI_ROUTER_PROVIDER_TIMEOUT_SECONDS": "10.5",
        }
    )
    config = AgentRuntimeConfig.from_environment(values)
    assert config.ai_router_anthropic_api_key is not None
    assert config.ai_router_anthropic_api_key.path == Path("secrets/anthropic-key")
    assert config.ai_router_anthropic_model == "claude-sonnet-test"
    assert config.ai_router_openai_api_key is not None
    assert config.ai_router_openai_api_key.path == Path("secrets/openai-key")
    assert config.ai_router_openai_model == "gpt-test"
    assert config.ai_router_max_output_tokens == 512
    assert config.ai_router_provider_timeout_seconds == 10.5


def test_agent_configuration_accepts_partial_ai_router_configuration() -> None:
    values = _agent_values()
    values["AI_PLATFORM_AGENT_AI_ROUTER_ANTHROPIC_MODEL"] = "claude-sonnet-test"
    config = AgentRuntimeConfig.from_environment(values)
    assert config.ai_router_anthropic_model == "claude-sonnet-test"
    assert config.ai_router_anthropic_api_key is None
    assert config.ai_router_openai_model is None


def test_agent_configuration_rejects_out_of_range_max_output_tokens() -> None:
    values = _agent_values()
    values["AI_PLATFORM_AGENT_AI_ROUTER_MAX_OUTPUT_TOKENS"] = "0"
    with pytest.raises(RuntimeConfigurationError, match="OUT_OF_RANGE"):
        AgentRuntimeConfig.from_environment(values)


def test_secret_file_reference_never_accepts_an_empty_value(tmp_path: Path) -> None:
    secret = tmp_path / "secret"
    secret.write_text("\n", encoding="utf-8")
    with pytest.raises(RuntimeConfigurationError, match="SECRET_FILE_EMPTY"):
        SecretFileReference(secret).read()
