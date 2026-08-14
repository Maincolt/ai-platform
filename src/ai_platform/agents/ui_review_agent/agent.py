"""The UI Review Agent execution lifecycle (ADR-0019, mirroring
`ai_platform.agents.review_agent.agent`).

Ordering, the durable pre-call claim, and the ADR-0016 unknown-outcome
handling are identical to `ReviewAgent` -- see that module's docstring for
the full rationale, which applies unchanged here. Two additions, both
happening *before* any provider-call claim is taken (a disallowed target or
a failed capture means no AI Router call happens at all, so nothing needs
reconciling if either occurs):

1. The command's input URL must exactly match the hardcoded allowed review
   target (ADR-0019 Decision 4) -- any mismatch fails closed with
   `DISALLOWED_REVIEW_TARGET`.
2. A deterministic, read-only Playwright capture (`capture.py`) must
   succeed before the single AI Router call is made -- a capture failure
   fails closed with `PAGE_CAPTURE_FAILED`.

From the claim onward, this mirrors `ReviewAgent` exactly: `code.review`'s
`_parse_findings` becomes `_parse_ui_findings` (same strict-parse
discipline: any shape/content mismatch returns `None`, treated as
`MALFORMED_UI_REVIEW_OUTPUT`, never a partial or best-effort result), and
the findings shape drops `file`/`line` in favor of a free-text `area`
locator, since a web page has no file/line concept.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import cast

from ai_platform.agents.domain.outcomes import AgentCompletedReceipt, AgentEventOutboxRecord
from ai_platform.agents.test_agent.execution_context import ExecuteTaskContext
from ai_platform.agents.test_agent.messages import (
    build_task_completed_payload,
    build_task_failed_payload,
)
from ai_platform.agents.ui_review_agent.capability import CAPABILITY_NAME, CAPABILITY_VERSION
from ai_platform.agents.ui_review_agent.capture import PageCapture, PageCapturePort
from ai_platform.agents.ui_review_agent.errors import (
    CapabilityMismatchError,
    CaptureFailedError,
    CommandIdentityConflictError,
    CommandIntegrityError,
    DisallowedReviewTargetError,
    MissingOutcomeInvariantError,
    ProviderCallReconciliationPendingError,
)
from ai_platform.agents.ui_review_agent.ids import IdentifierFactory
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
_DISALLOWED_TARGET_FAILURE_CODE = "DISALLOWED_REVIEW_TARGET"
_CAPTURE_FAILED_FAILURE_CODE = "PAGE_CAPTURE_FAILED"
_MALFORMED_OUTPUT_FAILURE_CODE = "MALFORMED_UI_REVIEW_OUTPUT"
_VALID_SEVERITIES = frozenset({"low", "medium", "high"})
_MAX_FINDING_SUMMARY_LENGTH = 2000
_MAX_FINDING_AREA_LENGTH = 200
_MAX_FINDINGS = 100
_REQUIRED_FINDING_KEYS = frozenset({"area", "summary", "severity"})


class UiReviewAgentDisposition(Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DUPLICATE_RESOLVED = "DUPLICATE_RESOLVED"
    DEADLINE_EXPIRED_BEFORE_EXECUTION = "DEADLINE_EXPIRED_BEFORE_EXECUTION"


@dataclass(frozen=True, slots=True)
class UiReviewAgentResult:
    disposition: UiReviewAgentDisposition
    outcome: AgentOutcome
    """Always present: every code path either computes a fresh outcome or
    raises MissingOutcomeInvariantError rather than returning without one."""


def _build_review_prompt(capture: PageCapture) -> str:
    console_lines = (
        "\n".join(f"- [{message.level}] {message.text}" for message in capture.console_messages)
        or "(none)"
    )
    return (
        "You are a meticulous UI/UX and accessibility reviewer. Review the "
        "following captured web page and respond with ONLY a JSON array "
        "(no prose, no markdown fences) of finding objects. Each object "
        'must have exactly these keys: "area" (string, a short label for '
        'what the finding is about, e.g. "header navigation", '
        '"console", "accessibility"), "summary" (string, one sentence '
        'describing the issue), and "severity" (one of "low", "medium", '
        '"high"). Return an empty array [] if there are no findings.\n\n'
        f"URL: {capture.url}\n"
        f"HTTP status: {capture.http_status}\n"
        f"Title: {capture.title}\n\n"
        f"Console messages:\n{console_lines}\n\n"
        f"Accessibility snapshot:\n{capture.accessibility_snapshot}\n\n"
        f"Visible text:\n{capture.visible_text}"
    )


def _strip_markdown_json_fence(text: str) -> str:
    """Strip one wrapping ```json ... ``` (or plain ``` ... ```) code fence.

    The prompt asks for ONLY a JSON array, but real providers sometimes
    wrap it in a markdown fence anyway (observed live against a real
    Anthropic model, not a hypothetical). This is a presentation-format
    tolerance, not a laxer parse: the unwrapped content still goes through
    the same strict `json.loads` and shape validation below, so malformed
    fencing or malformed inner content is still rejected, never silently
    repaired.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) < 2 or lines[-1].strip() != "```":
        return stripped
    return "\n".join(lines[1:-1]).strip()


