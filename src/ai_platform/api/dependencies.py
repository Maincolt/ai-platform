"""Application assembly: wires the in-memory reference ports (Sprint 5) and
Sprint 3's application services into one process-lifetime `AppState`.

This is explicitly a non-production wiring used for deterministic component
tests and the zero-dependency development command. Concrete Phase 6 runtime
composition lives separately and never treats this process-local state as
durable.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ai_platform.api.context import LocalDevelopmentAuthorizationPolicy
from ai_platform.api.ids import Uuid7IdentifierFactory
from ai_platform.api.inmemory_ports import (
    InMemoryAgentPersistence,
    InMemoryOrchestratorPersistence,
)
from ai_platform.orchestrator.application.registry_candidate_selector import (
    RegistryCandidateSelector,
)
from ai_platform.orchestrator.application.submission import SubmissionOrchestrator
from ai_platform.orchestrator.application.terminal import TerminalEventProcessor
from ai_platform.orchestrator.registry.availability import (
    AvailabilityClassification,
    AvailabilityObservation,
    AvailabilityPort,
)
from ai_platform.orchestrator.registry.declarations import CapabilityBinding
from ai_platform.orchestrator.registry.snapshot import load_registry_snapshot
from ai_platform.ports.persistence.transactions import AuthorizedWorkflowQueryPort
from ai_platform.runtime.health import CoreReadinessPort, StaticReadiness
from ai_platform.shared.identifiers import AgentId

ORCHESTRATOR_OUTCOME_CONSUMER_ID = "orchestrator-outcome-consumer"
TASK_RESULT_TIMEOUT = timedelta(seconds=30)


@dataclass(frozen=True, slots=True)
class AlwaysReadyAvailabilityPort(AvailabilityPort):
    """No real Test Agent process exists before Phase 6; this always
    reports the configured deployment as fresh and ready so submission can
    still be exercised end-to-end in this slice."""

    ttl_seconds: float = 3600.0

    def observe(
        self, agent_id: AgentId, capability_name: str, capability_version: str
    ) -> AvailabilityObservation:
        # `observed_at` must never be later than the caller's own `now`, or
        # `is_fresh` fail-closes on the resulting negative age (ADR-0008
        # Section 5). Backdating by a second tolerates the small amount of
        # real wall-clock time that elapses between the request handler
        # capturing `now` and this observation being taken.
        return AvailabilityObservation(
            classification=AvailabilityClassification.READY,
            observed_at=datetime.now(UTC) - timedelta(seconds=1),
            ttl_seconds=self.ttl_seconds,
        )


@dataclass
class AppState:
    """One process-lifetime bundle of API-facing application services.

    Persistence references remain opaque because the component-test assembly
    uses in-memory adapters while the concrete runtime uses PostgreSQL.
    """

    orchestrator_persistence: object
    agent_persistence: object | None
    workflow_access_query: AuthorizedWorkflowQueryPort
    security_policy: LocalDevelopmentAuthorizationPolicy
    submission_orchestrator: SubmissionOrchestrator
    terminal_event_processor: TerminalEventProcessor
    readiness: CoreReadinessPort
    registry_loaded: bool
    task_result_timeout: timedelta


def default_test_agent_binding() -> CapabilityBinding:
    """The one trusted text.word-count Test Agent declaration used by
    default. Exposed so tests can build an alternate Registry snapshot
    (e.g. an empty one, to exercise the no-eligible-Agent path) without
    reaching into SubmissionOrchestrator's private state."""
    return CapabilityBinding(
        capability_name="text.word-count",
        capability_version="1.0",
        command_contract_name="ExecuteTask",
        command_contract_versions=("1.0",),
        event_contract_names=("TaskCompleted", "TaskFailed"),
        event_contract_versions=("1.0", "1.0"),
        agent_id=AgentId("018f23a7-6b4d-7c91-8a2e-123456789abc"),
        implementation_identity="test-agent-impl",
        implementation_version="1.0",
        deployment_declaration_digest="sha256:local-development-fixed-digest",
        environment="development",
        enabled=True,
        readiness_url="http://127.0.0.1:8100/health/ready",
    )


def build_app_state(*, bindings: list[CapabilityBinding] | None = None) -> AppState:
    """Assemble one process-lifetime AppState.

    `bindings` defaults to one trusted text.word-count Test Agent
    declaration, always reported ready. Pass an empty list to exercise the
    no-eligible-Agent path without touching any private internals.
    """
    if bindings is None:
        bindings = [default_test_agent_binding()]
    snapshot = load_registry_snapshot(bindings, revision="local-development-rev-1")
    candidate_selector = RegistryCandidateSelector(
        snapshot=snapshot,
        availability_port=AlwaysReadyAvailabilityPort(),
        selection_policy_version="1.0",
    )

    orchestrator_persistence = InMemoryOrchestratorPersistence()
    agent_persistence = InMemoryAgentPersistence()

    submission_orchestrator = SubmissionOrchestrator(
        accepted_request_query=orchestrator_persistence,
        request_access_audit=orchestrator_persistence,
        workflow_query=orchestrator_persistence,
        submission_transaction=orchestrator_persistence,
        candidate_selector=candidate_selector,
        id_factory=Uuid7IdentifierFactory(),
        orchestrator_component="orchestrator",
        orchestrator_instance_id="018f23a7-6b4d-7c91-8a2e-123456789abd",
    )
    terminal_event_processor = TerminalEventProcessor(
        transaction=orchestrator_persistence,
    )

    return AppState(
        orchestrator_persistence=orchestrator_persistence,
        agent_persistence=agent_persistence,
        workflow_access_query=orchestrator_persistence,
        security_policy=LocalDevelopmentAuthorizationPolicy(),
        submission_orchestrator=submission_orchestrator,
        terminal_event_processor=terminal_event_processor,
        readiness=StaticReadiness(),
        registry_loaded=True,
        task_result_timeout=TASK_RESULT_TIMEOUT,
    )
