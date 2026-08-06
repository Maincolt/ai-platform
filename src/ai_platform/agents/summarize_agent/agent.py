"""The Summarize Agent execution lifecycle (ADR-0014 Section 5, ADR-0016,
mirroring `ai_platform.agents.test_agent.agent`'s ordering).

Ordering matches TestAgent's skeleton: resolve any completed receipt first
(so a redelivered duplicate never gets a different outcome), only then
check whether the deadline has already elapsed, and only if still live
proceed to execution. The middle differs completely from TestAgent's
deterministic recompute-on-redelivery model, because a provider call is a
real external side effect (ADR-0007 Section 19-20):

1. Before calling the AI Router, durably claim the `task_attempt_id`
   (`AgentOutcomeTransactionPort.claim_provider_call`) so a crash between
   claiming and receiving a provider response is detectable on redelivery.
2. A redelivery that finds its own matching claim with no resolved outcome
   is the ADR-0014 Section 5 "unknown outcome" case -- a possibly-already
   -billed, possibly-already-generated completion whose actual result was
   never durably recorded. Per ADR-0016 (resolving ADR-0014 Section 8 Q1),
   this is deliberately NOT resolved to a synthetic outcome here: the
   original attempt may still be genuinely in flight, and committing a
   synthetic outcome now could race a late-arriving real completion and
   silently discard it. Instead, `handle()` raises
   `ProviderCallReconciliationPendingError`, which propagates uncaught to
   the runtime's `EventConsumerWorker`. That worker's existing
   retry-then-quarantine path provides the operator-review signal, and the
   Orchestrator's existing `DeadlineReconciler` provides the bounded
   reconciliation window (the attempt's own `task_result_deadline`) --
   both already-Accepted mechanisms, reused rather than duplicated.
3. A claim with mismatched command identity/digest is real corruption,
   handled exactly like TestAgent's duplicate-resolution conflicts.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from ai_platform.agents.domain.outcomes import AgentCompletedReceipt, AgentEventOutboxRecord
from ai_platform.agents.summarize_agent.capability import CAPABILITY_NAME, CAPABILITY_VERSION
from ai_platform.agents.summarize_agent.errors import (
    CapabilityMismatchError,
    CommandIdentityConflictError,
    CommandIntegrityError,
    MissingOutcomeInvariantError,
    ProviderCallReconciliationPendingError,
)
from ai_platform.agents.summarize_agent.ids import IdentifierFactory
from ai_platform.agents.test_agent.execution_context import ExecuteTaskContext
from ai_platform.agents.test_agent.messages import (
    build_task_completed_payload,
    build_task_failed_payload,
)
from ai_platform.orchestrator.domain.audit import AuditRecord
from ai_platform.ports.ai_router import (
    AICompletionRequest,
    AIRouterPort,
    DataClassification,
)
from ai_platform.ports.persistence.transactions import (
    AgentOutcomeCommitIntent,
    AgentOutcomeTransactionPort,
    CompletedAgentWork,
    ProviderCallClaimIntent,
    ProviderCallUsageRecord,
)
from ai_platform.shared.identifiers import ActorId, AgentId, MessageId
from ai_platform.shared.messages import canonical_message_bytes
from ai_platform.shared.outcomes import AgentOutcome

_DEADLINE_FAILURE_CODE = "TASK_RESULT_DEADLINE_EXCEEDED"


class SummarizeAgentDisposition(Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DUPLICATE_RESOLVED = "DUPLICATE_RESOLVED"
    DEADLINE_EXPIRED_BEFORE_EXECUTION = "DEADLINE_EXPIRED_BEFORE_EXECUTION"


@dataclass(frozen=True, slots=True)
class SummarizeAgentResult:
    disposition: SummarizeAgentDisposition
    outcome: AgentOutcome
    """Always present: every code path either computes a fresh outcome or
    raises MissingOutcomeInvariantError rather than returning without one."""


def _build_summarize_prompt(text: str) -> str:
    return f"Summarize the following text in at most a few sentences:\n\n{text}"


class SummarizeAgent:
    def __init__(
        self,
        *,
        environment: str,
        agent_deployment_id: AgentId,
        agent_component: str,
        outcome_transaction: AgentOutcomeTransactionPort,
        id_factory: IdentifierFactory,
        ai_router: AIRouterPort,
        max_output_tokens: int,
    ) -> None:
        if max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        self._environment = environment
        self._agent_deployment_id = agent_deployment_id
        self._agent_component = agent_component
        self._outcome_transaction = outcome_transaction
        self._id_factory = id_factory
        self._ai_router = ai_router
        self._max_output_tokens = max_output_tokens

    async def handle(self, context: ExecuteTaskContext, *, now: datetime) -> SummarizeAgentResult:
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
            disposition = SummarizeAgentDisposition.DEADLINE_EXPIRED_BEFORE_EXECUTION
            usage: ProviderCallUsageRecord | None = None
        else:
            claim = await self._outcome_transaction.claim_provider_call(
                ProviderCallClaimIntent(
                    task_attempt_id=context.task_attempt_id,
                    command_message_id=context.command_message_id,
                    command_digest=context.command_digest,
                    claimed_at=now,
                )
            )
            if not claim.created:
                assert claim.existing is not None
                if claim.existing.command_message_id != context.command_message_id:
                    raise CommandIdentityConflictError(
                        context.task_attempt_id, claim.existing.command_message_id
                    )
                if claim.existing.command_digest != context.command_digest:
                    raise CommandIntegrityError(context.command_message_id)

                # ADR-0016: a redelivery found our own unresolved claim -- a
                # crash between claiming and receiving a provider response,
                # or the original attempt still genuinely in flight. Do not
                # resolve synthetically; raise and let the runtime's
                # existing retry-then-quarantine and deadline-expiry
                # mechanisms handle it (see module docstring).
                raise ProviderCallReconciliationPendingError(context.task_attempt_id)
            else:
                completion = await self._ai_router.complete(
                    AICompletionRequest(
                        prompt=_build_summarize_prompt(context.input_text),
                        max_output_tokens=self._max_output_tokens,
                        idempotency_key=str(context.task_attempt_id),
                        deadline=context.task_result_deadline,
                        classification=DataClassification.NO_SPECIAL_HANDLING,
                    )
                )
                usage = (
                    ProviderCallUsageRecord(
                        provider=completion.usage.provider,
                        model=completion.usage.model,
                        input_tokens=completion.usage.input_tokens,
                        output_tokens=completion.usage.output_tokens,
                        latency_seconds=completion.usage.latency_seconds,
                    )
                    if completion.usage is not None
                    else None
                )
                if completion.output_text is not None:
                    outcome = AgentOutcome(
                        task_attempt_id=context.task_attempt_id,
                        completed_at=now,
                        result_data={"summary": completion.output_text},
                    )
                    disposition = SummarizeAgentDisposition.COMPLETED
                else:
                    assert completion.failure_code is not None
                    outcome = AgentOutcome(
                        task_attempt_id=context.task_attempt_id,
                        completed_at=now,
                        failure_code=completion.failure_code.value,
                        summary="The AI Router returned a classified failure.",
                    )
                    disposition = SummarizeAgentDisposition.FAILED

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
                usage=usage,
            )
        )
        if not committed.created:
            return self._resolve_duplicate(context, committed.completed_work)
        return SummarizeAgentResult(
            disposition=disposition, outcome=committed.completed_work.outcome
        )

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
    ) -> SummarizeAgentResult:
        existing_receipt = completed_work.receipt
        if existing_receipt.command_message_id != context.command_message_id:
            raise CommandIdentityConflictError(
                context.task_attempt_id, existing_receipt.command_message_id
            )
        if existing_receipt.command_digest != context.command_digest:
            raise CommandIntegrityError(context.command_message_id)

        if completed_work.outcome.task_attempt_id != context.task_attempt_id:
            raise MissingOutcomeInvariantError(context.task_attempt_id)
        return SummarizeAgentResult(
            disposition=SummarizeAgentDisposition.DUPLICATE_RESOLVED,
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
