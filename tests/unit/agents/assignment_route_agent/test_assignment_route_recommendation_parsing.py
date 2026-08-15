"""Tests for `assignment_route_agent.agent._parse_recommendations` --
turning the AI Router's raw text response into a structured, schema-valid
recommendation list, or `None` (never a partial/best-effort result) on any
shape mismatch. Recommendations differ from every findings-list
capability's shape: keys are `capability`/`rationale` instead of a
locator/summary/severity triple, `capability` must be one of the six
eligible team capabilities, and duplicate capability entries are
rejected (a recommendation list, not an evidence list, so naming the same
capability twice is meaningless).
"""

import json

from ai_platform.agents.assignment_route_agent.agent import (
    _parse_recommendations,  # pyright: ignore[reportPrivateUsage]
)


def _recommendations_json(items: list[dict[str, object]]) -> str:
    return json.dumps(items)


def test_empty_array_is_a_valid_empty_recommendation_list() -> None:
    assert _parse_recommendations("[]") == []


def test_well_formed_recommendations_parse_correctly() -> None:
    raw = _recommendations_json(
        [
            {
                "capability": "architecture.review",
                "rationale": "This proposes a new architectural boundary.",
            },
            {
                "capability": "technical.review",
                "rationale": "It also includes a concrete schema change.",
            },
        ]
    )

    recommendations = _parse_recommendations(raw)

    assert recommendations == [
        {
            "capability": "architecture.review",
            "rationale": "This proposes a new architectural boundary.",
        },
        {
            "capability": "technical.review",
            "rationale": "It also includes a concrete schema change.",
        },
    ]


def test_response_wrapped_in_a_json_markdown_fence_still_parses() -> None:
    raw = "```json\n" + _recommendations_json([]) + "\n```"
    assert _parse_recommendations(raw) == []


def test_response_wrapped_in_a_plain_markdown_fence_still_parses() -> None:
    raw = "```\n" + _recommendations_json([]) + "\n```"
    assert _parse_recommendations(raw) == []


def test_malformed_content_inside_a_markdown_fence_is_still_rejected() -> None:
    raw = "```json\nnot valid json\n```"
    assert _parse_recommendations(raw) is None


def test_non_json_text_is_rejected() -> None:
    assert _parse_recommendations("here is my routing decision...") is None


def test_json_object_instead_of_array_is_rejected() -> None:
    assert _parse_recommendations(json.dumps({"capability": "code.review"})) is None


def test_recommendation_missing_a_required_key_is_rejected() -> None:
    raw = json.dumps([{"capability": "code.review"}])  # no rationale
    assert _parse_recommendations(raw) is None


def test_recommendation_with_an_extra_key_is_rejected() -> None:
    raw = json.dumps([{"capability": "code.review", "rationale": "x", "confidence": 0.9}])
    assert _parse_recommendations(raw) is None


def test_recommendation_with_a_technical_review_component_key_is_rejected() -> None:
    raw = json.dumps([{"component": "users table", "rationale": "x"}])
    assert _parse_recommendations(raw) is None


def test_recommendation_naming_an_ineligible_capability_is_rejected() -> None:
    raw = json.dumps([{"capability": "text.word-count", "rationale": "x"}])
    assert _parse_recommendations(raw) is None


def test_recommendation_naming_itself_is_rejected() -> None:
    raw = json.dumps([{"capability": "assignment.route", "rationale": "x"}])
    assert _parse_recommendations(raw) is None


def test_recommendation_naming_an_unknown_capability_is_rejected() -> None:
    raw = json.dumps([{"capability": "not.a.real.capability", "rationale": "x"}])
    assert _parse_recommendations(raw) is None


def test_recommendation_with_an_empty_rationale_is_rejected() -> None:
    raw = json.dumps([{"capability": "code.review", "rationale": ""}])
    assert _parse_recommendations(raw) is None


def test_recommendation_with_an_oversized_rationale_is_rejected() -> None:
    raw = json.dumps([{"capability": "code.review", "rationale": "x" * 2001}])
    assert _parse_recommendations(raw) is None


def test_a_non_object_array_item_is_rejected() -> None:
    raw = json.dumps(["not an object"])
    assert _parse_recommendations(raw) is None


def test_duplicate_capability_entries_are_rejected() -> None:
    raw = json.dumps(
        [
            {"capability": "code.review", "rationale": "first mention"},
            {"capability": "code.review", "rationale": "second mention"},
        ]
    )
    assert _parse_recommendations(raw) is None


def test_too_many_recommendations_is_rejected() -> None:
    raw = json.dumps(
        [
            {"capability": name, "rationale": "x"}
            for name in [
                "text.summarize",
                "code.review",
                "ui.review",
                "architecture.review",
                "data.analysis",
                "technical.review",
                "code.review",
            ]
        ]
    )
    # Seven items exceeds the six-item cap even before the duplicate check.
    assert _parse_recommendations(raw) is None


def test_all_six_eligible_capabilities_can_be_recommended_together() -> None:
    raw = json.dumps(
        [
            {"capability": name, "rationale": "relevant"}
            for name in [
                "text.summarize",
                "code.review",
                "ui.review",
                "architecture.review",
                "data.analysis",
                "technical.review",
            ]
        ]
    )
    recommendations = _parse_recommendations(raw)
    assert recommendations is not None
    assert len(recommendations) == 6
