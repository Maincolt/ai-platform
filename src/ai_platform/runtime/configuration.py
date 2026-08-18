"""Validated environment configuration for the two local runtime processes."""

import ipaddress
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class RuntimeConfigurationError(ValueError):
    """Configuration is absent, unsafe, or inconsistent."""


@dataclass(frozen=True, slots=True)
class SecretFileReference:
    """Reference a secret without putting its value in configuration or logs."""

    path: Path

    def read(self) -> str:
        try:
            value = self.path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeConfigurationError("REQUIRED_SECRET_FILE_UNAVAILABLE") from exc
        if not value:
            raise RuntimeConfigurationError("REQUIRED_SECRET_FILE_EMPTY")
        return value


@dataclass(frozen=True, slots=True)
class CommonRuntimeConfig:
    environment: str
    database_dsn: SecretFileReference
    database_pool_min_size: int
    database_pool_max_size: int
    database_timeout_seconds: float
    kafka_bootstrap_servers: str
    kafka_security_protocol: str
    kafka_ca_file: Path | None
    task_commands_topic: str
    task_commands_quarantine_topic: str
    task_outcomes_topic: str
    task_outcomes_quarantine_topic: str
    contract_schema_directory: Path
    publish_timeout_seconds: float
    consumer_poll_timeout_seconds: float
    consumer_retry_delay_seconds: float
    consumer_maximum_processing_attempts: int
    worker_idle_delay_seconds: float
    outbox_claim_ttl_seconds: float
    outbox_maximum_publication_attempts: int
    quarantine_reconciliation_limit: int
    quarantine_query_timeout_seconds: float
    startup_timeout_seconds: float
    shutdown_grace_seconds: float


@dataclass(frozen=True, slots=True)
class PlatformRuntimeConfig(CommonRuntimeConfig):
    kafka_producer_username: str
    kafka_producer_password: SecretFileReference
    kafka_consumer_username: str
    kafka_consumer_password: SecretFileReference
    api_host: str
    api_port: int
    local_policy_enabled: bool
    registry_path: Path
    readiness_credential: SecretFileReference
    orchestrator_instance_id: str
    outcome_consumer_group_id: str
    outcome_logical_subscription_id: str
    deadline_interval_seconds: float
    deadline_batch_size: int
    readiness_timeout_seconds: float
    readiness_ttl_seconds: float
    readiness_refresh_interval_seconds: float
    task_result_timeout_seconds: float
    agent_database_dsn: SecretFileReference | None = None
    """ADR-0032: an optional second DSN, authenticated as the same
    `agent`-schema role every autonomous role's own DSN already uses, so
    the dashboard's autonomous-status endpoint can read
    `agent.autonomous_*` state. Read-only in practice -- `platform` never
    calls a write method on the resulting port. Left unset, the endpoint
    degrades to an inert response rather than platform failing to
    start."""

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> PlatformRuntimeConfig:
        values = os.environ if environment is None else environment
        common = _common(values, prefix="AI_PLATFORM_ORCHESTRATOR_")
        api_host = _required(values, "AI_PLATFORM_API_HOST")
        if not _is_loopback_literal(api_host):
            raise RuntimeConfigurationError("API_HOST_MUST_BE_LOOPBACK")
        local_policy_enabled = _required(values, "AI_PLATFORM_LOCAL_POLICY_ENABLED") == "true"
        if not local_policy_enabled:
            raise RuntimeConfigurationError("LOCAL_POLICY_REQUIRES_EXPLICIT_OPT_IN")
        return cls(
            environment=common.environment,
            database_dsn=common.database_dsn,
            database_pool_min_size=common.database_pool_min_size,
            database_pool_max_size=common.database_pool_max_size,
            database_timeout_seconds=common.database_timeout_seconds,
            kafka_bootstrap_servers=common.kafka_bootstrap_servers,
            kafka_security_protocol=common.kafka_security_protocol,
            kafka_ca_file=common.kafka_ca_file,
            task_commands_topic=common.task_commands_topic,
            task_commands_quarantine_topic=common.task_commands_quarantine_topic,
            task_outcomes_topic=common.task_outcomes_topic,
            task_outcomes_quarantine_topic=common.task_outcomes_quarantine_topic,
            contract_schema_directory=common.contract_schema_directory,
            publish_timeout_seconds=common.publish_timeout_seconds,
            consumer_poll_timeout_seconds=common.consumer_poll_timeout_seconds,
            consumer_retry_delay_seconds=common.consumer_retry_delay_seconds,
            consumer_maximum_processing_attempts=common.consumer_maximum_processing_attempts,
            worker_idle_delay_seconds=common.worker_idle_delay_seconds,
            outbox_claim_ttl_seconds=common.outbox_claim_ttl_seconds,
            outbox_maximum_publication_attempts=common.outbox_maximum_publication_attempts,
            quarantine_reconciliation_limit=common.quarantine_reconciliation_limit,
            quarantine_query_timeout_seconds=common.quarantine_query_timeout_seconds,
            startup_timeout_seconds=common.startup_timeout_seconds,
            shutdown_grace_seconds=common.shutdown_grace_seconds,
            kafka_producer_username=_required(
                values, "AI_PLATFORM_ORCHESTRATOR_KAFKA_PRODUCER_USERNAME"
            ),
            kafka_producer_password=SecretFileReference(
                Path(
                    _required(
                        values,
                        "AI_PLATFORM_ORCHESTRATOR_KAFKA_PRODUCER_PASSWORD_FILE",
                    )
                )
            ),
            kafka_consumer_username=_required(
                values, "AI_PLATFORM_ORCHESTRATOR_KAFKA_CONSUMER_USERNAME"
            ),
            kafka_consumer_password=SecretFileReference(
                Path(
                    _required(
                        values,
                        "AI_PLATFORM_ORCHESTRATOR_KAFKA_CONSUMER_PASSWORD_FILE",
                    )
                )
            ),
            api_host=api_host,
            api_port=_bounded_int(values, "AI_PLATFORM_API_PORT", 1, 65_535),
            local_policy_enabled=local_policy_enabled,
            registry_path=Path(_required(values, "AI_PLATFORM_REGISTRY_PATH")),
            readiness_credential=SecretFileReference(
                Path(_required(values, "AI_PLATFORM_READINESS_CREDENTIAL_FILE"))
            ),
            orchestrator_instance_id=_required(values, "AI_PLATFORM_ORCHESTRATOR_INSTANCE_ID"),
            outcome_consumer_group_id=_required(
                values, "AI_PLATFORM_ORCHESTRATOR_OUTCOME_CONSUMER_GROUP_ID"
            ),
            outcome_logical_subscription_id=_required(
                values, "AI_PLATFORM_ORCHESTRATOR_OUTCOME_LOGICAL_SUBSCRIPTION_ID"
            ),
            deadline_interval_seconds=_bounded_float(
                values, "AI_PLATFORM_DEADLINE_INTERVAL_SECONDS", 0.1, 3600.0
            ),
            deadline_batch_size=_bounded_int(values, "AI_PLATFORM_DEADLINE_BATCH_SIZE", 1, 10_000),
            readiness_timeout_seconds=_bounded_float(
                values, "AI_PLATFORM_AGENT_READINESS_TIMEOUT_SECONDS", 0.05, 30.0
            ),
            readiness_ttl_seconds=_bounded_float(
                values, "AI_PLATFORM_AGENT_READINESS_TTL_SECONDS", 0.1, 300.0
            ),
            readiness_refresh_interval_seconds=_bounded_float(
                values,
                "AI_PLATFORM_AGENT_READINESS_REFRESH_INTERVAL_SECONDS",
                0.1,
                300.0,
            ),
            task_result_timeout_seconds=_bounded_float(
                values, "AI_PLATFORM_TASK_RESULT_TIMEOUT_SECONDS", 0.1, 86_400.0
            ),
            agent_database_dsn=_optional_secret(
                values, "AI_PLATFORM_ORCHESTRATOR_AGENT_DATABASE_DSN_FILE"
            ),
        )


