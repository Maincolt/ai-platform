"""Concrete Sprint 6 composition for the platform and Test Agent processes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

import httpx
from fastapi import FastAPI

from ai_platform.adapters.ai_router.anthropic_adapter import (
    AnthropicProviderAdapter,
    AnthropicProviderConfig,
)
from ai_platform.adapters.ai_router.openai_adapter import (
    OpenAIProviderAdapter,
    OpenAIProviderConfig,
)
from ai_platform.adapters.ai_router.provider import ProviderAdapter
from ai_platform.adapters.ai_router.router import FallbackAIRouter
from ai_platform.adapters.event_bus.consumer import KafkaEventConsumer
from ai_platform.adapters.event_bus.health import KafkaBrokerHealth
from ai_platform.adapters.event_bus.producer import KafkaEventPublisher
from ai_platform.adapters.event_bus.quarantine import (
    KafkaQuarantinePublisher,
    KafkaTransportQuarantineCoordinator,
)
from ai_platform.adapters.event_bus.security import (
    KafkaSecurityConfig,
    KafkaSecurityProtocol,
)
from ai_platform.adapters.event_bus.topics import KafkaTopicMapping, TopicBinding
from ai_platform.adapters.persistence import (
    AsyncPsycopgPool,
    PsycopgAgentPersistence,
    PsycopgOrchestratorPersistence,
    PsycopgOutboxTransaction,
    PsycopgTransportRejectionTransaction,
)
from ai_platform.adapters.persistence.outbox import OutboxRecoveryPolicy
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
from ai_platform.api.app import app as workflow_api_app
from ai_platform.api.app import configure_app_state
from ai_platform.api.context import LocalDevelopmentAuthorizationPolicy
from ai_platform.api.dependencies import AppState
from ai_platform.orchestrator.application.candidate_selection import (
    CandidateSelectionConfigurationError,
)
from ai_platform.orchestrator.application.deadline import DeadlineReconciler
from ai_platform.orchestrator.application.registry_candidate_selector import (
    RegistryCandidateSelector,
)
from ai_platform.orchestrator.application.submission import SubmissionOrchestrator
from ai_platform.orchestrator.application.terminal import TerminalEventProcessor
from ai_platform.orchestrator.domain.selection import SelectionIntent
from ai_platform.orchestrator.registry.snapshot import RegistrySnapshot
from ai_platform.ports.event_bus import LogicalChannel, LogicalSubscription
from ai_platform.ports.persistence.outbox import OutboxTransactionPort
from ai_platform.ports.persistence.recovery import TransportRejectionTransactionPort
from ai_platform.ports.persistence.transactions import (
    AgentOutcomeTransactionPort,
    DeadlineTransactionPort,
    TerminalOutcomeTransactionPort,
)
from ai_platform.runtime.configuration import (
    AgentRuntimeConfig,
    CommonRuntimeConfig,
    PlatformRuntimeConfig,
    RuntimeConfigurationError,
    SecretFileReference,
)
from ai_platform.runtime.consumer import EventConsumerWorker
from ai_platform.runtime.contracts import JsonSchemaMessageValidator
from ai_platform.runtime.handlers import (
    CommandExecutorPort,
    ExecuteTaskDeliveryHandler,
    TerminalOutcomeDeliveryHandler,
)
from ai_platform.runtime.health import CoreReadiness
from ai_platform.runtime.ids import Uuid7IdentifierFactory
from ai_platform.runtime.lifecycle import (
    AsyncResource,
    ManagedService,
    PeriodicService,
    ProcessLifecycle,
)
from ai_platform.runtime.loading import (
    ArtifactLoadingError,
    load_agent_deployment_declaration,
    load_canonical_message_schemas,
    load_registry_artifact,
)
from ai_platform.runtime.publisher import OutboxPublisherWorker
from ai_platform.runtime.readiness import (
    AgentReadinessClient,
    AgentReadinessSnapshot,
    AgentReadinessState,
    CachedAgentAvailability,
    create_agent_readiness_app,
)
from ai_platform.runtime.services import (
    OutboxPublisherService,
    PassivePublisherService,
    StartupGateResource,
    UvicornService,
)
from ai_platform.shared.identifiers import AgentId

ServerFactory = Callable[[FastAPI, str, int], ManagedService]


class _RuntimeHealth:
    def __init__(self) -> None:
        self._healthy = False

    def mark_started(self) -> None:
        self._healthy = True

    def mark_stopping(self) -> None:
        self._healthy = False

    async def check(self) -> bool:
        return self._healthy


class _HttpClientResource:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        await self._client.aclose()


class _UnavailableCandidateSelector:
    def select(
        self,
        *,
        capability_name: str,
        capability_version: str,
        command_contract_name: str,
        command_contract_version: str,
        event_contract_names: tuple[str, ...],
        event_contract_versions: tuple[str, ...],
        environment: str,
        now: datetime,
    ) -> SelectionIntent:
        raise CandidateSelectionConfigurationError("REGISTRY_UNAVAILABLE")


@dataclass(frozen=True, slots=True)
class PlatformProcess:
    app: FastAPI
    app_state: AppState
    registry: RegistrySnapshot | None
    lifecycle: ProcessLifecycle

    async def start(self) -> None:
        await self.lifecycle.start()

    async def wait_for_exit(self) -> None:
        await self.lifecycle.wait_for_exit()

    async def stop(self) -> bool:
        return await self.lifecycle.stop()


@dataclass(frozen=True, slots=True)
class AgentProcess:
    readiness_app: FastAPI
    readiness_state: AgentReadinessState
    lifecycle: ProcessLifecycle

    async def start(self) -> None:
        await self.lifecycle.start()

    async def wait_for_exit(self) -> None:
        await self.lifecycle.wait_for_exit()

    async def stop(self) -> bool:
        return await self.lifecycle.stop()


def build_platform_process(
    config: PlatformRuntimeConfig,
    *,
    server_factory: ServerFactory | None = None,
) -> PlatformProcess:
    """Build the platform without contacting the configured Agent."""
    try:
        registry = load_registry_artifact(config.registry_path)
    except ArtifactLoadingError:
        registry = None
    registry_loaded = registry is not None
    producer_security = _security(
        config,
        username=config.kafka_producer_username,
        password=config.kafka_producer_password,
    )
    consumer_security = _security(
        config,
        username=config.kafka_consumer_username,
        password=config.kafka_consumer_password,
    )
    topics = _topic_mapping(config)
    pool = _pool(config, component_schema="orchestrator")
    persistence = PsycopgOrchestratorPersistence(pool)
    outbox = PsycopgOutboxTransaction(
        pool,
        recovery_policy=OutboxRecoveryPolicy(
            max_publication_attempts=config.outbox_maximum_publication_attempts
        ),
    )
    rejections = PsycopgTransportRejectionTransaction(pool)

    availability = CachedAgentAvailability(ttl_seconds=config.readiness_ttl_seconds)
    readiness_http_client = httpx.AsyncClient()
    # One client per distinct readiness_url (ADR-0017 Decision 5): bindings
    # are not uniformly reachable at the same address, so a single shared
    # client can no longer serve every binding the way it could when only
    # one Agent class existed.
    readiness_clients: dict[str, AgentReadinessClient] = {}
    if registry is None:
        candidate_selector = _UnavailableCandidateSelector()
    else:
        readiness_credential = config.readiness_credential.read()
        for binding in registry.bindings:
            if binding.readiness_url in readiness_clients:
                continue
            readiness_clients[binding.readiness_url] = AgentReadinessClient(
                client=readiness_http_client,
                readiness_url=binding.readiness_url,
                credential=readiness_credential,
                cache=availability,
                timeout_seconds=config.readiness_timeout_seconds,
            )
        candidate_selector = RegistryCandidateSelector(
            snapshot=registry,
            availability_port=availability,
            selection_policy_version="1.0",
        )
    identifier_factory = Uuid7IdentifierFactory()
    submission = SubmissionOrchestrator(
        accepted_request_query=persistence,
        request_access_audit=persistence,
        workflow_query=persistence,
        submission_transaction=persistence,
        candidate_selector=candidate_selector,
        id_factory=identifier_factory,
        orchestrator_component="orchestrator",
        orchestrator_instance_id=config.orchestrator_instance_id,
    )
    terminal = TerminalEventProcessor(transaction=cast(TerminalOutcomeTransactionPort, persistence))
    deadline = DeadlineReconciler(
        transaction=cast(DeadlineTransactionPort, persistence),
        batch_size=config.deadline_batch_size,
    )

    command_publisher = KafkaEventPublisher(
        bootstrap_servers=config.kafka_bootstrap_servers,
        client_id=f"{config.orchestrator_instance_id}-command-publisher",
        topic_mapping=topics,
        security=producer_security,
        environment=config.environment,
    )
    command_publisher_worker = OutboxPublisherWorker(
        outbox=cast(OutboxTransactionPort, outbox),
        publisher=command_publisher,
        logical_channel=LogicalChannel.TASK_COMMANDS,
        publisher_instance_id=config.orchestrator_instance_id,
        claim_ttl=timedelta(seconds=config.outbox_claim_ttl_seconds),
        publish_timeout_seconds=config.publish_timeout_seconds,
        idle_delay_seconds=config.worker_idle_delay_seconds,
    )

    broker_health = KafkaBrokerHealth(
        bootstrap_servers=config.kafka_bootstrap_servers,
        client_id=f"{config.orchestrator_instance_id}-startup-probe",
        security=producer_security,
        timeout_seconds=config.database_timeout_seconds,
    )
    runtime_health = _RuntimeHealth()
    readiness = CoreReadiness(
        {
            "database": _database_probe(pool),
            "event_bus": broker_health.check,
            "registry": _constant_probe(registry_loaded),
            "runtime": runtime_health.check,
        },
        timeout_seconds=config.database_timeout_seconds,
    )
    app_state = AppState(
        orchestrator_persistence=persistence,
        agent_persistence=None,
        workflow_access_query=persistence,
        security_policy=LocalDevelopmentAuthorizationPolicy(),
        submission_orchestrator=submission,
        terminal_event_processor=terminal,
        readiness=readiness,
        registry_loaded=registry_loaded,
        task_result_timeout=timedelta(seconds=config.task_result_timeout_seconds),
        registry_snapshot=registry,
        availability_port=availability if registry is not None else None,
    )
    configure_app_state(app_state)

    async def refresh_agent_availability() -> None:
        if registry is None:
            return
        now = datetime.now(UTC)
        for binding in registry.bindings:
            if not binding.enabled:
                continue
            readiness_client = readiness_clients[binding.readiness_url]
            await readiness_client.refresh(
                environment=binding.environment,
                agent_id=binding.agent_id,
                declaration_revision=registry.revision,
                declaration_digest=binding.deployment_declaration_digest,
                capability_name=binding.capability_name,
                capability_version=binding.capability_version,
                accepted_command_contracts=tuple(
                    (binding.command_contract_name, version)
                    for version in binding.command_contract_versions
                ),
                produced_event_contracts=tuple(
                    zip(
                        binding.event_contract_names,
                        binding.event_contract_versions,
                        strict=True,
                    )
                ),
                now=now,
            )

    async def reconcile_deadlines() -> None:
        await deadline.reconcile(now=datetime.now(UTC))

    actual_server_factory = server_factory or _server_service
    services: list[ManagedService] = [
        actual_server_factory(workflow_api_app, config.api_host, config.api_port),
        OutboxPublisherService(command_publisher_worker),
        PeriodicService(
            reconcile_deadlines,
            interval_seconds=config.deadline_interval_seconds,
        ),
    ]
    resources: list[AsyncResource] = [pool, StartupGateResource(broker_health.require_available)]

    def compose_outcome_recovery() -> None:
        schemas = load_canonical_message_schemas(
            config.contract_schema_directory,
            contract_names=("TaskCompleted", "TaskFailed"),
        )
        outcome_subscription = LogicalSubscription(
            identity=config.outcome_logical_subscription_id,
            channel=LogicalChannel.TASK_OUTCOMES,
        )
        outcome_consumer = KafkaEventConsumer(
            bootstrap_servers=config.kafka_bootstrap_servers,
            client_id=f"{config.orchestrator_instance_id}-outcome-consumer",
            group_id=config.outcome_consumer_group_id,
            subscription=outcome_subscription,
            topic_mapping=topics,
            security=consumer_security,
        )
        quarantine_publisher = KafkaQuarantinePublisher(
            bootstrap_servers=config.kafka_bootstrap_servers,
            client_id=f"{config.orchestrator_instance_id}-outcome-quarantine",
            topic_mapping=topics,
            security=consumer_security,
        )
        quarantine = KafkaTransportQuarantineCoordinator(
            metadata_provider=outcome_consumer,
            subscription=outcome_subscription,
            rejections=cast(TransportRejectionTransactionPort, rejections),
            publisher=quarantine_publisher,
            topic_mapping=topics,
            publish_timeout_seconds=config.publish_timeout_seconds,
        )
        outcome_handler = TerminalOutcomeDeliveryHandler(
            validator=JsonSchemaMessageValidator(schemas),
            processor=terminal,
            quarantine=quarantine,
            environment=config.environment,
            logical_consumer_id=config.outcome_logical_subscription_id,
        )
        outcome_worker = EventConsumerWorker(
            consumer=outcome_consumer,
            handler=outcome_handler,
            retry_exhaustion_handler=quarantine,
            acknowledgement_observer=quarantine,
            poll_timeout_seconds=config.consumer_poll_timeout_seconds,
            idle_delay_seconds=config.worker_idle_delay_seconds,
            retry_delay_seconds=config.consumer_retry_delay_seconds,
            maximum_processing_attempts=config.consumer_maximum_processing_attempts,
        )

        async def reconcile_outcome_quarantine() -> None:
            await quarantine.reconcile_confirmed_offsets(
                limit=config.quarantine_reconciliation_limit,
                query_timeout_seconds=config.quarantine_query_timeout_seconds,
            )

        resources.extend(
            (
                StartupGateResource(reconcile_outcome_quarantine),
                _HttpClientResource(readiness_http_client),
            )
        )
        services.extend(
            (
                outcome_worker,
                PassivePublisherService(quarantine_publisher),
                PeriodicService(
                    refresh_agent_availability,
                    interval_seconds=config.readiness_refresh_interval_seconds,
                ),
            )
        )

    compose_outcome_recovery()

    lifecycle = ProcessLifecycle(
        resources=resources,
        services=services,
        startup_timeout_seconds=config.startup_timeout_seconds,
        shutdown_timeout_seconds=config.shutdown_grace_seconds,
        on_started=runtime_health.mark_started,
        on_stopping=runtime_health.mark_stopping,
        on_service_failure=runtime_health.mark_stopping,
    )
    return PlatformProcess(
        app=workflow_api_app,
        app_state=app_state,
        registry=registry,
        lifecycle=lifecycle,
    )


def build_agent_process(
    config: AgentRuntimeConfig,
    *,
    server_factory: ServerFactory | None = None,
) -> AgentProcess:
    """Build the deterministic Test Agent with readiness initially false."""
    agent_id = AgentId(config.agent_id)
    declaration_revision, declaration = load_agent_deployment_declaration(
        config.declaration_path,
        environment=config.environment,
        agent_id=agent_id,
        implementation_identity=config.agent_component,
        declaration_digest=config.declaration_digest,
    )
    schemas = load_canonical_message_schemas(
        config.contract_schema_directory,
        contract_names=("ExecuteTask",),
    )
    producer_security = _security(
        config,
        username=config.kafka_producer_username,
        password=config.kafka_producer_password,
    )
    consumer_security = _security(
        config,
        username=config.kafka_consumer_username,
        password=config.kafka_consumer_password,
    )
    topics = _topic_mapping(config)
    pool = _pool(config, component_schema="agent")
    persistence = PsycopgAgentPersistence(pool)
    outbox = PsycopgOutboxTransaction(
        pool,
        recovery_policy=OutboxRecoveryPolicy(
            max_publication_attempts=config.outbox_maximum_publication_attempts
        ),
    )
    rejections = PsycopgTransportRejectionTransaction(pool)
    executor = _build_executor(
        declaration.capability_name,
        config=config,
        agent_id=agent_id,
        persistence=persistence,
    )

    outcome_publisher = KafkaEventPublisher(
        bootstrap_servers=config.kafka_bootstrap_servers,
        client_id=f"{config.publisher_instance_id}-outcome-publisher",
        topic_mapping=topics,
        security=producer_security,
    )
    command_subscription = LogicalSubscription(
        identity=config.command_logical_subscription_id,
        channel=LogicalChannel.TASK_COMMANDS,
    )
    command_consumer = KafkaEventConsumer(
        bootstrap_servers=config.kafka_bootstrap_servers,
        client_id=f"{config.agent_id}-command-consumer",
        group_id=config.command_consumer_group_id,
        subscription=command_subscription,
        topic_mapping=topics,
        security=consumer_security,
        maximum_in_flight=config.maximum_concurrency,
    )
    quarantine_publisher = KafkaQuarantinePublisher(
        bootstrap_servers=config.kafka_bootstrap_servers,
        client_id=f"{config.agent_id}-command-quarantine",
        topic_mapping=topics,
        security=consumer_security,
    )
    quarantine = KafkaTransportQuarantineCoordinator(
        metadata_provider=command_consumer,
        subscription=command_subscription,
        rejections=cast(TransportRejectionTransactionPort, rejections),
        publisher=quarantine_publisher,
        topic_mapping=topics,
        publish_timeout_seconds=config.publish_timeout_seconds,
    )
    command_handler = ExecuteTaskDeliveryHandler(
        validator=JsonSchemaMessageValidator(schemas),
        executor=executor,
        quarantine=quarantine,
        expected_orchestrator_component="orchestrator",
        expected_agent_component=config.agent_component,
        expected_agent_id=config.agent_id,
    )
    command_worker = EventConsumerWorker(
        consumer=command_consumer,
        handler=command_handler,
        retry_exhaustion_handler=quarantine,
        acknowledgement_observer=quarantine,
        poll_timeout_seconds=config.consumer_poll_timeout_seconds,
        idle_delay_seconds=config.worker_idle_delay_seconds,
        retry_delay_seconds=config.consumer_retry_delay_seconds,
        maximum_processing_attempts=config.consumer_maximum_processing_attempts,
        maximum_concurrency=config.maximum_concurrency,
    )
    outcome_publisher_worker = OutboxPublisherWorker(
        outbox=cast(OutboxTransactionPort, outbox),
        publisher=outcome_publisher,
        logical_channel=LogicalChannel.TASK_OUTCOMES,
        publisher_instance_id=config.publisher_instance_id,
        claim_ttl=timedelta(seconds=config.outbox_claim_ttl_seconds),
        publish_timeout_seconds=config.publish_timeout_seconds,
        idle_delay_seconds=config.worker_idle_delay_seconds,
    )
    readiness_state = AgentReadinessState(
        AgentReadinessSnapshot(
            environment=config.environment,
            agent_id=agent_id,
            declaration_revision=declaration_revision,
            declaration_digest=config.declaration_digest,
            capabilities=((declaration.capability_name, declaration.capability_version),),
            accepted_command_contracts=tuple(
                (declaration.command_contract_name, version)
                for version in declaration.command_contract_versions
            ),
            produced_event_contracts=tuple(
                zip(
                    declaration.event_contract_names,
                    declaration.event_contract_versions,
                    strict=True,
                )
            ),
            ready=False,
            draining=False,
        )
    )
    readiness_app = create_agent_readiness_app(
        state=readiness_state,
        readiness_credential=config.readiness_credential.read(),
    )
    broker_health = KafkaBrokerHealth(
        bootstrap_servers=config.kafka_bootstrap_servers,
        client_id=f"{config.agent_id}-startup-probe",
        security=producer_security,
        timeout_seconds=config.database_timeout_seconds,
    )
    services: list[ManagedService] = [
        command_worker,
        OutboxPublisherService(outcome_publisher_worker),
        PassivePublisherService(quarantine_publisher),
    ]
    actual_server_factory = server_factory or _server_service
    services.append(
        actual_server_factory(
            readiness_app,
            config.readiness_host,
            config.readiness_port,
        )
    )

    async def reconcile_command_quarantine() -> None:
        await quarantine.reconcile_confirmed_offsets(
            limit=config.quarantine_reconciliation_limit,
            query_timeout_seconds=config.quarantine_query_timeout_seconds,
        )

    lifecycle = ProcessLifecycle(
        resources=(
            pool,
            StartupGateResource(broker_health.require_available),
            StartupGateResource(reconcile_command_quarantine),
        ),
        services=services,
        startup_timeout_seconds=config.startup_timeout_seconds,
        shutdown_timeout_seconds=config.shutdown_grace_seconds,
        on_started=lambda: readiness_state.set_ready(True),
        on_stopping=readiness_state.start_draining,
        on_service_failure=lambda: readiness_state.set_ready(False),
    )
    return AgentProcess(
        readiness_app=readiness_app,
        readiness_state=readiness_state,
        lifecycle=lifecycle,
    )


def _build_executor(
    capability_name: str,
    *,
    config: AgentRuntimeConfig,
    agent_id: AgentId,
    persistence: PsycopgAgentPersistence,
) -> CommandExecutorPort:
    """Select the Agent executor for `declaration.capability_name`.

    Fails closed: an unrecognized capability name never silently falls
    back to `TestAgent` (or anything else) -- it is a configuration error.
    """
    outcome_transaction = cast(AgentOutcomeTransactionPort, persistence)
    if capability_name == WORD_COUNT_CAPABILITY_NAME:
        return TestAgent(
            environment=config.environment,
            agent_deployment_id=agent_id,
            agent_component=config.agent_component,
            outcome_transaction=outcome_transaction,
            id_factory=Uuid7IdentifierFactory(),
        )
    if capability_name == SUMMARIZE_CAPABILITY_NAME:
        return SummarizeAgent(
            environment=config.environment,
            agent_deployment_id=agent_id,
            agent_component=config.agent_component,
            outcome_transaction=outcome_transaction,
            id_factory=Uuid7IdentifierFactory(),
            ai_router=_build_ai_router(config),
            max_output_tokens=_require_ai_router_int(config, "ai_router_max_output_tokens"),
        )
    if capability_name == REVIEW_CAPABILITY_NAME:
        return ReviewAgent(
            environment=config.environment,
            agent_deployment_id=agent_id,
            agent_component=config.agent_component,
            outcome_transaction=outcome_transaction,
            id_factory=Uuid7IdentifierFactory(),
            ai_router=_build_ai_router(config),
            max_output_tokens=_require_ai_router_int(config, "ai_router_max_output_tokens"),
        )
    raise RuntimeConfigurationError(f"UNSUPPORTED_AGENT_CAPABILITY:{capability_name}")


# ADR-0017 Decision 3: the specific Claude/OpenAI models approved for
# text.summarize, chosen for cost/latency suitability against short-input
# summarization. Changing this list is a durable, reviewable ADR change
# (edit this ADR or supersede it), not a silent config edit -- enforced
# here in code specifically so an unreviewed model change cannot ship
# silently through a Compose/environment-variable edit alone.
#
# ADR-0018 Decision 5 deliberately left code.review's own model approval
# undecided at acceptance time. The repository owner has since decided
# (during this deployment-wiring PR) that code.review reuses this exact
# list rather than requiring a separately-approved one, since both
# capabilities share the same cost/latency profile -- see ADR-0018's
# Implementation Status section for that decision's record. A model wanted
# for code.review specifically, and not on this list, still requires a
# durable ADR change here, same as it would for text.summarize.
_APPROVED_ANTHROPIC_MODELS = frozenset({"claude-haiku-4-5"})
_APPROVED_OPENAI_MODELS = frozenset({"gpt-5-mini"})


def _build_ai_router(config: AgentRuntimeConfig) -> FallbackAIRouter:
    providers: list[ProviderAdapter] = []
    if (
        config.ai_router_anthropic_api_key is not None
        or config.ai_router_anthropic_model is not None
    ):
        providers.append(
            AnthropicProviderAdapter(
                AnthropicProviderConfig(
                    api_key=_require_ai_router_secret(config, "ai_router_anthropic_api_key"),
                    model=_require_approved_ai_router_model(
                        config,
                        "ai_router_anthropic_model",
                        approved=_APPROVED_ANTHROPIC_MODELS,
                    ),
                )
            )
        )
    if config.ai_router_openai_api_key is not None or config.ai_router_openai_model is not None:
        providers.append(
            OpenAIProviderAdapter(
                OpenAIProviderConfig(
                    api_key=_require_ai_router_secret(config, "ai_router_openai_api_key"),
                    model=_require_approved_ai_router_model(
                        config,
                        "ai_router_openai_model",
                        approved=_APPROVED_OPENAI_MODELS,
                    ),
                )
            )
        )
    if not providers:
        raise RuntimeConfigurationError("MISSING_AI_ROUTER_PROVIDER_CONFIGURATION")
    return FallbackAIRouter(providers)


def _require_ai_router_secret(config: AgentRuntimeConfig, field_name: str) -> str:
    reference = getattr(config, field_name)
    if reference is None:
        raise RuntimeConfigurationError(f"MISSING_CONFIGURATION:{field_name}")
    return cast(SecretFileReference, reference).read()


def _require_ai_router_str(config: AgentRuntimeConfig, field_name: str) -> str:
    value = getattr(config, field_name)
    if value is None:
        raise RuntimeConfigurationError(f"MISSING_CONFIGURATION:{field_name}")
    return cast(str, value)


def _require_approved_ai_router_model(
    config: AgentRuntimeConfig, field_name: str, *, approved: frozenset[str]
) -> str:
    """Fail closed on an unapproved model (ADR-0017 Decision 3)."""
    value = _require_ai_router_str(config, field_name)
    if value not in approved:
        raise RuntimeConfigurationError(f"UNAPPROVED_AI_ROUTER_MODEL:{field_name}:{value}")
    return value


def _require_ai_router_int(config: AgentRuntimeConfig, field_name: str) -> int:
    value = getattr(config, field_name)
    if value is None:
        raise RuntimeConfigurationError(f"MISSING_CONFIGURATION:{field_name}")
    return cast(int, value)


def _security(
    config: CommonRuntimeConfig,
    *,
    username: str,
    password: SecretFileReference,
) -> KafkaSecurityConfig:
    protocol = KafkaSecurityProtocol[config.kafka_security_protocol]
    return KafkaSecurityConfig(
        security_protocol=protocol,
        username=username,
        password=password.read(),
        ca_file=None if config.kafka_ca_file is None else str(config.kafka_ca_file),
    )


def _topic_mapping(config: CommonRuntimeConfig) -> KafkaTopicMapping:
    return KafkaTopicMapping(
        (
            TopicBinding(
                logical_channel=LogicalChannel.TASK_COMMANDS,
                topic=config.task_commands_topic,
                quarantine_topic=config.task_commands_quarantine_topic,
            ),
            TopicBinding(
                logical_channel=LogicalChannel.TASK_OUTCOMES,
                topic=config.task_outcomes_topic,
                quarantine_topic=config.task_outcomes_quarantine_topic,
            ),
        )
    )


_EXPECTED_SCHEMA_VERSION: dict[str, int] = {
    # Bump alongside the latest applied infrastructure/migrations/*.sql for
    # each component so a stale database is rejected at startup rather than
    # silently misread.
    "orchestrator": 3,
    "agent": 4,
}


def _pool(config: CommonRuntimeConfig, *, component_schema: str) -> AsyncPsycopgPool:
    return AsyncPsycopgPool(
        config.database_dsn.read(),
        component_schema=component_schema,
        expected_schema_version=_EXPECTED_SCHEMA_VERSION[component_schema],
        min_size=config.database_pool_min_size,
        max_size=config.database_pool_max_size,
        timeout_seconds=config.database_timeout_seconds,
    )


def _database_probe(
    pool: AsyncPsycopgPool,
) -> Callable[[], Awaitable[bool]]:
    async def check() -> bool:
        try:
            async with pool.connection() as connection:
                row = await (await connection.execute("SELECT 1")).fetchone()
        except Exception:
            return False
        return row is not None and row[0] == 1

    return check


def _constant_probe(value: bool) -> Callable[[], Awaitable[bool]]:
    async def check() -> bool:
        return value

    return check


def _server_service(app: FastAPI, host: str, port: int) -> ManagedService:
    return UvicornService(app=app, host=host, port=port)
