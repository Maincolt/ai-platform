"""The Product Owner Agent's cycle logic (ADR-0026, ADR-0030).

Same shape as `scrum_master_agent.agent` (ADR-0028): no `handle(context,
*, now)` reacting to one `ExecuteTask` command. `run_cycle()` is the
operation a `PeriodicService` (`src/ai_platform/runtime/lifecycle.py`)
invokes on a fixed interval. Each cycle: check the kill switch, check
today's budget, fetch the board, make one AI Router call proposing a
bounded batch of actions, strictly parse/validate the proposal, then
dispatch each valid action independently -- one action's failure never
blocks or rolls back the others (ADR-0028 Decision 3, reused unchanged).
Every dispatch attempt, win or lose, is recorded to the durable audit log
before the cycle ends.
"""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from ai_platform.agents._autonomous_shared import estimate_spend_cents, strip_markdown_json_fence
from ai_platform.agents.product_owner_agent.errors import (
    BacklogFetchFailedError,
    TrackerActionFailedError,
)
from ai_platform.agents.product_owner_agent.tracker import BacklogTrackerPort, ProjectBoardSnapshot
from ai_platform.ports.ai_router import AICompletionRequest, AIRouterPort, DataClassification
from ai_platform.ports.persistence.autonomous import AutonomousStatePort

logger = logging.getLogger(__name__)

_ROLE = "product-owner"
_VALID_ACTIONS = frozenset(
    {
        "create_ticket",
        "edit_ticket",
        "close_ticket",
        "archive_draft_ticket",
        "reprioritize",
        "adjust_sprint_scope",
    }
)
_MAX_PROPOSED_ACTIONS = 10
_MAX_LONG_FIELD_LENGTH = 2000
_MAX_SHORT_FIELD_LENGTH = 200
# Sentinel `after_item_id` value meaning "move to the top of the board"
# (GraphQL's `updateProjectV2ItemPosition afterId: null`) -- every other
# field in this parser must be a non-empty string, so a real item_id and
# "move to top" both need a non-empty-string representation.
_REPRIORITIZE_TOP_SENTINEL = "TOP"
_ACTION_REQUIRED_KEYS: dict[str, frozenset[str]] = {
    "create_ticket": frozenset({"action", "title", "body", "rationale"}),
    "edit_ticket": frozenset({"action", "issue_url", "title", "body", "rationale"}),
    "close_ticket": frozenset({"action", "issue_url", "rationale"}),
    "archive_draft_ticket": frozenset({"action", "item_id", "rationale"}),
    "reprioritize": frozenset({"action", "item_id", "after_item_id", "rationale"}),
    "adjust_sprint_scope": frozenset({"action", "item_id", "status", "rationale"}),
}


@dataclass(frozen=True, slots=True)
class ProposedAction:
    action: str
    fields: dict[str, str]
    rationale: str


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
        "You are a product owner with real, autonomous write access to "
        "this project board. Review the board and respond with ONLY a "
        "JSON array (no prose, no markdown fences) of proposed action "
        "objects. You may propose zero actions if nothing is warranted "
        "-- do not act just to have done something. Each object must "
        'have an "action" key set to exactly one of "create_ticket", '
        '"edit_ticket", "close_ticket", "archive_draft_ticket", '
        '"reprioritize", or "adjust_sprint_scope", plus these keys for '
        "that action (no others):\n"
        '- "create_ticket": "title", "body" (the ticket description), '
        '"rationale" (one sentence).\n'
        '- "edit_ticket": "issue_url" (must match an item\'s url shown '
        'below exactly -- never a draft item), "title", "body" (the '
        'complete replacement title/body), "rationale" (one sentence).\n'
        '- "close_ticket": "issue_url" (must match an item\'s url shown '
        'below exactly -- never a draft item), "rationale" (one '
        "sentence).\n"
        '- "archive_draft_ticket": "item_id" (must match a draft item\'s '
        "item_id shown below exactly -- an item with no url), "
        '"rationale" (one sentence).\n'
        '- "reprioritize": "item_id" (must match an item_id shown below '
        'exactly), "after_item_id" (another item_id to place this item '
        f"directly after, or the literal string {_REPRIORITIZE_TOP_SENTINEL!r} "
        'to move it to the very top of the board), "rationale" (one '
        "sentence).\n"
        '- "adjust_sprint_scope": "item_id" (must match an item_id shown '
        'below exactly), "status" (the target status name -- a '
        '"Backlog"-style option removes it from the active sprint, an '
        'active-sprint option adds it), "rationale" (one sentence).\n\n'
        f"Board: {snapshot.title}\n"
        f"Items:\n{item_lines}"
    )


