"""The Principal Developer Agent's cycle logic (ADR-0026, ADR-0031).

Same shape as `scrum_master_agent.agent`/`product_owner_agent.agent`: no
`handle(context, *, now)` reacting to one `ExecuteTask` command.
`run_cycle()` is the operation a `PeriodicService`
(`src/ai_platform/runtime/lifecycle.py`) invokes on a fixed interval.
Each cycle: check the kill switch, check today's budget, fetch open pull
requests, make one AI Router call proposing a bounded batch of actions,
strictly parse/validate the proposal, then dispatch each valid action
independently -- one action's failure never blocks or rolls back the
others (ADR-0028 Decision 3, reused unchanged). Every dispatch attempt,
win or lose, is recorded to the durable audit log before the cycle ends.

`merge` is additionally re-verified against GitHub's live
`mergeable_state` immediately before the merge call itself
(`source_control.py`'s `merge()`) -- this module never trusts the
snapshot fetched at cycle start for that decision.
"""

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from ai_platform.agents._autonomous_shared import estimate_spend_cents, strip_markdown_json_fence
from ai_platform.agents.principal_developer_agent.errors import (
    PullRequestFetchFailedError,
    SourceControlActionFailedError,
)
from ai_platform.agents.principal_developer_agent.source_control import (
    PullRequestSnapshot,
    SourceControlPort,
)
from ai_platform.ports.ai_router import AICompletionRequest, AIRouterPort, DataClassification
from ai_platform.ports.persistence.autonomous import AutonomousStatePort

logger = logging.getLogger(__name__)

_ROLE = "principal-developer"
_VALID_ACTIONS = frozenset({"request_changes", "merge"})
_MAX_PROPOSED_ACTIONS = 10
_MAX_LONG_FIELD_LENGTH = 2000
_MAX_PULL_NUMBER = 1_000_000
_ACTION_REQUIRED_KEYS: dict[str, frozenset[str]] = {
    "request_changes": frozenset({"action", "pull_number", "body", "rationale"}),
    "merge": frozenset({"action", "pull_number", "rationale"}),
}
_PULL_NUMBER_PATTERN = re.compile(r"^[1-9][0-9]*$")
_MERGEABLE_STATE_CLEAN = "clean"


@dataclass(frozen=True, slots=True)
class ProposedAction:
    action: str
    pull_number: int
    body: str | None
    rationale: str


