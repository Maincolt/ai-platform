"""Tests for `domain_review_agent.agent._parse_proposed_actions` and
`_pull_request_in_domain` -- the strict single-action parser and the
path-prefix domain filter (ADR-0033), which is what actually
distinguishes `frontend-specialist-agent` from
`postgres-specialist-agent` despite sharing all their other code.
"""

import json

from ai_platform.agents._pull_request_review_shared import PullRequestSnapshot
from ai_platform.agents.domain_review_agent.agent import (
    ProposedAction,
    _parse_proposed_actions,  # pyright: ignore[reportPrivateUsage]
    _pull_request_in_domain,  # pyright: ignore[reportPrivateUsage]
)


def _actions_json(actions: list[dict[str, object]]) -> str:
    return json.dumps(actions)


# --- _pull_request_in_domain ----------------------------------------------


def test_pull_request_in_domain_matches_a_prefix() -> None:
    pr = PullRequestSnapshot(
        number=1, title="x", changed_file_paths=("frontend/dashboard/src/App.vue",)
    )
    assert _pull_request_in_domain(pr, path_prefixes=("frontend/",)) is True


def test_pull_request_not_in_domain_when_no_path_matches() -> None:
    pr = PullRequestSnapshot(number=1, title="x", changed_file_paths=("README.md",))
    assert _pull_request_in_domain(pr, path_prefixes=("frontend/",)) is False


def test_pull_request_in_domain_matches_any_of_several_prefixes() -> None:
    pr = PullRequestSnapshot(
        number=1, title="x", changed_file_paths=("infrastructure/migrations/0010_x.sql",)
    )
    assert (
        _pull_request_in_domain(
            pr,
            path_prefixes=(
                "infrastructure/migrations/",
                "src/ai_platform/adapters/persistence/",
            ),
        )
        is True
    )


def test_pull_request_not_in_domain_with_no_changed_files() -> None:
    pr = PullRequestSnapshot(number=1, title="x", changed_file_paths=())
    assert _pull_request_in_domain(pr, path_prefixes=("frontend/",)) is False


def test_pull_request_in_domain_requires_a_true_prefix_not_a_substring() -> None:
    """A path containing the domain string mid-name must not match --
    only an actual path prefix counts."""
    pr = PullRequestSnapshot(number=1, title="x", changed_file_paths=("not_frontend/x.py",))
    assert _pull_request_in_domain(pr, path_prefixes=("frontend/",)) is False


# --- _parse_proposed_actions -----------------------------------------------


def test_empty_array_is_a_valid_empty_proposal() -> None:
    assert _parse_proposed_actions("[]") == []


def test_well_formed_action_parses_correctly() -> None:
    raw = _actions_json(
        [
            {
                "action": "request_changes",
                "pull_number": "42",
                "body": "Please use the Composition API here.",
                "rationale": "Options API is inconsistent with the rest of the codebase.",
            }
        ]
    )

    parsed = _parse_proposed_actions(raw)

    assert parsed == [
        ProposedAction(
            pull_number=42,
            body="Please use the Composition API here.",
            rationale="Options API is inconsistent with the rest of the codebase.",
        )
    ]


def test_multiple_actions_in_one_batch_all_parse() -> None:
    raw = _actions_json(
        [
            {"action": "request_changes", "pull_number": "1", "body": "a", "rationale": "x"},
            {"action": "request_changes", "pull_number": "2", "body": "b", "rationale": "y"},
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
    assert _parse_proposed_actions(json.dumps({"action": "request_changes"})) is None


def test_wrong_action_value_is_rejected() -> None:
    raw = json.dumps([{"action": "merge", "pull_number": "1", "body": "x", "rationale": "y"}])
    assert _parse_proposed_actions(raw) is None


def test_action_missing_a_required_key_is_rejected() -> None:
    raw = json.dumps([{"action": "request_changes", "pull_number": "1", "rationale": "x"}])
    assert _parse_proposed_actions(raw) is None


def test_action_with_an_extra_key_is_rejected() -> None:
    raw = json.dumps(
        [
            {
                "action": "request_changes",
                "pull_number": "1",
                "body": "x",
                "rationale": "y",
                "confidence": 0.9,
            }
        ]
    )
    assert _parse_proposed_actions(raw) is None


def test_pull_number_must_be_digits_only() -> None:
    raw = json.dumps(
        [{"action": "request_changes", "pull_number": "abc", "body": "x", "rationale": "y"}]
    )
    assert _parse_proposed_actions(raw) is None


def test_pull_number_as_a_json_int_is_rejected() -> None:
    raw = json.dumps(
        [{"action": "request_changes", "pull_number": 1, "body": "x", "rationale": "y"}]
    )
    assert _parse_proposed_actions(raw) is None


def test_a_non_object_array_item_is_rejected() -> None:
    assert _parse_proposed_actions(json.dumps(["not an object"])) is None


def test_too_many_proposed_actions_is_rejected() -> None:
    raw = _actions_json(
        [
            {"action": "request_changes", "pull_number": "1", "body": "x", "rationale": "y"}
            for _ in range(11)
        ]
    )
    assert _parse_proposed_actions(raw) is None
