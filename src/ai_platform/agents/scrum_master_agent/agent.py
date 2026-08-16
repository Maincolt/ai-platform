"""The Scrum Master Agent's cycle logic (ADR-0026, ADR-0028).

Unlike every prior Agent, there is no `handle(context, *, now)` reacting
to one `ExecuteTask` command. Instead, `run_cycle()` is the operation a
`PeriodicService` (`src/ai_platform/runtime/lifecycle.py`) invokes on a
fixed interval. Each cycle: check the kill switch, check today's budget,
fetch the board, make one AI Router call proposing a bounded batch of
actions, strictly parse/validate the proposal, then dispatch each valid
action independently -- one action's failure never blocks or rolls back
the others (ADR-0028 Decision 3). Every dispatch attempt, win or lose,
is recorded to the durable audit log before the cycle ends.
"""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from ai_platform.agents.scrum_master_agent.errors import (
    ProjectBoardFetchFailedError,
    TrackerActionFailedError,
)
from ai_platform.agents.scrum_master_agent.tracker import ProjectBoardSnapshot, ProjectTrackerPort
from ai_platform.ports.ai_router import AICompletionRequest, AIRouterPort, DataClassification
from ai_platform.ports.ai_router import AICompletionUsage as ProviderCallUsage
from ai_platform.ports.persistence.autonomous import AutonomousStatePort

logger = logging.getLogger(__name__)

_ROLE = "scrum-master"
_VALID_ACTIONS = frozenset({"set_status", "add_comment", "create_draft_item"})
_MAX_PROPOSED_ACTIONS = 10
_MAX_LONG_FIELD_LENGTH = 2000
_MAX_SHORT_FIELD_LENGTH = 200
_ACTION_REQUIRED_KEYS: dict[str, frozenset[str]] = {
    "set_status": frozenset({"action", "item_id", "status", "rationale"}),
    "add_comment": frozenset({"action", "issue_url", "body", "rationale"}),
    "create_draft_item": frozenset({"action", "title", "body", "rationale"}),
}

# Rough, hardcoded USD-cents-per-1000-tokens estimates (input_rate,
# output_rate) for the ADR-0017 Decision 3-approved models -- NOT exact
# provider billing (ADR-0028 Decision 2). Update to match real current
# pricing before relying on the daily spend cap for anything beyond a
# rough circuit breaker; the action-count cap is the primary practical
# limiter.
_MODEL_RATE_CENTS_PER_1K_TOKENS: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (0.1, 0.5),
    "gpt-5-mini": (0.025, 0.2),
}
_DEFAULT_RATE_CENTS_PER_1K_TOKENS = (0.5, 1.5)


@dataclass(frozen=True, slots=True)
class ProposedAction:
    action: str
    fields: dict[str, str]
    rationale: str


def _estimate_spend_cents(usage: ProviderCallUsage) -> int:
    input_rate, output_rate = _MODEL_RATE_CENTS_PER_1K_TOKENS.get(
        usage.model, _DEFAULT_RATE_CENTS_PER_1K_TOKENS
    )
    estimated = (usage.input_tokens / 1000) * input_rate + (
        usage.output_tokens / 1000
    ) * output_rate
    return max(0, round(estimated))


def _build_action_prompt(snapshot: ProjectBoardSnapshot) -> str:
    item_lines = (
        "\n".join(
            f'- item_id={item.item_id!r} title="{item.title}" status="{item.status or "no status"}"'
            + (f" url={item.url}" if item.url else " (draft item, no URL)")
            for item in snapshot.items
        )
        or "(no items)"
    )
    return (
        "You are a scrum master with real, autonomous write access to "
        "this project board. Review the board and respond with ONLY a "
        "JSON array (no prose, no markdown fences) of proposed action "
        "objects. You may propose zero actions if nothing is warranted "
        "-- do not act just to have done something. Each object must "
        'have an "action" key set to exactly one of "set_status", '
        '"add_comment", or "create_draft_item", plus these keys for '
        "that action (no others):\n"
        '- "set_status": "item_id" (must match an item_id shown below '
        'exactly), "status" (the target status name), "rationale" (one '
        "sentence).\n"
        '- "add_comment": "issue_url" (must match an item\'s url shown '
        'below exactly -- never a draft item), "body" (the comment '
        'text), "rationale" (one sentence).\n'
        '- "create_draft_item": "title", "body" (the draft issue '
        'description), "rationale" (one sentence).\n\n'
        f"Board: {snapshot.title}\n"
        f"Items:\n{item_lines}"
    )


def _strip_markdown_json_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) < 2 or lines[-1].strip() != "```":
        return stripped
    return "\n".join(lines[1:-1]).strip()


def _valid_field(value: object, *, maximum_length: int) -> bool:
    return isinstance(value, str) and bool(value) and len(value) <= maximum_length


