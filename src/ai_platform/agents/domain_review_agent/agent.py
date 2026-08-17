"""The Domain Review Agent's cycle logic (ADR-0026, ADR-0033).

Same shape as every prior autonomous role's `agent.py`: no
`handle(context, *, now)` reacting to one `ExecuteTask` command.
`run_cycle()` is the operation a `PeriodicService`
(`src/ai_platform/runtime/lifecycle.py`) invokes on a fixed interval.
Each cycle: check the kill switch, check today's budget, fetch open pull
requests, filter to only those touching this role's own domain (before
any AI Router call -- a PR outside the domain is never shown to the
model), make one AI Router call proposing a bounded batch of
`request_changes` actions, strictly parse/validate the proposal, then
dispatch each valid action independently. Every dispatch attempt, win or
lose, is recorded to the durable audit log before the cycle ends.

Unlike every prior role, one `DomainReviewAgent` instance backs two
distinct deployments (`frontend-specialist-agent`,
`postgres-specialist-agent`) -- `role`, `domain_label`, and
`path_prefixes` are constructor parameters, not module constants.
"""

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from ai_platform.agents._autonomous_shared import estimate_spend_cents, strip_markdown_json_fence
from ai_platform.agents._pull_request_review_shared import (
    PullRequestReviewPort,
    PullRequestSnapshot,
)
from ai_platform.agents.domain_review_agent.errors import (
    PullRequestFetchFailedError,
    ReviewActionFailedError,
)
from ai_platform.ports.ai_router import AICompletionRequest, AIRouterPort, DataClassification
from ai_platform.ports.persistence.autonomous import AutonomousStatePort

logger = logging.getLogger(__name__)

_MAX_PROPOSED_ACTIONS = 10
_MAX_BODY_LENGTH = 2000
_MAX_PULL_NUMBER = 1_000_000
_REQUIRED_KEYS = frozenset({"action", "pull_number", "body", "rationale"})
_PULL_NUMBER_PATTERN = re.compile(r"^[1-9][0-9]*$")


@dataclass(frozen=True, slots=True)
class ProposedAction:
    pull_number: int
    body: str
    rationale: str


def _pull_request_in_domain(
    pull_request: PullRequestSnapshot, *, path_prefixes: tuple[str, ...]
) -> bool:
    return any(
        path.startswith(prefix)
        for path in pull_request.changed_file_paths
        for prefix in path_prefixes
    )


def _build_action_prompt(
    *, domain_label: str, pull_requests: tuple[PullRequestSnapshot, ...]
) -> str:
    pull_request_lines = (
        "\n".join(f'- #{pr.number} "{pr.title}"' for pr in pull_requests)
        or "(no open pull requests touch this domain)"
    )
    return (
        f"You are a {domain_label} specialist with real, autonomous "
        "code-review access to this repository -- but only the ability "
        "to request changes, never to merge or write anything yourself. "
        "Review the open pull requests below (already filtered to ones "
        f"touching {domain_label} files) and respond with ONLY a JSON "
        "array (no prose, no markdown fences) of proposed "
        '"request_changes" objects. You may propose zero actions if '
        "nothing is warranted -- do not act just to have done "
        'something. Each object must have "action" set to exactly '
        '"request_changes", "pull_number" (the PR number as a string, '
        'e.g. "42"), "body" (the review comment explaining what needs '
        'to change), and "rationale" (one sentence).\n\n'
        f"Open pull requests:\n{pull_request_lines}"
    )


def _valid_field(value: object, *, maximum_length: int) -> bool:
    return isinstance(value, str) and bool(value) and len(value) <= maximum_length


def _valid_pull_number(value: object) -> int | None:
    if not isinstance(value, str) or not _PULL_NUMBER_PATTERN.match(value):
        return None
    number = int(value)
    if number > _MAX_PULL_NUMBER:
        return None
    return number


def _parse_proposed_actions(output_text: str) -> list[ProposedAction] | None:
    """Parse and validate the provider's raw response into a bounded,
    strictly-typed list of proposed actions. Returns `None` on any
    shape/content mismatch anywhere in the batch -- the caller treats
    that as "propose nothing this cycle," never a partial acceptance."""
    try:
        parsed: object = json.loads(strip_markdown_json_fence(output_text))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, list):
        return None
    candidates = cast(list[object], parsed)
    if len(candidates) > _MAX_PROPOSED_ACTIONS:
        return None

    proposals: list[ProposedAction] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            return None
        item = cast(dict[str, object], candidate)
        if frozenset(item.keys()) != _REQUIRED_KEYS:
            return None
        if item.get("action") != "request_changes":
            return None

        rationale = item.get("rationale")
        if not _valid_field(rationale, maximum_length=_MAX_BODY_LENGTH):
            return None
        body = item.get("body")
        if not _valid_field(body, maximum_length=_MAX_BODY_LENGTH):
            return None
        pull_number = _valid_pull_number(item.get("pull_number"))
        if pull_number is None:
            return None

        proposals.append(
            ProposedAction(
                pull_number=pull_number, body=cast(str, body), rationale=cast(str, rationale)
            )
        )
    return proposals


