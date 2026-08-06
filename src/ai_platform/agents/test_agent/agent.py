"""The Test Agent execution lifecycle (vertical-slice-01.md Section 14,
ADR-0007 Section 4).

Ordering matches Section 14 exactly: resolve any completed receipt first
(so a redelivered duplicate never gets a different outcome), only then
check whether the deadline has already elapsed, and only if still live
execute the deterministic capability. Concurrent duplicates at commit time
resolve to one durable outcome through the Agent outcome transaction
(ADR-0006: "one logical effect, not exactly-once computation").
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ai_platform.agents.domain.outcomes import AgentCompletedReceipt, AgentEventOutboxRecord
from ai_platform.agents.test_agent.capability import (
    CAPABILITY_NAME,
    CAPABILITY_VERSION,
    compute_word_count,
)
from ai_platform.agents.test_agent.errors import (
    CapabilityMismatchError,
    CommandIdentityConflictError,
    CommandIntegrityError,
    MissingOutcomeInvariantError,
)
from ai_platform.agents.test_agent.execution_context import ExecuteTaskContext
from ai_platform.agents.test_agent.ids import IdentifierFactory
from ai_platform.agents.test_agent.messages import (
    build_task_completed_payload,
    build_task_failed_payload,
)
from ai_platform.orchestrator.domain.audit import AuditRecord
from ai_platform.ports.persistence.transactions import (
    AgentOutcomeCommitIntent,
    AgentOutcomeTransactionPort,
    CompletedAgentWork,
)
from ai_platform.shared.identifiers import ActorId, AgentId, MessageId
from ai_platform.shared.messages import canonical_message_bytes
from ai_platform.shared.outcomes import AgentOutcome

_DEADLINE_FAILURE_CODE = "TASK_RESULT_DEADLINE_EXCEEDED"


class TestAgentDisposition(Enum):
    __test__ = False  # not a pytest test class despite the name prefix

    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DUPLICATE_RESOLVED = "DUPLICATE_RESOLVED"
    DEADLINE_EXPIRED_BEFORE_EXECUTION = "DEADLINE_EXPIRED_BEFORE_EXECUTION"


@dataclass(frozen=True, slots=True)
class TestAgentResult:
    __test__ = False  # not a pytest test class despite the name prefix

    disposition: TestAgentDisposition
    outcome: AgentOutcome
    """Always present: every code path either computes a fresh outcome or
    raises MissingOutcomeInvariantError rather than returning without one."""


class TestAgent:
    __test__ = False  # not a pytest test class despite the name prefix

    def __init__(
        self,
        *,
        environment: str,
        agent_deployment_id: AgentId,
        agent_component: str,
        outcome_transaction: AgentOutcomeTransactionPort,
        id_factory: IdentifierFactory,
    ) -> None:
        self._environment = environment
        self._agent_deployment_id = agent_deployment_id
        self._agent_component = agent_component
        self._outcome_transaction = outcome_transaction
        self._id_factory = id_factory

    async def handle(self, context: ExecuteTaskContext, *, now: datetime) -> TestAgentResult:
        if (
            context.capability_name != CAPABILITY_NAME
            or context.capability_version != CAPABILITY_VERSION
        ):
            raise CapabilityMismatchError(context.capability_name, context.capability_version)

        existing = await self._outcome_transaction.get_completed(context.task_attempt_id)
        if existing is not None:
            return self._resolve_duplicate(context, existing)

        if context.task_result_deadline <= now:
            outcome = AgentOutcome(
                task_attempt_id=context.task_attempt_id,
                completed_at=now,
                failure_code=_DEADLINE_FAILURE_CODE,
                summary="Task result deadline elapsed before execution.",
            )
            disposition = TestAgentDisposition.DEADLINE_EXPIRED_BEFORE_EXECUTION
        else:
            word_count = compute_word_count(context.input_text)
            outcome = AgentOutcome(
                task_attempt_id=context.task_attempt_id,
                completed_at=now,
                result_data={"word_count": word_count},
            )
            disposition = TestAgentDisposition.COMPLETED

        completed_work = self._build_completed_work(context, outcome, now=now)
        committed = await self._outcome_transaction.commit_outcome(
            AgentOutcomeCommitIntent(
                completed_work=completed_work,
                audit=AuditRecord(
                    kind="agent_outcome_committed",
                    workflow_id=context.workflow_id,
                    occurred_at=now,
                    actor_id=ActorId(f"agent:{self._agent_deployment_id}"),
                    details={
                        "task_attempt_id": str(context.task_attempt_id),
                        "terminal_event_message_id": str(completed_work.event_outbox.message_id),
                    },
                ),
            )
        )
        if not committed.created:
            return self._resolve_duplicate(context, committed.completed_work)
        return TestAgentResult(disposition=disposition, outcome=committed.completed_work.outcome)

    def _build_completed_work(
        self, context: ExecuteTaskContext, outcome: AgentOutcome, *, now: datetime
    ) -> CompletedAgentWork:
        message_id = MessageId(self._id_factory.new_id())
        event_outbox = self._build_terminal_event(context, outcome, message_id=message_id, now=now)
        receipt = AgentCompletedReceipt(
            environment=self._environment,
            agent_deployment_id=self._agent_deployment_id,
            task_attempt_id=context.task_attempt_id,
            command_message_id=context.command_message_id,
            command_digest=context.command_digest,
            terminal_event_message_id=message_id,
            completed_at=outcome.completed_at,
        )
        return CompletedAgentWork(receipt=receipt, outcome=outcome, event_outbox=event_outbox)

    def _resolve_duplicate(
        self, context: ExecuteTaskContext, completed_work: CompletedAgentWork
    ) -> TestAgentResult:
        existing_receipt = completed_work.receipt
        if existing_receipt.command_message_id != context.command_message_id:
            raise CommandIdentityConflictError(
                context.task_attempt_id, existing_receipt.command_message_id
            )
        if existing_receipt.command_digest != context.command_digest:
            raise CommandIntegrityError(context.command_message_id)

        if completed_work.outcome.task_attempt_id != context.task_attempt_id:
            raise MissingOutcomeInvariantError(context.task_attempt_id)
        return TestAgentResult(
            disposition=TestAgentDisposition.DUPLICATE_RESOLVED,
            outcome=completed_work.outcome,
        )

    def _build_terminal_event(
        self,
        context: ExecuteTaskContext,
        outcome: AgentOutcome,
        *,
        message_id: MessageId,
        now: datetime,
    ) -> AgentEventOutboxRecord:
        if outcome.result_data is not None:
            payload = build_task_completed_payload(
                message_id=message_id,
                correlation_id=context.correlation_id,
                causation_id=context.command_message_id,
                workflow_id=context.workflow_id,
                task_id=context.task_id,
                task_attempt_id=context.task_attempt_id,
                agent_component=self._agent_component,
                agent_instance_id=self._agent_deployment_id,
                text=context.input_text,
                result_data=outcome.result_data,
                capability_name=CAPABILITY_NAME,
                capability_version=CAPABILITY_VERSION,
                completed_at=outcome.completed_at,
                created_at=now,
            )
        else:
            assert outcome.failure_code is not None
            payload = build_task_failed_payload(
                message_id=message_id,
                correlation_id=context.correlation_id,
                causation_id=context.command_message_id,
                workflow_id=context.workflow_id,
                task_id=context.task_id,
                task_attempt_id=context.task_attempt_id,
                agent_component=self._agent_component,
                agent_instance_id=self._agent_deployment_id,
                failure_code=outcome.failure_code,
                summary=outcome.summary or "",
                capability_name=CAPABILITY_NAME,
                capability_version=CAPABILITY_VERSION,
                failed_at=outcome.completed_at,
                created_at=now,
            )

        return AgentEventOutboxRecord(
            message_id=message_id,
            workflow_id=context.workflow_id,
            logical_channel="task-outcomes",
            ordering_key=str(context.workflow_id),
            payload_bytes=canonical_message_bytes(payload),
            headers=(),
            creation_sequence=1,
            created_at=now,
        )