@dataclass(frozen=True, slots=True)
class AgentRuntimeConfig(CommonRuntimeConfig):
    kafka_producer_username: str
    kafka_producer_password: SecretFileReference
    kafka_consumer_username: str
    kafka_consumer_password: SecretFileReference
    agent_id: str
    readiness_host: str
    readiness_port: int
    readiness_credential: SecretFileReference
    maximum_concurrency: int
    agent_component: str
    declaration_digest: str
    declaration_path: Path
    publisher_instance_id: str
    command_consumer_group_id: str
    command_logical_subscription_id: str
    ai_router_anthropic_api_key: SecretFileReference | None
    ai_router_anthropic_model: str | None
    ai_router_openai_api_key: SecretFileReference | None
    ai_router_openai_model: str | None
    ai_router_max_output_tokens: int | None
    ai_router_provider_timeout_seconds: float | None
    github_token: SecretFileReference | None
    github_project_owner: str | None
    github_project_number: int | None

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> AgentRuntimeConfig:
        values = os.environ if environment is None else environment
        common = _common(values, prefix="AI_PLATFORM_AGENT_")
        readiness_host = _required(values, "AI_PLATFORM_AGENT_READINESS_HOST")
        # Two legitimate patterns (ADR-0017 Decision 5): an Agent sharing
        # the platform process's network namespace (network_mode:
        # "service:platform") binds loopback-only and is reached at
        # 127.0.0.1, exactly as before; an Agent in its own network
        # namespace must bind every interface (0.0.0.0) to be reachable
        # from the platform container at all -- loopback there would only
        # ever be reachable from inside that Agent's own container, never
        # from the platform container that needs to query it. Still not a
        # public exposure: the isolated Compose network is not reachable
        # from the host (infrastructure/README.md), and every readiness
        # request still requires the shared bearer credential.
        if not (_is_loopback_literal(readiness_host) or readiness_host == "0.0.0.0"):
            raise RuntimeConfigurationError("READINESS_HOST_MUST_BE_LOOPBACK_OR_ALL_INTERFACES")
        return cls(
            environment=common.environment,
            database_dsn=common.database_dsn,
            database_pool_min_size=common.database_pool_min_size,
            database_pool_max_size=common.database_pool_max_size,
            database_timeout_seconds=common.database_timeout_seconds,
            kafka_bootstrap_servers=common.kafka_bootstrap_servers,
            kafka_security_protocol=common.kafka_security_protocol,
            kafka_ca_file=common.kafka_ca_file,
            task_commands_topic=common.task_commands_topic,
            task_commands_quarantine_topic=common.task_commands_quarantine_topic,
            task_outcomes_topic=common.task_outcomes_topic,
            task_outcomes_quarantine_topic=common.task_outcomes_quarantine_topic,
            contract_schema_directory=common.contract_schema_directory,
            publish_timeout_seconds=common.publish_timeout_seconds,
            consumer_poll_timeout_seconds=common.consumer_poll_timeout_seconds,
            consumer_retry_delay_seconds=common.consumer_retry_delay_seconds,
            consumer_maximum_processing_attempts=common.consumer_maximum_processing_attempts,
            worker_idle_delay_seconds=common.worker_idle_delay_seconds,
            outbox_claim_ttl_seconds=common.outbox_claim_ttl_seconds,
            outbox_maximum_publication_attempts=common.outbox_maximum_publication_attempts,
            quarantine_reconciliation_limit=common.quarantine_reconciliation_limit,
            quarantine_query_timeout_seconds=common.quarantine_query_timeout_seconds,
            startup_timeout_seconds=common.startup_timeout_seconds,
            shutdown_grace_seconds=common.shutdown_grace_seconds,
            kafka_producer_username=_required(values, "AI_PLATFORM_AGENT_KAFKA_PRODUCER_USERNAME"),
            kafka_producer_password=SecretFileReference(
                Path(_required(values, "AI_PLATFORM_AGENT_KAFKA_PRODUCER_PASSWORD_FILE"))
            ),
            kafka_consumer_username=_required(values, "AI_PLATFORM_AGENT_KAFKA_CONSUMER_USERNAME"),
            kafka_consumer_password=SecretFileReference(
                Path(_required(values, "AI_PLATFORM_AGENT_KAFKA_CONSUMER_PASSWORD_FILE"))
            ),
            agent_id=_required(values, "AI_PLATFORM_AGENT_ID"),
            readiness_host=readiness_host,
            readiness_port=_bounded_int(values, "AI_PLATFORM_AGENT_READINESS_PORT", 1, 65_535),
            readiness_credential=SecretFileReference(
                Path(_required(values, "AI_PLATFORM_READINESS_CREDENTIAL_FILE"))
            ),
            maximum_concurrency=_bounded_int(
                values, "AI_PLATFORM_AGENT_MAXIMUM_CONCURRENCY", 1, 256
            ),
            agent_component=_required(values, "AI_PLATFORM_AGENT_COMPONENT"),
            declaration_digest=_required(values, "AI_PLATFORM_AGENT_DECLARATION_DIGEST"),
            declaration_path=Path(_required(values, "AI_PLATFORM_AGENT_DECLARATION_PATH")),
            publisher_instance_id=_required(values, "AI_PLATFORM_AGENT_PUBLISHER_INSTANCE_ID"),
            command_consumer_group_id=_required(
                values, "AI_PLATFORM_AGENT_COMMAND_CONSUMER_GROUP_ID"
            ),
            command_logical_subscription_id=_required(
                values, "AI_PLATFORM_AGENT_COMMAND_LOGICAL_SUBSCRIPTION_ID"
            ),
            ai_router_anthropic_api_key=_optional_secret(
                values, "AI_PLATFORM_AGENT_AI_ROUTER_ANTHROPIC_API_KEY_FILE"
            ),
            ai_router_anthropic_model=_optional_str(
                values, "AI_PLATFORM_AGENT_AI_ROUTER_ANTHROPIC_MODEL"
            ),
            ai_router_openai_api_key=_optional_secret(
                values, "AI_PLATFORM_AGENT_AI_ROUTER_OPENAI_API_KEY_FILE"
            ),
            ai_router_openai_model=_optional_str(
                values, "AI_PLATFORM_AGENT_AI_ROUTER_OPENAI_MODEL"
            ),
            ai_router_max_output_tokens=_optional_int(
                values, "AI_PLATFORM_AGENT_AI_ROUTER_MAX_OUTPUT_TOKENS", 1, 32_000
            ),
            ai_router_provider_timeout_seconds=_optional_float(
                values, "AI_PLATFORM_AGENT_AI_ROUTER_PROVIDER_TIMEOUT_SECONDS", 0.1, 300.0
            ),
            github_token=_optional_secret(values, "AI_PLATFORM_AGENT_GITHUB_TOKEN_FILE"),
            github_project_owner=_optional_str(values, "AI_PLATFORM_AGENT_GITHUB_PROJECT_OWNER"),
            github_project_number=_optional_int(
                values, "AI_PLATFORM_AGENT_GITHUB_PROJECT_NUMBER", 1, 1_000_000
            ),
        )