class DomainReviewAgent:
    def __init__(
        self,
        *,
        role: str,
        domain_label: str,
        path_prefixes: tuple[str, ...],
        agent_deployment_id: str,
        state: AutonomousStatePort,
        pull_request_review: PullRequestReviewPort,
        ai_router: AIRouterPort,
        max_output_tokens: int,
        provider_deadline_seconds: float,
        max_actions_per_day: int,
        max_spend_cents_per_day: int,
    ) -> None:
        if not role:
            raise ValueError("role must be non-empty")
        if not domain_label:
            raise ValueError("domain_label must be non-empty")
        if not path_prefixes:
            raise ValueError("path_prefixes must be non-empty")
        if max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        if provider_deadline_seconds <= 0:
            raise ValueError("provider_deadline_seconds must be positive")
        if max_actions_per_day <= 0:
            raise ValueError("max_actions_per_day must be positive")
        if max_spend_cents_per_day <= 0:
            raise ValueError("max_spend_cents_per_day must be positive")
        self._role = role
        self._domain_label = domain_label
        self._path_prefixes = path_prefixes
        self._agent_deployment_id = agent_deployment_id
        self._state = state
        self._pull_request_review = pull_request_review
        self._ai_router = ai_router
        self._max_output_tokens = max_output_tokens
        self._provider_deadline_seconds = provider_deadline_seconds
        self._max_actions_per_day = max_actions_per_day
        self._max_spend_cents_per_day = max_spend_cents_per_day

    async def run_cycle(self) -> None:
        if await self._state.is_kill_switch_engaged():
            logger.info("%s: kill switch engaged, skipping cycle", self._role)
            return

        now = datetime.now(UTC)
        today = now.date()
        budget = await self._state.get_daily_budget(role=self._role, today=today)
        if (
            budget.actions_used >= self._max_actions_per_day
            or budget.spend_cents_used >= self._max_spend_cents_per_day
        ):
            logger.info("%s: daily budget exhausted, skipping cycle", self._role)
            return

        try:
            all_pull_requests = await self._pull_request_review.fetch_open_pull_requests()
        except PullRequestFetchFailedError as error:
            logger.warning("%s: pull request fetch failed: %s", self._role, error.reason)
            return

        in_domain = tuple(
            pr
            for pr in all_pull_requests
            if _pull_request_in_domain(pr, path_prefixes=self._path_prefixes)
        )
        if not in_domain:
            logger.info("%s: no open pull requests touch this domain", self._role)
            return

        completion = await self._ai_router.complete(
            AICompletionRequest(
                prompt=_build_action_prompt(
                    domain_label=self._domain_label, pull_requests=in_domain
                ),
                max_output_tokens=self._max_output_tokens,
                idempotency_key=f"{self._role}-{now.isoformat()}",
                deadline=now + timedelta(seconds=self._provider_deadline_seconds),
                classification=DataClassification.NO_SPECIAL_HANDLING,
            )
        )
        if completion.usage is not None:
            spend_cents = estimate_spend_cents(completion.usage)
            if spend_cents:
                await self._state.record_budget_usage(
                    role=self._role, today=today, actions=0, spend_cents=spend_cents
                )

        if completion.output_text is None:
            logger.warning("%s: AI Router returned a classified failure", self._role)
            return

        proposals = _parse_proposed_actions(completion.output_text)
        if proposals is None:
            logger.warning("%s: proposed-actions response did not parse", self._role)
            return

        remaining_actions = self._max_actions_per_day - budget.actions_used
        for proposal in proposals:
            if remaining_actions <= 0:
                logger.info("%s: daily action cap reached mid-cycle, stopping", self._role)
                break
            await self._dispatch(proposal, now=now)
            remaining_actions -= 1

    async def _dispatch(self, proposal: ProposedAction, *, now: datetime) -> None:
        inputs = {"body": proposal.body, "rationale": proposal.rationale}
        try:
            await self._pull_request_review.request_changes(
                pull_number=proposal.pull_number, body=proposal.body
            )
        except ReviewActionFailedError as error:
            await self._state.record_action(
                agent_deployment_id=self._agent_deployment_id,
                role=self._role,
                action_type="request_changes",
                target=str(proposal.pull_number),
                inputs=inputs,
                result_status="FAILED",
                result_detail=str(error),
                occurred_at=now,
            )
            await self._state.record_budget_usage(
                role=self._role, today=now.date(), actions=1, spend_cents=0
            )
            return

        await self._state.record_action(
            agent_deployment_id=self._agent_deployment_id,
            role=self._role,
            action_type="request_changes",
            target=str(proposal.pull_number),
            inputs=inputs,
            result_status="SUCCEEDED",
            result_detail="ok",
            occurred_at=now,
        )
        await self._state.record_budget_usage(
            role=self._role, today=now.date(), actions=1, spend_cents=0
        )
