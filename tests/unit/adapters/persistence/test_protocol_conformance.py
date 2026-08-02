"""Static structural checks for concrete persistence adapters."""

from ai_platform.adapters.persistence.agent import PsycopgAgentPersistence
from ai_platform.adapters.persistence.orchestrator import PsycopgOrchestratorPersistence
from ai_platform.adapters.persistence.outbox import PsycopgOutboxTransaction
from ai_platform.adapters.persistence.recovery import PsycopgTransportRejectionTransaction
from ai_platform.ports.persistence.outbox import OutboxTransactionPort
from ai_platform.ports.persistence.recovery import TransportRejectionTransactionPort
from ai_platform.ports.persistence.transactions import (
    AcceptedRequestAccessAuditPort,
    AcceptedRequestQueryPort,
    AgentOutcomeTransactionPort,
    AuthorizedWorkflowQueryPort,
    DeadlineTransactionPort,
    SubmissionTransactionPort,
    TerminalOutcomeTransactionPort,
    WorkflowQueryPort,
)


def _type_check_only(
    orchestrator: PsycopgOrchestratorPersistence,
    agent: PsycopgAgentPersistence,
    outbox: PsycopgOutboxTransaction,
    rejection: PsycopgTransportRejectionTransaction,
) -> None:
    accepted_query: AcceptedRequestQueryPort = orchestrator
    request_access_audit: AcceptedRequestAccessAuditPort = orchestrator
    workflow_query: WorkflowQueryPort = orchestrator
    authorized_query: AuthorizedWorkflowQueryPort = orchestrator
    submission: SubmissionTransactionPort = orchestrator
    terminal: TerminalOutcomeTransactionPort = orchestrator
    deadline: DeadlineTransactionPort = orchestrator
    agent_outcome: AgentOutcomeTransactionPort = agent
    outbox_port: OutboxTransactionPort = outbox
    rejection_port: TransportRejectionTransactionPort = rejection
    assert all(
        value is not None
        for value in (
            accepted_query,
            request_access_audit,
            workflow_query,
            authorized_query,
            submission,
            terminal,
            deadline,
            agent_outcome,
            outbox_port,
            rejection_port,
        )
    )


def test_protocol_conformance_is_checked_by_static_analysis() -> None:
    assert callable(_type_check_only)