def _parse_proposed_actions(output_text: str) -> list[ProposedAction] | None:
    """Parse and validate the provider's raw response into a bounded,
    strictly-typed list of proposed actions. Returns `None` on any
    shape/content mismatch anywhere in the batch -- the caller treats
    that as "propose nothing this cycle," never a partial acceptance."""
    try:
        parsed: object = json.loads(_strip_markdown_json_fence(output_text))
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

        fields: dict[str, str] = {}
        for key in required_keys - {"action", "rationale"}:
            value = item[key]
            bound = (
                _MAX_SHORT_FIELD_LENGTH
                if key in {"item_id", "status", "title", "issue_url"}
                else _MAX_LONG_FIELD_LENGTH
            )
            if not _valid_field(value, maximum_length=bound):
                return None
            fields[key] = cast(str, value)

        proposals.append(
            ProposedAction(action=action, fields=fields, rationale=cast(str, rationale))
        )
    return proposals


class ScrumMasterAgent:
    def __init__(
        self,
        *,
        agent_deployment_id: str,
        state: AutonomousStatePort,
        project_tracker: ProjectTrackerPort,
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
        self._project_tracker = project_tracker
        self._ai_router = ai_router
        self._max_output_tokens = max_output_tokens
        self._provider_deadline_seconds = provider_deadline_seconds
        self._max_actions_per_day = max_actions_per_day
        self._max_spend_cents_per_day = max_spend_cents_per_day

    async def run_cycle(self) -> None:
        if await self._state.is_kill_switch_engaged():
            logger.info("scrum-master-agent: kill switch engaged, skipping cycle")
            return

        now = datetime.now(UTC)
        today = now.date()
        budget = await self._state.get_daily_budget(role=_ROLE, today=today)
        if (
            budget.actions_used >= self._max_actions_per_day
            or budget.spend_cents_used >= self._max_spend_cents_per_day
        ):
            logger.info("scrum-master-agent: daily budget exhausted, skipping cycle")
            return

        try:
            snapshot = await self._project_tracker.fetch()
        except ProjectBoardFetchFailedError as error:
            logger.warning("scrum-master-agent: board fetch failed: %s", error.reason)
            return

        completion = await self._ai_router.complete(
            AICompletionRequest(
                prompt=_build_action_prompt(snapshot),
                max_output_tokens=self._max_output_tokens,
                idempotency_key=f"scrum-master-{now.isoformat()}",
                deadline=now + timedelta(seconds=self._provider_deadline_seconds),
                classification=DataClassification.NO_SPECIAL_HANDLING,
            )
        )
        if completion.usage is not None:
            spend_cents = _estimate_spend_cents(completion.usage)
            if spend_cents:
                await self._state.record_budget_usage(
                    role=_ROLE, today=today, actions=0, spend_cents=spend_cents
                )

        if completion.output_text is None:
            logger.warning("scrum-master-agent: AI Router returned a classified failure")
            return

        proposals = _parse_proposed_actions(completion.output_text)
        if proposals is None:
            logger.warning("scrum-master-agent: proposed-actions response did not parse")
            return

        remaining_actions = self._max_actions_per_day - budget.actions_used
        for proposal in proposals:
            if remaining_actions <= 0:
                logger.info("scrum-master-agent: daily action cap reached mid-cycle, stopping")
                break
            await self._dispatch(proposal, now=now)
            remaining_actions -= 1

    async def _dispatch(self, proposal: ProposedAction, *, now: datetime) -> None:
        try:
            target = await self._dispatch_action(proposal)
        except TrackerActionFailedError as error:
            await self._state.record_action(
                agent_deployment_id=self._agent_deployment_id,
                role=_ROLE,
                action_type=proposal.action,
                target=_proposal_target(proposal),
                inputs={**proposal.fields, "rationale": proposal.rationale},
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
            target=target,
            inputs={**proposal.fields, "rationale": proposal.rationale},
            result_status="SUCCEEDED",
            result_detail="ok",
            occurred_at=now,
        )
        await self._state.record_budget_usage(
            role=_ROLE, today=now.date(), actions=1, spend_cents=0
        )

    async def _dispatch_action(self, proposal: ProposedAction) -> str:
        if proposal.action == "set_status":
            item_id = proposal.fields["item_id"]
            await self._project_tracker.set_status(
                item_id=item_id, status_name=proposal.fields["status"]
            )
            return item_id
        if proposal.action == "add_comment":
            issue_url = proposal.fields["issue_url"]
            await self._project_tracker.add_comment(
                issue_url=issue_url, body=proposal.fields["body"]
            )
            return issue_url
        if proposal.action == "create_draft_item":
            await self._project_tracker.create_draft_item(
                title=proposal.fields["title"], body=proposal.fields["body"]
            )
            return proposal.fields["title"]
        raise TrackerActionFailedError(proposal.action, "unrecognized action type")


def _proposal_target(proposal: ProposedAction) -> str:
    if proposal.action == "set_status":
        return proposal.fields.get("item_id", "")
    if proposal.action == "add_comment":
        return proposal.fields.get("issue_url", "")
    return proposal.fields.get("title", "")
