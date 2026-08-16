"""Tests for `principal_developer_agent.agent._parse_proposed_actions` --
same strict discriminated-union parsing discipline as the other two
autonomous roles, extended with the `pull_number` digit-string
validator (the first field of this shape across all three roles)."""

import json

from ai_platform.agents.principal_developer_agent.agent import (
    ProposedAction,
    _parse_proposed_actions,  # pyright: ignore[reportPrivateUsage]
)


def _actions_json(actions: list[dict[str, object]]) -> str:
    return json.dumps(actions)


def test_empty_array_is_a_valid_empty_proposal() -> None:
    assert _parse_proposed_actions("[]") == []


def test_well_formed_request_changes_action_parses_correctly() -> None:
    raw = _actions_json(
        [
            {
                "action": "request_changes",
                "pull_number": "42",
                "body": "Please add tests.",
                "rationale": "Missing coverage for the new branch.",
            }
        ]
    )

    parsed = _parse_proposed_actions(raw)

    assert parsed == [
        ProposedAction(
            action="request_changes",
            pull_number=42,
            body="Please add tests.",
            rationale="Missing coverage for the new branch.",
        )
    ]


def test_well_formed_merge_action_parses_correctly() -> None:
    raw = _actions_json(
        [
            {
                "action": "merge",
                "pull_number": "7",
                "rationale": "All checks pass, no conflicts.",
            }
        ]
    )

    parsed = _parse_proposed_actions(raw)

    assert parsed == [
        ProposedAction(
            action="merge", pull_number=7, body=None, rationale="All checks pass, no conflicts."
        )
    ]


def test_multiple_actions_in_one_batch_all_parse() -> None:
    raw = _actions_json(
        [
            {"action": "merge", "pull_number": "1", "rationale": "x"},
            {
                "action": "request_changes",
                "pull_number": "2",
                "body": "b",
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
    assert _parse_proposed_actions("I reviewed the PRs and...") is None


def test_json_object_instead_of_array_is_rejected() -> None:
    assert _parse_proposed_actions(json.dumps({"action": "merge"})) is None


def test_unrecognized_action_type_is_rejected() -> None:
    raw = json.dumps([{"action": "force_push", "rationale": "x"}])
    assert _parse_proposed_actions(raw) is None


def test_action_missing_a_required_key_is_rejected() -> None:
    raw = json.dumps([{"action": "merge", "rationale": "x"}])  # no pull_number
    assert _parse_proposed_actions(raw) is None


def test_action_with_an_extra_key_is_rejected() -> None:
    raw = json.dumps([{"action": "merge", "pull_number": "1", "rationale": "x", "confidence": 0.9}])
    assert _parse_proposed_actions(raw) is None


def test_merge_with_request_changes_fields_is_rejected() -> None:
    raw = json.dumps([{"action": "merge", "pull_number": "1", "body": "x", "rationale": "y"}])
    assert _parse_proposed_actions(raw) is None


def test_pull_number_must_be_digits_only() -> None:
    raw = json.dumps([{"action": "merge", "pull_number": "abc", "rationale": "x"}])
    assert _parse_proposed_actions(raw) is None


def test_pull_number_must_not_be_zero() -> None:
    raw = json.dumps([{"action": "merge", "pull_number": "0", "rationale": "x"}])
    assert _parse_proposed_actions(raw) is None


def test_pull_number_must_not_have_leading_zero() -> None:
    raw = json.dumps([{"action": "merge", "pull_number": "007", "rationale": "x"}])
    assert _parse_proposed_actions(raw) is None


def test_pull_number_must_not_be_negative() -> None:
    raw = json.dumps([{"action": "merge", "pull_number": "-1", "rationale": "x"}])
    assert _parse_proposed_actions(raw) is None


def test_pull_number_must_not_exceed_the_bound() -> None:
    raw = json.dumps([{"action": "merge", "pull_number": "9999999", "rationale": "x"}])
    assert _parse_proposed_actions(raw) is None


def test_pull_number_as_a_json_int_is_rejected() -> None:
    """`pull_number` must be the string form, matching every other
    identifier field across all three autonomous roles -- a bare JSON
    integer is a shape mismatch, not a valid alternate encoding."""
    raw = json.dumps([{"action": "merge", "pull_number": 1, "rationale": "x"}])
    assert _parse_proposed_actions(raw) is None


def test_a_non_object_array_item_is_rejected() -> None:
    assert _parse_proposed_actions(json.dumps(["not an object"])) is None


def test_too_many_proposed_actions_is_rejected() -> None:
    raw = _actions_json(
        [{"action": "merge", "pull_number": "1", "rationale": "x"} for _ in range(11)]
    )
    assert _parse_proposed_actions(raw) is None
