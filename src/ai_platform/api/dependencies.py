"""Application assembly: wires the in-memory reference ports (Sprint 5) and
Sprint 3's application services into one process-lifetime `AppState`.

This is explicitly a non-production wiring used to make the Workflow API
runnable and testable before Phase 6 introduces real PostgreSQL/Kafka
adapters. There is no Event Bus consumer here: after submission, a
workflow remains `DISPATCHED` until something (a future Phase 6 consumer,
or a test driving `TerminalEventProcessor` directly, as Sprint 3's
integration tests already do) applies the terminal outcome. That is an
honest reflection of this slice's scope, not a bug.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ai_platform.api.context import LocalDevelopmentAuthorizationPolicy
from ai_platform.api.ids import Uuid7IdentifierFactory
from ai_platform.api.inmemory_ports import (
    InMemoryAcceptedRequestRepository,
    InMemoryAgentEventOutboxRepository,
    InMemoryAgentOutcomeRepository,
    InMemoryAgentReceiptRepository,
    InMemoryAuditRepository,
    InMemoryOrchestratorInboxRepository,
    InMemoryOrchestratorOutboxRepository,
    InMemoryTaskAttemptRepository,
    InMemoryTaskRepository,
    InMemoryWorkflowRepository,
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
        return AvailabilityObservation(
            classification=AvailabilityClassification.READY,
            observed_at=datetime.now(UTC),
            ttl_seconds=self.ttl_seconds,
        )


@dataclass
class AppState:
    """One process-lifetime bundle of in-memory ports and the application
    services composed over them."""

    accepted_request_repo: InMemoryAcceptedRequestRepository
    workflow_repo: InMemoryWorkflowRepository
    task_repo: InMemoryTaskRepository
    task_attempt_repo: InMemoryTaskAttemptRepository
    orchestrator_outbox_repo: InMemoryOrchestratorOutboxRepository
    audit_repo: InMemoryAuditRepository
    orchestrator_inbox_repo: InMemoryOrchestratorInboxRepository
    agent_receipt_repo: InMemoryAgentReceiptRepository
    agent_outcome_repo: InMemoryAgentOutcomeRepository
    agent_event_outbox_repo: InMemoryAgentEventOutboxRepository
    security_policy: LocalDevelopmentAuthorizationPolicy
    submission_orchestrator: SubmissionOrchestrator
    terminal_event_processor: TerminalEventProcessor
    registry_loaded: bool


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
        agent_id=AgentId("test-agent"),
        implementation_identity="test-agent-impl",
        implementation_version="1.0",
        deployment_declaration_digest="sha256:local-development-fixed-digest",
        environment="local-development",
        enabled=True,
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

    accepted_request_repo = InMemoryAcceptedRequestRepository()
    workflow_repo = InMemoryWorkflowRepository()
    task_repo = InMemoryTaskRepository()
    task_attempt_repo = InMemoryTaskAttemptRepository()
    orchestrator_outbox_repo = InMemoryOrchestratorOutboxRepository()
    audit_repo = InMemoryAuditRepository()
    orchestrator_inbox_repo = InMemoryOrchestratorInboxRepository()
    agent_receipt_repo = InMemoryAgentReceiptRepository()
    agent_outcome_repo = InMemoryAgentOutcomeRepository()
    agent_event_outbox_repo = InMemoryAgentEventOutboxRepository()

    submission_orchestrator = SubmissionOrchestrator(
        accepted_request_repo=accepted_request_repo,
        workflow_repo=workflow_repo,
        task_repo=task_repo,
        task_attempt_repo=task_attempt_repo,
        outbox_repo=orchestrator_outbox_repo,
        audit_repo=audit_repo,
        candidate_selector=candidate_selector,
        id_factory=Uuid7IdentifierFactory(),
        orchestrator_component="orchestrator",
        orchestrator_instance_id="local-development-orchestrator",
    )
    terminal_event_processor = TerminalEventProcessor(
        workflow_repo=workflow_repo,
        inbox_repo=orchestrator_inbox_repo,
        audit_repo=audit_repo,
    )

    return AppState(
        accepted_request_repo=accepted_request_repo,
        workflow_repo=workflow_repo,
        task_repo=task_repo,
        task_attempt_repo=task_attempt_repo,
        orchestrator_outbox_repo=orchestrator_outbox_repo,
        audit_repo=audit_repo,
        orchestrator_inbox_repo=orchestrator_inbox_repo,
        agent_receipt_repo=agent_receipt_repo,
        agent_outcome_repo=agent_outcome_repo,
        agent_event_outbox_repo=agent_event_outbox_repo,
        security_policy=LocalDevelopmentAuthorizationPolicy(),
        submission_orchestrator=submission_orchestrator,
        terminal_event_processor=terminal_event_processor,
        registry_loaded=True,
    )