@dataclass(frozen=True, slots=True)
class _AutonomousRoleRuntimeConfigBase:
    """Fields shared by every ADR-0026 autonomous-role runtime config
    (`scrum-master`, `product-owner`, and eventually `principal-developer`).
    Deliberately not a `CommonRuntimeConfig` subclass -- these are
    `PeriodicService`-driven processes with no `ExecuteTask` consumption
    and no published events, so none of `CommonRuntimeConfig`'s Kafka/
    contract-schema fields apply. Each role's own config subclasses this
    with only its role-specific credential fields (ADR-0030's Context)."""

    environment: str
    database_dsn: SecretFileReference
    database_pool_min_size: int
    database_pool_max_size: int
    database_timeout_seconds: float
    agent_id: str
    agent_component: str
    readiness_host: str
    readiness_port: int
    readiness_credential: SecretFileReference
    startup_timeout_seconds: float
    shutdown_grace_seconds: float
    ai_router_anthropic_api_key: SecretFileReference | None
    ai_router_anthropic_model: str | None
    ai_router_openai_api_key: SecretFileReference | None
    ai_router_openai_model: str | None
    ai_router_max_output_tokens: int | None
    ai_router_provider_timeout_seconds: float | None
    autonomous_poll_interval_seconds: float
    autonomous_max_actions_per_day: int
    autonomous_max_spend_cents_per_day: int


