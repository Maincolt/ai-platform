"""The Test Agent execution lifecycle (vertical-slice-01.md Section 14,
ADR-0007 Section 4).

Ordering matches Section 14 exactly: resolve any completed receipt first
(so a redelivered duplicate never gets a different outcome), only then
check whether the deadline has already elapsed, and only if still live
execute the deterministic capability. Concurrent duplicates at commit time
resolve to one durable outcome via the receipt repository's
create_or_resolve (ADR-0006: "one logical effect, not exactly-once
computation").
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
)
from ai_platform.agents.test_agent.execution_context import ExecuteTaskContext
from ai_platform.agents.test_agent.ids import IdentifierFactory
from ai_platform.agents.test_agent.messages import (
    build_task_completed_payload,
    build_task_failed_payload,
)
from ai_platform.ports.persistence.agent import (
    AgentOutcomeRepositoryPort,
    AgentReceiptRepositoryPort,
)
from ai_platform.ports.persistence.outbox import AgentEventOutboxRepositoryPort
from ai_platform.shared.identifiers import AgentId, MessageId
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
    outcome: AgentOutcome | None


class TestAgent:
    __test__ = False  # not a pytest test class despite the name prefix

    def __init__(
        self,
        *,
        environment: str,
        agent_deployment_id: AgentId,
        agent_component: str,
        receipt_repo: AgentReceiptRepositoryPort,
        outcome_repo: AgentOutcomeRepositoryPort,
        event_outbox_repo: AgentEventOutboxRepositoryPort,
        id_factory: IdentifierFactory,
    ) -> None:
        self._environment = environment
        self._agent_deployment_id = agent_deployment_id
        self._agent_component = agent_component
        self._receipt_repo = receipt_repo
        self._outcome_repo = outcome_repo
        self._event_outbox_repo = event_outbox_repo
        self._id_factory = id_factory

    def handle(self, context: ExecuteTaskContext, *, now: datetime) -> TestAgentResult:
        if (
            context.capability_name != CAPABILITY_NAME
            or context.capability_version != CAPABILITY_VERSION
        ):
            raise CapabilityMismatchError(context.capability_name, context.capability_version)

        existing_receipt = self._receipt_repo.get_by_attempt(context.task_attempt_id)
        if existing_receipt is not None:
            return self._resolve_duplicate(context, existing_receipt)

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
                task_attempt_id=context.task_attempt_id, completed_at=now, word_count=word_count
            )
            disposition = TestAgentDisposition.COMPLETED

        receipt = AgentCompletedReceipt(
            environment=self._environment,
            agent_deployment_id=self._agent_deployment_id,
            task_attempt_id=context.task_attempt_id,
            command_message_id=context.command_message_id,
            command_digest=context.command_digest,
        )
        resolved_receipt, is_new = self._receipt_repo.create_or_resolve(receipt)
        if not is_new:
            # Lost a concurrent race to commit first; reuse the winner's outcome.
            return self._resolve_duplicate(context, resolved_receipt)

        self._outcome_repo.save(outcome)
        self._enqueue_terminal_event(context, outcome, now=now)
        return TestAgentResult(disposition=disposition, outcome=outcome)

    def _resolve_duplicate(
        self, context: ExecuteTaskContext, existing_receipt: AgentCompletedReceipt
    ) -> TestAgentResult:
        if existing_receipt.command_message_id != context.command_message_id:
            raise CommandIdentityConflictError(
                context.task_attempt_id, existing_receipt.command_message_id
            )
        if existing_receipt.command_digest != context.command_digest:
            raise CommandIntegrityError(context.command_message_id)

        existing_outcome = self._outcome_repo.get_by_attempt(context.task_attempt_id)
        return TestAgentResult(
            disposition=TestAgentDisposition.DUPLICATE_RESOLVED, outcome=existing_outcome
        )

    def _enqueue_terminal_event(
        self, context: ExecuteTaskContext, outcome: AgentOutcome, *, now: datetime
    ) -> None:
        message_id = MessageId(self._id_factory.new_id())
        if outcome.word_count is not None:
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
                word_count=outcome.word_count,
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

        self._event_outbox_repo.enqueue(
            AgentEventOutboxRecord(
                message_id=message_id,
                workflow_id=context.workflow_id,
                payload=payload,
                created_at=now,
            )
        )
