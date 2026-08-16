"""Tests for `product_owner_agent.agent._parse_proposed_actions` -- same
strict discriminated-union parsing discipline as
`scrum_master_agent.agent`, extended with a sixth action type and the
`reprioritize` top-of-board sentinel.
"""

import json

from ai_platform.agents.product_owner_agent.agent import (
    ProposedAction,
    _parse_proposed_actions,  # pyright: ignore[reportPrivateUsage]
)


def _actions_json(actions: list[dict[str, object]]) -> str:
    return json.dumps(actions)


def test_empty_array_is_a_valid_empty_proposal() -> None:
    assert _parse_proposed_actions("[]") == []


def test_well_formed_create_ticket_action_parses_correctly() -> None:
    raw = _actions_json(
        [
            {
                "action": "create_ticket",
                "title": "Write onboarding docs",
                "body": "Nobody has documented setup yet.",
                "rationale": "Gap noticed while reviewing the board.",
            }
        ]
    )

    parsed = _parse_proposed_actions(raw)

    assert parsed is not None
    assert parsed[0].action == "create_ticket"


def test_well_formed_edit_ticket_action_parses_correctly() -> None:
    raw = _actions_json(
        [
            {
                "action": "edit_ticket",
                "issue_url": "https://github.com/octocat/repo/issues/1",
                "title": "Updated title",
                "body": "Updated body",
                "rationale": "Scope changed.",
            }
        ]
    )

    parsed = _parse_proposed_actions(raw)

    assert parsed is not None
    assert parsed[0].fields["issue_url"] == "https://github.com/octocat/repo/issues/1"


def test_well_formed_close_ticket_action_parses_correctly() -> None:
    raw = _actions_json(
        [
            {
                "action": "close_ticket",
                "issue_url": "https://github.com/octocat/repo/issues/1",
                "rationale": "No longer needed.",
            }
        ]
    )

    parsed = _parse_proposed_actions(raw)

    assert parsed is not None
    assert parsed[0].action == "close_ticket"


def test_well_formed_archive_draft_ticket_action_parses_correctly() -> None:
    raw = _actions_json(
        [
            {
                "action": "archive_draft_ticket",
                "item_id": "PVTI_item1",
                "rationale": "Duplicate of an existing ticket.",
            }
        ]
    )

    parsed = _parse_proposed_actions(raw)

    assert parsed == [
        ProposedAction(
            action="archive_draft_ticket",
            fields={"item_id": "PVTI_item1"},
            rationale="Duplicate of an existing ticket.",
        )
    ]


def test_well_formed_reprioritize_action_parses_correctly() -> None:
    raw = _actions_json(
        [
            {
                "action": "reprioritize",
                "item_id": "PVTI_item1",
                "after_item_id": "TOP",
                "rationale": "Highest priority this sprint.",
            }
        ]
    )

    parsed = _parse_proposed_actions(raw)

    assert parsed is not None
    assert parsed[0].fields["after_item_id"] == "TOP"


def test_well_formed_adjust_sprint_scope_action_parses_correctly() -> None:
    raw = _actions_json(
        [
            {
                "action": "adjust_sprint_scope",
                "item_id": "PVTI_item1",
                "status": "Backlog",
                "rationale": "Deprioritized out of this sprint.",
            }
        ]
    )

    parsed = _parse_proposed_actions(raw)

    assert parsed is not None
    assert parsed[0].fields["status"] == "Backlog"


def test_multiple_actions_in_one_batch_all_parse() -> None:
    raw = _actions_json(
        [
            {"action": "create_ticket", "title": "a", "body": "b", "rationale": "x"},
            {"action": "archive_draft_ticket", "item_id": "c", "rationale": "y"},
        ]
    )

    parsed = _parse_proposed_actions(raw)

    assert parsed is not None
    assert len(parsed) == 2


def test_response_wrapped_in_a_json_markdown_fence_still_parses() -> None:
    raw = "```json\n" + _actions_json([]) + "\n```"
    assert _parse_proposed_actions(raw) == []


def test_non_json_text_is_rejected() -> None:
    assert _parse_proposed_actions("here is my plan for the backlog...") is None


def test_json_object_instead_of_array_is_rejected() -> None:
    assert _parse_proposed_actions(json.dumps({"action": "create_ticket"})) is None


def test_unrecognized_action_type_is_rejected() -> None:
    raw = json.dumps([{"action": "delete_everything", "rationale": "x"}])
    assert _parse_proposed_actions(raw) is None


def test_action_missing_a_required_key_is_rejected() -> None:
    raw = json.dumps([{"action": "create_ticket", "title": "a", "rationale": "x"}])  # no body
    assert _parse_proposed_actions(raw) is None


def test_action_with_an_extra_key_is_rejected() -> None:
    raw = json.dumps(
        [
            {
                "action": "archive_draft_ticket",
                "item_id": "a",
                "rationale": "x",
                "confidence": 0.9,
            }
        ]
    )
    assert _parse_proposed_actions(raw) is None


def test_action_with_fields_from_a_different_action_type_is_rejected() -> None:
    raw = json.dumps([{"action": "archive_draft_ticket", "issue_url": "x", "rationale": "z"}])
    assert _parse_proposed_actions(raw) is None


def test_action_with_an_empty_field_is_rejected() -> None:
    raw = json.dumps([{"action": "archive_draft_ticket", "item_id": "", "rationale": "x"}])
    assert _parse_proposed_actions(raw) is None


def test_action_with_an_oversized_short_field_is_rejected() -> None:
    raw = json.dumps([{"action": "archive_draft_ticket", "item_id": "x" * 201, "rationale": "y"}])
    assert _parse_proposed_actions(raw) is None


def test_action_with_a_non_string_field_is_rejected() -> None:
    raw = json.dumps([{"action": "archive_draft_ticket", "item_id": 5, "rationale": "x"}])
    assert _parse_proposed_actions(raw) is None


def test_a_non_object_array_item_is_rejected() -> None:
    assert _parse_proposed_actions(json.dumps(["not an object"])) is None


def test_too_many_proposed_actions_is_rejected() -> None:
    raw = _actions_json(
        [{"action": "archive_draft_ticket", "item_id": "a", "rationale": "x"} for _ in range(11)]
    )
    assert _parse_proposed_actions(raw) is None