def _autonomous_role_base(values: Mapping[str, str]) -> _AutonomousRoleRuntimeConfigBase:
    env_name = _required(values, "AI_PLATFORM_ENVIRONMENT")
    if env_name != "development":
        raise RuntimeConfigurationError("SYNTHETIC_POLICY_REQUIRES_DEVELOPMENT")
    pool_min_size = _bounded_int(values, "AI_PLATFORM_AGENT_DATABASE_POOL_MIN_SIZE", 1, 32)
    pool_max_size = _bounded_int(values, "AI_PLATFORM_AGENT_DATABASE_POOL_MAX_SIZE", 1, 64)
    if pool_min_size > pool_max_size:
        raise RuntimeConfigurationError("DATABASE_POOL_MIN_EXCEEDS_MAX")
    readiness_host = _required(values, "AI_PLATFORM_AGENT_READINESS_HOST")
    if not (_is_loopback_literal(readiness_host) or readiness_host == "0.0.0.0"):
        raise RuntimeConfigurationError("READINESS_HOST_MUST_BE_LOOPBACK_OR_ALL_INTERFACES")
    return _AutonomousRoleRuntimeConfigBase(
        environment=env_name,
        database_dsn=SecretFileReference(
            Path(_required(values, "AI_PLATFORM_AGENT_DATABASE_DSN_FILE"))
        ),
        database_pool_min_size=pool_min_size,
        database_pool_max_size=pool_max_size,
        database_timeout_seconds=_bounded_float(
            values, "AI_PLATFORM_AGENT_DATABASE_TIMEOUT_SECONDS", 0.1, 120.0
        ),
        agent_id=_required(values, "AI_PLATFORM_AGENT_ID"),
        agent_component=_required(values, "AI_PLATFORM_AGENT_COMPONENT"),
        readiness_host=readiness_host,
        readiness_port=_bounded_int(values, "AI_PLATFORM_AGENT_READINESS_PORT", 1, 65_535),
        readiness_credential=SecretFileReference(
            Path(_required(values, "AI_PLATFORM_READINESS_CREDENTIAL_FILE"))
        ),
        startup_timeout_seconds=_bounded_float(
            values, "AI_PLATFORM_STARTUP_TIMEOUT_SECONDS", 0.1, 300.0
        ),
        shutdown_grace_seconds=_bounded_float(
            values, "AI_PLATFORM_SHUTDOWN_GRACE_SECONDS", 0.1, 300.0
        ),
        ai_router_anthropic_api_key=_optional_secret(
            values, "AI_PLATFORM_AGENT_AI_ROUTER_ANTHROPIC_API_KEY_FILE"
        ),
        ai_router_anthropic_model=_optional_str(
            values, "AI_PLATFORM_AGENT_AI_ROUTER_ANTHROPIC_MODEL"
        ),
        ai_router_openai_api_key=_optional_secret(
            values, "AI_PLATFORM_AGENT_AI_ROUTER_OPENAI_API_KEY_FILE"
        ),
        ai_router_openai_model=_optional_str(values, "AI_PLATFORM_AGENT_AI_ROUTER_OPENAI_MODEL"),
        ai_router_max_output_tokens=_optional_int(
            values, "AI_PLATFORM_AGENT_AI_ROUTER_MAX_OUTPUT_TOKENS", 1, 32_000
        ),
        ai_router_provider_timeout_seconds=_optional_float(
            values, "AI_PLATFORM_AGENT_AI_ROUTER_PROVIDER_TIMEOUT_SECONDS", 0.1, 300.0
        ),
        autonomous_poll_interval_seconds=_bounded_float(
            values, "AI_PLATFORM_AGENT_AUTONOMOUS_POLL_INTERVAL_SECONDS", 1.0, 86_400.0
        ),
        autonomous_max_actions_per_day=_bounded_int(
            values, "AI_PLATFORM_AGENT_AUTONOMOUS_MAX_ACTIONS_PER_DAY", 1, 10_000
        ),
        autonomous_max_spend_cents_per_day=_bounded_int(
            values, "AI_PLATFORM_AGENT_AUTONOMOUS_MAX_SPEND_CENTS_PER_DAY", 1, 1_000_000
        ),
    )


