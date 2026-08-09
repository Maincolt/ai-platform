"""The Review Agent execution lifecycle (ADR-0018, mirroring
`ai_platform.agents.summarize_agent.agent`).

Ordering, the durable pre-call claim, and the ADR-0016 unknown-outcome
handling are identical to `SummarizeAgent` -- see that module's docstring
for the full rationale, which applies unchanged here. The one addition:
`code.review`'s `result_data` is a structured findings list (ADR-0018
Decision 3), not a passthrough string, so a successful provider call is
not automatically a successful completion -- the raw response text must
still parse into a valid findings list. A provider call that succeeds but
returns unparseable output is treated as a failed completion
(`MALFORMED_REVIEW_OUTPUT`), the same way a classified AI Router failure
is: usage is still recorded (a real, billed call happened), but no
`TaskCompleted` is produced. The raw unparseable text is never persisted
into the outcome's `summary` -- only a fixed, generic description -- so a
provider's imperfect output cannot leak arbitrary content past the
platform's existing redaction boundary.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import cast

from ai_platform.agents.domain.outcomes import AgentCompletedReceipt, AgentEventOutboxRecord
from ai_platform.agents.review_agent.capability import CAPABILITY_NAME, CAPABILITY_VERSION
from ai_platform.agents.review_agent.errors import (
    CapabilityMismatchError,
    CommandIdentityConflictError,
    CommandIntegrityError,
    MissingOutcomeInvariantError,
    ProviderCallReconciliationPendingError,
)
from ai_platform.agents.review_agent.ids import IdentifierFactory
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
_MALFORMED_OUTPUT_FAILURE_CODE = "MALFORMED_REVIEW_OUTPUT"
_VALID_SEVERITIES = frozenset({"low", "medium", "high"})
_MAX_FINDING_SUMMARY_LENGTH = 2000
_MAX_FINDINGS = 100
_REQUIRED_FINDING_KEYS = frozenset({"file", "line", "summary", "severity"})


class ReviewAgentDisposition(Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DUPLICATE_RESOLVED = "DUPLICATE_RESOLVED"
    DEADLINE_EXPIRED_BEFORE_EXECUTION = "DEADLINE_EXPIRED_BEFORE_EXECUTION"


@dataclass(frozen=True, slots=True)
class ReviewAgentResult:
    disposition: ReviewAgentDisposition
    outcome: AgentOutcome
    """Always present: every code path either computes a fresh outcome or
    raises MissingOutcomeInvariantError rather than returning without one."""


def _build_review_prompt(diff: str) -> str:
    return (
        "You are a meticulous code reviewer. Review the following diff and "
        "respond with ONLY a JSON array (no prose, no markdown fences) of "
        "finding objects. Each object must have exactly these keys: "
        '"file" (string, the affected file path), "line" (integer or null, '
        'the affected line number if known), "summary" (string, one '
        'sentence describing the issue), and "severity" (one of "low", '
        '"medium", "high"). Return an empty array [] if there are no '
        f"findings.\n\nDiff:\n{diff}"
    )


def _parse_findings(output_text: str) -> list[dict[str, object]] | None:
    """Parse and validate the provider's raw response into a findings list.

    Returns `None` on any shape/content mismatch -- the caller treats that
    as a failed completion (`MALFORMED_REVIEW_OUTPUT`), never as a partial
    or best-effort result.
    """
    try:
        parsed: object = json.loads(output_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list):
        return None
    candidates = cast(list[object], parsed)
    if len(candidates) > _MAX_FINDINGS:
        return None

    findings: list[dict[str, object]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            return None
        item = cast(dict[str, object], candidate)
        if frozenset(item.keys()) != _REQUIRED_FINDING_KEYS:
            return None
        file_value = item["file"]
        line_value = item["line"]
        summary_value = item["summary"]
        severity_value = item["severity"]
        if not isinstance(file_value, str) or not file_value:
            return None
        if line_value is not None and (
            isinstance(line_value, bool) or not isinstance(line_value, int) or line_value < 0
        ):
            return None
        if (
            not isinstance(summary_value, str)
            or not summary_value
            or len(summary_value) > _MAX_FINDING_SUMMARY_LENGTH
        ):
            return None
        if severity_value not in _VALID_SEVERITIES:
            return None
        findings.append(
            {
                "file": file_value,
                "line": line_value,
                "summary": summary_value,
                "severity": severity_value,
            }
        )
    return findings


class ReviewAgent:
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

    async def handle(self, context: ExecuteTaskContext, *, now: datetime) -> ReviewAgentResult:
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
            disposition = ReviewAgentDisposition.DEADLINE_EXPIRED_BEFORE_EXECUTION
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
                        prompt=_build_review_prompt(context.input_text),
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
                    findings = _parse_findings(completion.output_text)
                    if findings is not None:
                        outcome = AgentOutcome(
                            task_attempt_id=context.task_attempt_id,
                            completed_at=now,
                            result_data={"findings": findings},
                        )
                        disposition = ReviewAgentDisposition.COMPLETED
                    else:
                        outcome = AgentOutcome(
                            task_attempt_id=context.task_attempt_id,
                            completed_at=now,
                            failure_code=_MALFORMED_OUTPUT_FAILURE_CODE,
                            summary=(
                                "The AI Router's response did not parse into a valid findings list."
                            ),
                        )
                        disposition = ReviewAgentDisposition.FAILED
                else:
                    assert completion.failure_code is not None
                    outcome = AgentOutcome(
                        task_attempt_id=context.task_attempt_id,
                        completed_at=now,
                        failure_code=completion.failure_code.value,
                        summary="The AI Router returned a classified failure.",
                    )
                    disposition = ReviewAgentDisposition.FAILED

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
        return ReviewAgentResult(disposition=disposition, outcome=committed.completed_work.outcome)

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
    ) -> ReviewAgentResult:
        existing_receipt = completed_work.receipt
        if existing_receipt.command_message_id != context.command_message_id:
            raise CommandIdentityConflictError(
                context.task_attempt_id, existing_receipt.command_message_id
            )
        if existing_receipt.command_digest != context.command_digest:
            raise CommandIntegrityError(context.command_message_id)

        if completed_work.outcome.task_attempt_id != context.task_attempt_id:
            raise MissingOutcomeInvariantError(context.task_attempt_id)
        return ReviewAgentResult(
            disposition=ReviewAgentDisposition.DUPLICATE_RESOLVED,
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
