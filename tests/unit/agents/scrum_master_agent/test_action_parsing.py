"""Tests for `scrum_master_agent.agent._parse_proposed_actions` -- turning
the AI Router's raw text response into a structured, strictly-typed
batch of proposed actions, or `None` (never a partial/best-effort
result) on any shape mismatch anywhere in the batch.
"""

import json

from ai_platform.agents.scrum_master_agent.agent import (
    ProposedAction,
    _parse_proposed_actions,  # pyright: ignore[reportPrivateUsage]
)


def _actions_json(actions: list[dict[str, object]]) -> str:
    return json.dumps(actions)


def test_empty_array_is_a_valid_empty_proposal() -> None:
    assert _parse_proposed_actions("[]") == []


def test_well_formed_set_status_action_parses_correctly() -> None:
    raw = _actions_json(
        [
            {
                "action": "set_status",
                "item_id": "PVTI_item1",
                "status": "In Progress",
                "rationale": "It has a recent commit.",
            }
        ]
    )

    parsed = _parse_proposed_actions(raw)

    assert parsed == [
        ProposedAction(
            action="set_status",
            fields={"item_id": "PVTI_item1", "status": "In Progress"},
            rationale="It has a recent commit.",
        )
    ]


def test_well_formed_add_comment_action_parses_correctly() -> None:
    raw = _actions_json(
        [
            {
                "action": "add_comment",
                "issue_url": "https://github.com/octocat/repo/issues/1",
                "body": "Following up on this.",
                "rationale": "Stale for 5 days.",
            }
        ]
    )

    parsed = _parse_proposed_actions(raw)

    assert parsed is not None
    assert parsed[0].action == "add_comment"
    assert parsed[0].fields["issue_url"] == "https://github.com/octocat/repo/issues/1"


def test_well_formed_create_draft_item_action_parses_correctly() -> None:
    raw = _actions_json(
        [
            {
                "action": "create_draft_item",
                "title": "Write onboarding docs",
                "body": "Nobody has documented setup yet.",
                "rationale": "Gap noticed while reviewing the board.",
            }
        ]
    )

    parsed = _parse_proposed_actions(raw)

    assert parsed is not None
    assert parsed[0].action == "create_draft_item"


def test_multiple_actions_in_one_batch_all_parse() -> None:
    raw = _actions_json(
        [
            {
                "action": "set_status",
                "item_id": "a",
                "status": "Done",
                "rationale": "x",
            },
            {
                "action": "create_draft_item",
                "title": "b",
                "body": "c",
                "rationale": "y",
            },
        ]
    )

    parsed = _parse_proposed_actions(raw)

    assert parsed is not None
    assert len(parsed) == 2


def test_response_wrapped_in_a_json_markdown_fence_still_parses() -> None:
    raw = "```json\n" + _actions_json([]) + "\n```"
    assert _parse_proposed_actions(raw) == []


def test_non_json_text_is_rejected() -> None:
    assert _parse_proposed_actions("here is my plan for the sprint...") is None


def test_json_object_instead_of_array_is_rejected() -> None:
    assert _parse_proposed_actions(json.dumps({"action": "set_status"})) is None


def test_unrecognized_action_type_is_rejected() -> None:
    raw = json.dumps([{"action": "delete_everything", "rationale": "x"}])
    assert _parse_proposed_actions(raw) is None


def test_action_missing_a_required_key_is_rejected() -> None:
    raw = json.dumps([{"action": "set_status", "item_id": "a", "rationale": "x"}])  # no status
    assert _parse_proposed_actions(raw) is None


def test_action_with_an_extra_key_is_rejected() -> None:
    raw = json.dumps(
        [
            {
                "action": "set_status",
                "item_id": "a",
                "status": "Done",
                "rationale": "x",
                "confidence": 0.9,
            }
        ]
    )
    assert _parse_proposed_actions(raw) is None


def test_action_with_fields_from_a_different_action_type_is_rejected() -> None:
    """A set_status object carrying add_comment's `issue_url`/`body`
    fields instead of `item_id`/`status` must not accidentally pass."""
    raw = json.dumps([{"action": "set_status", "issue_url": "x", "body": "y", "rationale": "z"}])
    assert _parse_proposed_actions(raw) is None


def test_action_with_an_empty_field_is_rejected() -> None:
    raw = json.dumps([{"action": "set_status", "item_id": "", "status": "Done", "rationale": "x"}])
    assert _parse_proposed_actions(raw) is None


def test_action_with_an_oversized_short_field_is_rejected() -> None:
    raw = json.dumps(
        [{"action": "set_status", "item_id": "x" * 201, "status": "Done", "rationale": "y"}]
    )
    assert _parse_proposed_actions(raw) is None


def test_action_with_a_non_string_field_is_rejected() -> None:
    raw = json.dumps([{"action": "set_status", "item_id": 5, "status": "Done", "rationale": "x"}])
    assert _parse_proposed_actions(raw) is None


def test_a_non_object_array_item_is_rejected() -> None:
    assert _parse_proposed_actions(json.dumps(["not an object"])) is None


def test_too_many_proposed_actions_is_rejected() -> None:
    raw = _actions_json(
        [
            {"action": "set_status", "item_id": "a", "status": "Done", "rationale": "x"}
            for _ in range(11)
        ]
    )
    assert _parse_proposed_actions(raw) is None