@dataclass(frozen=True, slots=True)
class ScrumMasterRuntimeConfig(_AutonomousRoleRuntimeConfigBase):
    """ADR-0028: adds `scrum-master-agent`'s GitHub Projects v2 tracker
    credential to the shared autonomous-role base."""

    github_token: SecretFileReference | None
    github_project_owner: str | None
    github_project_number: int | None

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> ScrumMasterRuntimeConfig:
        values = os.environ if environment is None else environment
        base = _autonomous_role_base(values)
        return cls(
            environment=base.environment,
            database_dsn=base.database_dsn,
            database_pool_min_size=base.database_pool_min_size,
            database_pool_max_size=base.database_pool_max_size,
            database_timeout_seconds=base.database_timeout_seconds,
            agent_id=base.agent_id,
            agent_component=base.agent_component,
            readiness_host=base.readiness_host,
            readiness_port=base.readiness_port,
            readiness_credential=base.readiness_credential,
            startup_timeout_seconds=base.startup_timeout_seconds,
            shutdown_grace_seconds=base.shutdown_grace_seconds,
            ai_router_anthropic_api_key=base.ai_router_anthropic_api_key,
            ai_router_anthropic_model=base.ai_router_anthropic_model,
            ai_router_openai_api_key=base.ai_router_openai_api_key,
            ai_router_openai_model=base.ai_router_openai_model,
            ai_router_max_output_tokens=base.ai_router_max_output_tokens,
            ai_router_provider_timeout_seconds=base.ai_router_provider_timeout_seconds,
            autonomous_poll_interval_seconds=base.autonomous_poll_interval_seconds,
            autonomous_max_actions_per_day=base.autonomous_max_actions_per_day,
            autonomous_max_spend_cents_per_day=base.autonomous_max_spend_cents_per_day,
            github_token=_optional_secret(values, "AI_PLATFORM_AGENT_GITHUB_TOKEN_FILE"),
            github_project_owner=_optional_str(values, "AI_PLATFORM_AGENT_GITHUB_PROJECT_OWNER"),
            github_project_number=_optional_int(
                values, "AI_PLATFORM_AGENT_GITHUB_PROJECT_NUMBER", 1, 1_000_000
            ),
        )


@dataclass(frozen=True, slots=True)
class ProductOwnerRuntimeConfig(_AutonomousRoleRuntimeConfigBase):
    """ADR-0030: adds `product-owner-agent`'s GitHub Projects v2 backlog
    credential to the shared autonomous-role base -- the same field
    shape as `ScrumMasterRuntimeConfig`'s GitHub credential (both
    operate on the same board type), read from `product-owner-agent`'s
    own env vars/secret file so each role's container gets its own,
    separately-scoped PAT (ADR-0028 Decision 4's per-role least
    privilege, applied identically here)."""

    github_token: SecretFileReference | None
    github_project_owner: str | None
    github_project_number: int | None

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> ProductOwnerRuntimeConfig:
        values = os.environ if environment is None else environment
        base = _autonomous_role_base(values)
        return cls(
            environment=base.environment,
            database_dsn=base.database_dsn,
            database_pool_min_size=base.database_pool_min_size,
            database_pool_max_size=base.database_pool_max_size,
            database_timeout_seconds=base.database_timeout_seconds,
            agent_id=base.agent_id,
            agent_component=base.agent_component,
            readiness_host=base.readiness_host,
            readiness_port=base.readiness_port,
            readiness_credential=base.readiness_credential,
            startup_timeout_seconds=base.startup_timeout_seconds,
            shutdown_grace_seconds=base.shutdown_grace_seconds,
            ai_router_anthropic_api_key=base.ai_router_anthropic_api_key,
            ai_router_anthropic_model=base.ai_router_anthropic_model,
            ai_router_openai_api_key=base.ai_router_openai_api_key,
            ai_router_openai_model=base.ai_router_openai_model,
            ai_router_max_output_tokens=base.ai_router_max_output_tokens,
            ai_router_provider_timeout_seconds=base.ai_router_provider_timeout_seconds,
            autonomous_poll_interval_seconds=base.autonomous_poll_interval_seconds,
            autonomous_max_actions_per_day=base.autonomous_max_actions_per_day,
            autonomous_max_spend_cents_per_day=base.autonomous_max_spend_cents_per_day,
            github_token=_optional_secret(values, "AI_PLATFORM_AGENT_GITHUB_TOKEN_FILE"),
            github_project_owner=_optional_str(values, "AI_PLATFORM_AGENT_GITHUB_PROJECT_OWNER"),
            github_project_number=_optional_int(
                values, "AI_PLATFORM_AGENT_GITHUB_PROJECT_NUMBER", 1, 1_000_000
            ),
        )