def _parse_ui_findings(output_text: str) -> list[dict[str, object]] | None:
    """Parse and validate the provider's raw response into a findings list.

    Returns `None` on any shape/content mismatch -- the caller treats that
    as a failed completion (`MALFORMED_UI_REVIEW_OUTPUT`), never as a
    partial or best-effort result.
    """
    try:
        parsed: object = json.loads(_strip_markdown_json_fence(output_text))
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
        area_value = item["area"]
        summary_value = item["summary"]
        severity_value = item["severity"]
        if (
            not isinstance(area_value, str)
            or not area_value
            or len(area_value) > _MAX_FINDING_AREA_LENGTH
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
                "area": area_value,
                "summary": summary_value,
                "severity": severity_value,
            }
        )
    return findings


class UiReviewAgent:
    def __init__(
        self,
        *,
        environment: str,
        agent_deployment_id: AgentId,
        agent_component: str,
        outcome_transaction: AgentOutcomeTransactionPort,
        id_factory: IdentifierFactory,
        ai_router: AIRouterPort,
        page_capture: PageCapturePort,
        allowed_review_target: str,
        max_output_tokens: int,
    ) -> None:
        if max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        if not allowed_review_target:
            raise ValueError("allowed_review_target must be non-empty")
        self._environment = environment
        self._agent_deployment_id = agent_deployment_id
        self._agent_component = agent_component
        self._outcome_transaction = outcome_transaction
        self._id_factory = id_factory
        self._ai_router = ai_router
        self._page_capture = page_capture
        self._allowed_review_target = allowed_review_target
        self._max_output_tokens = max_output_tokens

    async def handle(self, context: ExecuteTaskContext, *, now: datetime) -> UiReviewAgentResult:
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
            return await self._commit(
                context,
                outcome,
                disposition=UiReviewAgentDisposition.DEADLINE_EXPIRED_BEFORE_EXECUTION,
                usage=None,
                now=now,
            )

        if context.input_text != self._allowed_review_target:
            error = DisallowedReviewTargetError(context.input_text)
            outcome = AgentOutcome(
                task_attempt_id=context.task_attempt_id,
                completed_at=now,
                failure_code=_DISALLOWED_TARGET_FAILURE_CODE,
                summary=str(error),
            )
            return await self._commit(
                context,
                outcome,
                disposition=UiReviewAgentDisposition.FAILED,
                usage=None,
                now=now,
            )

        try:
            capture = await self._page_capture.capture(context.input_text)
        except CaptureFailedError as error:
            outcome = AgentOutcome(
                task_attempt_id=context.task_attempt_id,
                completed_at=now,
                failure_code=_CAPTURE_FAILED_FAILURE_CODE,
                summary=f"Page capture failed: {error.reason}",
            )
            return await self._commit(
                context,
                outcome,
                disposition=UiReviewAgentDisposition.FAILED,
                usage=None,
                now=now,
            )

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
            # resolve synthetically; raise and let the runtime's existing
            # retry-then-quarantine and deadline-expiry mechanisms handle
            # it (see module docstring).
            raise ProviderCallReconciliationPendingError(context.task_attempt_id)

        completion = await self._ai_router.complete(
            AICompletionRequest(
                prompt=_build_review_prompt(capture),
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
            findings = _parse_ui_findings(completion.output_text)
            if findings is not None:
                outcome = AgentOutcome(
                    task_attempt_id=context.task_attempt_id,
                    completed_at=now,
                    result_data={"findings": findings},
                )
                disposition = UiReviewAgentDisposition.COMPLETED
            else:
                outcome = AgentOutcome(
                    task_attempt_id=context.task_attempt_id,
                    completed_at=now,
                    failure_code=_MALFORMED_OUTPUT_FAILURE_CODE,
                    summary=("The AI Router's response did not parse into a valid findings list."),
                )
                disposition = UiReviewAgentDisposition.FAILED
        else:
            assert completion.failure_code is not None
            outcome = AgentOutcome(
                task_attempt_id=context.task_attempt_id,
                completed_at=now,
                failure_code=completion.failure_code.value,
                summary="The AI Router returned a classified failure.",
            )
            disposition = UiReviewAgentDisposition.FAILED

        return await self._commit(context, outcome, disposition=disposition, usage=usage, now=now)

    async def _commit(
        self,
        context: ExecuteTaskContext,
        outcome: AgentOutcome,
        *,
        disposition: UiReviewAgentDisposition,
        usage: ProviderCallUsageRecord | None,
        now: datetime,
    ) -> UiReviewAgentResult:
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
        return UiReviewAgentResult(
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
    ) -> UiReviewAgentResult:
        existing_receipt = completed_work.receipt
        if existing_receipt.command_message_id != context.command_message_id:
            raise CommandIdentityConflictError(
                context.task_attempt_id, existing_receipt.command_message_id
            )
        if existing_receipt.command_digest != context.command_digest:
            raise CommandIntegrityError(context.command_message_id)

        if completed_work.outcome.task_attempt_id != context.task_attempt_id:
            raise MissingOutcomeInvariantError(context.task_attempt_id)
        return UiReviewAgentResult(
            disposition=UiReviewAgentDisposition.DUPLICATE_RESOLVED,
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