def _build_action_prompt(pull_requests: tuple[PullRequestSnapshot, ...]) -> str:
    pull_request_lines = (
        "\n".join(
            f'- #{pr.number} "{pr.title}" mergeable_state={pr.mergeable_state!r}'
            for pr in pull_requests
        )
        or "(no open pull requests)"
    )
    return (
        "You are a principal developer with real, autonomous review and "
        "merge access to this repository. Review the open pull requests "
        "below and respond with ONLY a JSON array (no prose, no markdown "
        "fences) of proposed action objects. You may propose zero "
        "actions if nothing is warranted -- do not act just to have "
        "done something. Only merge a pull request whose "
        f"mergeable_state is exactly {_MERGEABLE_STATE_CLEAN!r} -- never "
        "merge one with any other mergeable_state. Each object must "
        'have an "action" key set to exactly one of "request_changes" '
        'or "merge", plus these keys for that action (no others):\n'
        '- "request_changes": "pull_number" (the PR number as a string, '
        'e.g. "42"), "body" (the review comment explaining what needs '
        'to change), "rationale" (one sentence).\n'
        '- "merge": "pull_number" (the PR number as a string, must have '
        f"mergeable_state {_MERGEABLE_STATE_CLEAN!r} in the list below), "
        '"rationale" (one sentence).\n\n'
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
        action = item.get("action")
        if action not in _VALID_ACTIONS:
            return None
        action = cast(str, action)
        required_keys = _ACTION_REQUIRED_KEYS[action]
        if frozenset(item.keys()) != required_keys:
            return None

        rationale = item.get("rationale")
        if not _valid_field(rationale, maximum_length=_MAX_LONG_FIELD_LENGTH):
            return None

        pull_number = _valid_pull_number(item.get("pull_number"))
        if pull_number is None:
            return None

        body: str | None = None
        if action == "request_changes":
            body_value = item.get("body")
            if not _valid_field(body_value, maximum_length=_MAX_LONG_FIELD_LENGTH):
                return None
            body = cast(str, body_value)

        proposals.append(
            ProposedAction(
                action=action,
                pull_number=pull_number,
                body=body,
                rationale=cast(str, rationale),
            )
        )
    return proposals


class PrincipalDeveloperAgent:
    def __init__(
        self,
        *,
        agent_deployment_id: str,
        state: AutonomousStatePort,
        source_control: SourceControlPort,
        ai_router: AIRouterPort,
        max_output_tokens: int,
        provider_deadline_seconds: float,
        max_actions_per_day: int,
        max_spend_cents_per_day: int,
    ) -> None:
        if max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        if provider_deadline_seconds <= 0:
            raise ValueError("provider_deadline_seconds must be positive")
        if max_actions_per_day <= 0:
            raise ValueError("max_actions_per_day must be positive")
        if max_spend_cents_per_day <= 0:
            raise ValueError("max_spend_cents_per_day must be positive")
        self._agent_deployment_id = agent_deployment_id
        self._state = state
        self._source_control = source_control
        self._ai_router = ai_router
        self._max_output_tokens = max_output_tokens
        self._provider_deadline_seconds = provider_deadline_seconds
        self._max_actions_per_day = max_actions_per_day
        self._max_spend_cents_per_day = max_spend_cents_per_day

    async def run_cycle(self) -> None:
        if await self._state.is_kill_switch_engaged():
            logger.info("principal-developer-agent: kill switch engaged, skipping cycle")
            return

        now = datetime.now(UTC)
        today = now.date()
        budget = await self._state.get_daily_budget(role=_ROLE, today=today)
        if (
            budget.actions_used >= self._max_actions_per_day
            or budget.spend_cents_used >= self._max_spend_cents_per_day
        ):
            logger.info("principal-developer-agent: daily budget exhausted, skipping cycle")
            return

        try:
            pull_requests = await self._source_control.fetch_open_pull_requests()
        except PullRequestFetchFailedError as error:
            logger.warning("principal-developer-agent: pull request fetch failed: %s", error.reason)
            return

        completion = await self._ai_router.complete(
            AICompletionRequest(
                prompt=_build_action_prompt(pull_requests),
                max_output_tokens=self._max_output_tokens,
                idempotency_key=f"principal-developer-{now.isoformat()}",
                deadline=now + timedelta(seconds=self._provider_deadline_seconds),
                classification=DataClassification.NO_SPECIAL_HANDLING,
            )
        )
        if completion.usage is not None:
            spend_cents = estimate_spend_cents(completion.usage)
            if spend_cents:
                await self._state.record_budget_usage(
                    role=_ROLE, today=today, actions=0, spend_cents=spend_cents
                )

        if completion.output_text is None:
            logger.warning("principal-developer-agent: AI Router returned a classified failure")
            return

        proposals = _parse_proposed_actions(completion.output_text)
        if proposals is None:
            logger.warning("principal-developer-agent: proposed-actions response did not parse")
            return

        remaining_actions = self._max_actions_per_day - budget.actions_used
        for proposal in proposals:
            if remaining_actions <= 0:
                logger.info(
                    "principal-developer-agent: daily action cap reached mid-cycle, stopping"
                )
                break
            await self._dispatch(proposal, now=now)
            remaining_actions -= 1

    async def _dispatch(self, proposal: ProposedAction, *, now: datetime) -> None:
        inputs: dict[str, object] = {
            "pull_number": str(proposal.pull_number),
            "rationale": proposal.rationale,
        }
        if proposal.body is not None:
            inputs["body"] = proposal.body

        try:
            await self._dispatch_action(proposal)
        except SourceControlActionFailedError as error:
            await self._state.record_action(
                agent_deployment_id=self._agent_deployment_id,
                role=_ROLE,
                action_type=proposal.action,
                target=str(proposal.pull_number),
                inputs=inputs,
                result_status="FAILED",
                result_detail=str(error),
                occurred_at=now,
            )
            await self._state.record_budget_usage(
                role=_ROLE, today=now.date(), actions=1, spend_cents=0
            )
            return

        await self._state.record_action(
            agent_deployment_id=self._agent_deployment_id,
            role=_ROLE,
            action_type=proposal.action,
            target=str(proposal.pull_number),
            inputs=inputs,
            result_status="SUCCEEDED",
            result_detail="ok",
            occurred_at=now,
        )
        await self._state.record_budget_usage(
            role=_ROLE, today=now.date(), actions=1, spend_cents=0
        )

    async def _dispatch_action(self, proposal: ProposedAction) -> None:
        if proposal.action == "request_changes":
            assert proposal.body is not None
            await self._source_control.request_changes(
                pull_number=proposal.pull_number, body=proposal.body
            )
            return
        if proposal.action == "merge":
            await self._source_control.merge(pull_number=proposal.pull_number)
            return
        raise SourceControlActionFailedError(proposal.action, "unrecognized action type")