@dataclass(frozen=True, slots=True)
class PrincipalDeveloperRuntimeConfig(_AutonomousRoleRuntimeConfigBase):
    """ADR-0031: adds `principal-developer-agent`'s GitHub source-control
    credential to the shared autonomous-role base -- unlike
    `ScrumMasterRuntimeConfig`/`ProductOwnerRuntimeConfig`, this role
    operates on a repository's pull requests directly, never the
    Projects v2 board, so it needs a repo owner/name pair instead of a
    project owner/number pair, and no project number at all."""

    github_token: SecretFileReference | None
    github_repo_owner: str | None
    github_repo_name: str | None

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> PrincipalDeveloperRuntimeConfig:
        values = os.environ if environment is None else environment
        base = _autonomous_role_base(values)
        return cls(
            environment=base.environment,
            database_dsn=base.database_dsn,
            database_pool_min_size=base.database_pool_min_size,
            database_pool_max_size=base.database_pool_max_size,
            database_timeout_seconds=base.database_timeout_seconds,
            agent_id=base.agent_id,
            agent_component=base.agent_component,
            readiness_host=base.readiness_host,
            readiness_port=base.readiness_port,
            readiness_credential=base.readiness_credential,
            startup_timeout_seconds=base.startup_timeout_seconds,
            shutdown_grace_seconds=base.shutdown_grace_seconds,
            ai_router_anthropic_api_key=base.ai_router_anthropic_api_key,
            ai_router_anthropic_model=base.ai_router_anthropic_model,
            ai_router_openai_api_key=base.ai_router_openai_api_key,
            ai_router_openai_model=base.ai_router_openai_model,
            ai_router_max_output_tokens=base.ai_router_max_output_tokens,
            ai_router_provider_timeout_seconds=base.ai_router_provider_timeout_seconds,
            autonomous_poll_interval_seconds=base.autonomous_poll_interval_seconds,
            autonomous_max_actions_per_day=base.autonomous_max_actions_per_day,
            autonomous_max_spend_cents_per_day=base.autonomous_max_spend_cents_per_day,
            github_token=_optional_secret(values, "AI_PLATFORM_AGENT_GITHUB_TOKEN_FILE"),
            github_repo_owner=_optional_str(values, "AI_PLATFORM_AGENT_GITHUB_REPO_OWNER"),
            github_repo_name=_optional_str(values, "AI_PLATFORM_AGENT_GITHUB_REPO_NAME"),
        )


@dataclass(frozen=True, slots=True)
class FrontendSpecialistRuntimeConfig(_AutonomousRoleRuntimeConfigBase):
    """ADR-0033: adds `frontend-specialist-agent`'s GitHub source-control
    credential to the shared autonomous-role base -- same repo owner/name
    shape as `PrincipalDeveloperRuntimeConfig` (this role also operates
    on pull requests directly, never the Projects v2 board), kept as its
    own config class rather than a third shared base -- two isn't a
    strong enough signal to abstract config construction itself."""

    github_token: SecretFileReference | None
    github_repo_owner: str | None
    github_repo_name: str | None

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> FrontendSpecialistRuntimeConfig:
        values = os.environ if environment is None else environment
        base = _autonomous_role_base(values)
        return cls(
            environment=base.environment,
            database_dsn=base.database_dsn,
            database_pool_min_size=base.database_pool_min_size,
            database_pool_max_size=base.database_pool_max_size,
            database_timeout_seconds=base.database_timeout_seconds,
            agent_id=base.agent_id,
            agent_component=base.agent_component,
            readiness_host=base.readiness_host,
            readiness_port=base.readiness_port,
            readiness_credential=base.readiness_credential,
            startup_timeout_seconds=base.startup_timeout_seconds,
            shutdown_grace_seconds=base.shutdown_grace_seconds,
            ai_router_anthropic_api_key=base.ai_router_anthropic_api_key,
            ai_router_anthropic_model=base.ai_router_anthropic_model,
            ai_router_openai_api_key=base.ai_router_openai_api_key,
            ai_router_openai_model=base.ai_router_openai_model,
            ai_router_max_output_tokens=base.ai_router_max_output_tokens,
            ai_router_provider_timeout_seconds=base.ai_router_provider_timeout_seconds,
            autonomous_poll_interval_seconds=base.autonomous_poll_interval_seconds,
            autonomous_max_actions_per_day=base.autonomous_max_actions_per_day,
            autonomous_max_spend_cents_per_day=base.autonomous_max_spend_cents_per_day,
            github_token=_optional_secret(values, "AI_PLATFORM_AGENT_GITHUB_TOKEN_FILE"),
            github_repo_owner=_optional_str(values, "AI_PLATFORM_AGENT_GITHUB_REPO_OWNER"),
            github_repo_name=_optional_str(values, "AI_PLATFORM_AGENT_GITHUB_REPO_NAME"),
        )