def _valid_field(value: object, *, maximum_length: int) -> bool:
    return isinstance(value, str) and bool(value) and len(value) <= maximum_length


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

        fields: dict[str, str] = {}
        for key in required_keys - {"action", "rationale"}:
            value = item[key]
            bound = (
                _MAX_SHORT_FIELD_LENGTH
                if key in {"item_id", "after_item_id", "status", "title", "issue_url"}
                else _MAX_LONG_FIELD_LENGTH
            )
            if not _valid_field(value, maximum_length=bound):
                return None
            fields[key] = cast(str, value)

        proposals.append(
            ProposedAction(action=action, fields=fields, rationale=cast(str, rationale))
        )
    return proposals


class ProductOwnerAgent:
    def __init__(
        self,
        *,
        agent_deployment_id: str,
        state: AutonomousStatePort,
        backlog_tracker: BacklogTrackerPort,
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
        self._backlog_tracker = backlog_tracker
        self._ai_router = ai_router
        self._max_output_tokens = max_output_tokens
        self._provider_deadline_seconds = provider_deadline_seconds
        self._max_actions_per_day = max_actions_per_day
        self._max_spend_cents_per_day = max_spend_cents_per_day

    async def run_cycle(self) -> None:
        if await self._state.is_kill_switch_engaged():
            logger.info("product-owner-agent: kill switch engaged, skipping cycle")
            return

        now = datetime.now(UTC)
        today = now.date()
        budget = await self._state.get_daily_budget(role=_ROLE, today=today)
        if (
            budget.actions_used >= self._max_actions_per_day
            or budget.spend_cents_used >= self._max_spend_cents_per_day
        ):
            logger.info("product-owner-agent: daily budget exhausted, skipping cycle")
            return

        try:
            snapshot = await self._backlog_tracker.fetch()
        except BacklogFetchFailedError as error:
            logger.warning("product-owner-agent: backlog fetch failed: %s", error.reason)
            return

        completion = await self._ai_router.complete(
            AICompletionRequest(
                prompt=_build_action_prompt(snapshot),
                max_output_tokens=self._max_output_tokens,
                idempotency_key=f"product-owner-{now.isoformat()}",
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
            logger.warning("product-owner-agent: AI Router returned a classified failure")
            return

        proposals = _parse_proposed_actions(completion.output_text)
        if proposals is None:
            logger.warning("product-owner-agent: proposed-actions response did not parse")
            return

        remaining_actions = self._max_actions_per_day - budget.actions_used
        for proposal in proposals:
            if remaining_actions <= 0:
                logger.info("product-owner-agent: daily action cap reached mid-cycle, stopping")
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
        if proposal.action == "create_ticket":
            await self._backlog_tracker.create_ticket(
                title=proposal.fields["title"], body=proposal.fields["body"]
            )
            return proposal.fields["title"]
        if proposal.action == "edit_ticket":
            issue_url = proposal.fields["issue_url"]
            await self._backlog_tracker.edit_ticket(
                issue_url=issue_url, title=proposal.fields["title"], body=proposal.fields["body"]
            )
            return issue_url
        if proposal.action == "close_ticket":
            issue_url = proposal.fields["issue_url"]
            await self._backlog_tracker.close_ticket(issue_url=issue_url)
            return issue_url
        if proposal.action == "archive_draft_ticket":
            item_id = proposal.fields["item_id"]
            await self._backlog_tracker.archive_draft_ticket(item_id=item_id)
            return item_id
        if proposal.action == "reprioritize":
            item_id = proposal.fields["item_id"]
            after_item_id = proposal.fields["after_item_id"]
            await self._backlog_tracker.reprioritize(
                item_id=item_id,
                after_item_id=None
                if after_item_id == _REPRIORITIZE_TOP_SENTINEL
                else after_item_id,
            )
            return item_id
        if proposal.action == "adjust_sprint_scope":
            item_id = proposal.fields["item_id"]
            await self._backlog_tracker.adjust_sprint_scope(
                item_id=item_id, status_name=proposal.fields["status"]
            )
            return item_id
        raise TrackerActionFailedError(proposal.action, "unrecognized action type")


def _proposal_target(proposal: ProposedAction) -> str:
    if proposal.action in {"edit_ticket", "close_ticket"}:
        return proposal.fields.get("issue_url", "")
    if proposal.action in {"archive_draft_ticket", "reprioritize", "adjust_sprint_scope"}:
        return proposal.fields.get("item_id", "")
    return proposal.fields.get("title", "")