@dataclass(frozen=True, slots=True)
class PostgresSpecialistRuntimeConfig(_AutonomousRoleRuntimeConfigBase):
    """ADR-0033: adds `postgres-specialist-agent`'s GitHub source-control
    credential to the shared autonomous-role base -- see
    `FrontendSpecialistRuntimeConfig`'s docstring; identical shape,
    separate role."""

    github_token: SecretFileReference | None
    github_repo_owner: str | None
    github_repo_name: str | None

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> PostgresSpecialistRuntimeConfig:
        values = os.environ if environment is None else environment
        base = _autonomous_role_base(values)
        return cls(
            environment=base.environment,
            database_dsn=base.database_dsn,
            database_pool_min_size=base.database_pool_min_size,
            database_pool_max_size=base.database_pool_max_size,
            database_timeout_seconds=base.database_timeout_seconds,
            agent_id=base.agent_id,
            agent_component=base.agent_component,
            readiness_host=base.readiness_host,
            readiness_port=base.readiness_port,
            readiness_credential=base.readiness_credential,
            startup_timeout_seconds=base.startup_timeout_seconds,
            shutdown_grace_seconds=base.shutdown_grace_seconds,
            ai_router_anthropic_api_key=base.ai_router_anthropic_api_key,
            ai_router_anthropic_model=base.ai_router_anthropic_model,
            ai_router_openai_api_key=base.ai_router_openai_api_key,
            ai_router_openai_model=base.ai_router_openai_model,
            ai_router_max_output_tokens=base.ai_router_max_output_tokens,
            ai_router_provider_timeout_seconds=base.ai_router_provider_timeout_seconds,
            autonomous_poll_interval_seconds=base.autonomous_poll_interval_seconds,
            autonomous_max_actions_per_day=base.autonomous_max_actions_per_day,
            autonomous_max_spend_cents_per_day=base.autonomous_max_spend_cents_per_day,
            github_token=_optional_secret(values, "AI_PLATFORM_AGENT_GITHUB_TOKEN_FILE"),
            github_repo_owner=_optional_str(values, "AI_PLATFORM_AGENT_GITHUB_REPO_OWNER"),
            github_repo_name=_optional_str(values, "AI_PLATFORM_AGENT_GITHUB_REPO_NAME"),
        )


@dataclass(frozen=True, slots=True)
class BackendSpecialistRuntimeConfig(_AutonomousRoleRuntimeConfigBase):
    """ADR-0034: adds `backend-specialist-agent`'s GitHub source-control
    credential to the shared autonomous-role base -- see
    `FrontendSpecialistRuntimeConfig`'s docstring; identical shape,
    separate role."""

    github_token: SecretFileReference | None
    github_repo_owner: str | None
    github_repo_name: str | None

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> BackendSpecialistRuntimeConfig:
        values = os.environ if environment is None else environment
        base = _autonomous_role_base(values)
        return cls(
            environment=base.environment,
            database_dsn=base.database_dsn,
            database_pool_min_size=base.database_pool_min_size,
            database_pool_max_size=base.database_pool_max_size,
            database_timeout_seconds=base.database_timeout_seconds,
            agent_id=base.agent_id,
            agent_component=base.agent_component,
            readiness_host=base.readiness_host,
            readiness_port=base.readiness_port,
            readiness_credential=base.readiness_credential,
            startup_timeout_seconds=base.startup_timeout_seconds,
            shutdown_grace_seconds=base.shutdown_grace_seconds,
            ai_router_anthropic_api_key=base.ai_router_anthropic_api_key,
            ai_router_anthropic_model=base.ai_router_anthropic_model,
            ai_router_openai_api_key=base.ai_router_openai_api_key,
            ai_router_openai_model=base.ai_router_openai_model,
            ai_router_max_output_tokens=base.ai_router_max_output_tokens,
            ai_router_provider_timeout_seconds=base.ai_router_provider_timeout_seconds,
            autonomous_poll_interval_seconds=base.autonomous_poll_interval_seconds,
            autonomous_max_actions_per_day=base.autonomous_max_actions_per_day,
            autonomous_max_spend_cents_per_day=base.autonomous_max_spend_cents_per_day,
            github_token=_optional_secret(values, "AI_PLATFORM_AGENT_GITHUB_TOKEN_FILE"),
            github_repo_owner=_optional_str(values, "AI_PLATFORM_AGENT_GITHUB_REPO_OWNER"),
            github_repo_name=_optional_str(values, "AI_PLATFORM_AGENT_GITHUB_REPO_NAME"),
        )


def _common(values: Mapping[str, str], *, prefix: str) -> CommonRuntimeConfig:
    environment = _required(values, "AI_PLATFORM_ENVIRONMENT")
    if environment != "development":
        raise RuntimeConfigurationError("SYNTHETIC_POLICY_REQUIRES_DEVELOPMENT")
    protocol = _required(values, f"{prefix}KAFKA_SECURITY_PROTOCOL")
    if protocol not in {"SASL_SSL", "LOCAL_DEVELOPMENT_SASL_PLAINTEXT"}:
        raise RuntimeConfigurationError("UNSUPPORTED_KAFKA_SECURITY_PROTOCOL")
    pool_min_size = _bounded_int(values, f"{prefix}DATABASE_POOL_MIN_SIZE", 1, 32)
    pool_max_size = _bounded_int(values, f"{prefix}DATABASE_POOL_MAX_SIZE", 1, 64)
    if pool_min_size > pool_max_size:
        raise RuntimeConfigurationError("DATABASE_POOL_MIN_EXCEEDS_MAX")
    return CommonRuntimeConfig(
        environment=environment,
        database_dsn=SecretFileReference(Path(_required(values, f"{prefix}DATABASE_DSN_FILE"))),
        database_pool_min_size=pool_min_size,
        database_pool_max_size=pool_max_size,
        database_timeout_seconds=_bounded_float(
            values, f"{prefix}DATABASE_TIMEOUT_SECONDS", 0.1, 120.0
        ),
        kafka_bootstrap_servers=_required(values, "AI_PLATFORM_KAFKA_BOOTSTRAP_SERVERS"),
        kafka_security_protocol=protocol,
        kafka_ca_file=_optional_path(values, "AI_PLATFORM_KAFKA_CA_FILE"),
        task_commands_topic=_required(values, "AI_PLATFORM_TASK_COMMANDS_TOPIC"),
        task_commands_quarantine_topic=_required(
            values, "AI_PLATFORM_TASK_COMMANDS_QUARANTINE_TOPIC"
        ),
        task_outcomes_topic=_required(values, "AI_PLATFORM_TASK_OUTCOMES_TOPIC"),
        task_outcomes_quarantine_topic=_required(
            values, "AI_PLATFORM_TASK_OUTCOMES_QUARANTINE_TOPIC"
        ),
        contract_schema_directory=Path(_required(values, "AI_PLATFORM_CONTRACT_SCHEMA_DIRECTORY")),
        publish_timeout_seconds=_bounded_float(
            values, "AI_PLATFORM_PUBLISH_TIMEOUT_SECONDS", 0.05, 120.0
        ),
        consumer_poll_timeout_seconds=_bounded_float(
            values, "AI_PLATFORM_CONSUMER_POLL_TIMEOUT_SECONDS", 0.05, 30.0
        ),
        consumer_retry_delay_seconds=_bounded_float(
            values, "AI_PLATFORM_CONSUMER_RETRY_DELAY_SECONDS", 0.0, 30.0
        ),
        consumer_maximum_processing_attempts=_bounded_int(
            values, "AI_PLATFORM_CONSUMER_MAXIMUM_PROCESSING_ATTEMPTS", 1, 100
        ),
        worker_idle_delay_seconds=_bounded_float(
            values, "AI_PLATFORM_WORKER_IDLE_DELAY_SECONDS", 0.01, 30.0
        ),
        outbox_claim_ttl_seconds=_bounded_float(
            values, "AI_PLATFORM_OUTBOX_CLAIM_TTL_SECONDS", 0.1, 3600.0
        ),
        outbox_maximum_publication_attempts=_bounded_int(
            values, "AI_PLATFORM_OUTBOX_MAXIMUM_PUBLICATION_ATTEMPTS", 1, 100
        ),
        quarantine_reconciliation_limit=_bounded_int(
            values, "AI_PLATFORM_QUARANTINE_RECONCILIATION_LIMIT", 1, 1_000
        ),
        quarantine_query_timeout_seconds=_bounded_float(
            values, "AI_PLATFORM_QUARANTINE_QUERY_TIMEOUT_SECONDS", 0.05, 30.0
        ),
        startup_timeout_seconds=_bounded_float(
            values, "AI_PLATFORM_STARTUP_TIMEOUT_SECONDS", 0.1, 300.0
        ),
        shutdown_grace_seconds=_bounded_float(
            values, "AI_PLATFORM_SHUTDOWN_GRACE_SECONDS", 0.1, 300.0
        ),
    )


def _required(values: Mapping[str, str], name: str) -> str:
    value = values.get(name)
    if value is None or not value.strip():
        raise RuntimeConfigurationError(f"MISSING_CONFIGURATION:{name}")
    return value.strip()


def _bounded_int(values: Mapping[str, str], name: str, minimum: int, maximum: int) -> int:
    try:
        value = int(_required(values, name))
    except ValueError as exc:
        raise RuntimeConfigurationError(f"INVALID_INTEGER:{name}") from exc
    if not minimum <= value <= maximum:
        raise RuntimeConfigurationError(f"OUT_OF_RANGE:{name}")
    return value


def _bounded_float(values: Mapping[str, str], name: str, minimum: float, maximum: float) -> float:
    try:
        value = float(_required(values, name))
    except ValueError as exc:
        raise RuntimeConfigurationError(f"INVALID_NUMBER:{name}") from exc
    if not minimum <= value <= maximum:
        raise RuntimeConfigurationError(f"OUT_OF_RANGE:{name}")
    return value


def _is_loopback_literal(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def _optional_path(values: Mapping[str, str], name: str) -> Path | None:
    value = values.get(name)
    if value is None:
        return None
    if not value.strip():
        raise RuntimeConfigurationError(f"EMPTY_CONFIGURATION:{name}")
    return Path(value.strip())


def _optional_str(values: Mapping[str, str], name: str) -> str | None:
    value = values.get(name)
    if value is None:
        return None
    if not value.strip():
        raise RuntimeConfigurationError(f"EMPTY_CONFIGURATION:{name}")
    return value.strip()


def _optional_secret(values: Mapping[str, str], name: str) -> SecretFileReference | None:
    path = _optional_path(values, name)
    return None if path is None else SecretFileReference(path)


def _optional_int(values: Mapping[str, str], name: str, minimum: int, maximum: int) -> int | None:
    value = values.get(name)
    if value is None:
        return None
    return _bounded_int(values, name, minimum, maximum)


def _optional_float(
    values: Mapping[str, str], name: str, minimum: float, maximum: float
) -> float | None:
    value = values.get(name)
    if value is None:
        return None
    return _bounded_float(values, name, minimum, maximum)
