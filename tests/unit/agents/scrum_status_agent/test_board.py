"""Tests for `scrum_status_agent.board` -- both the pure helpers and the
full `GitHubProjectsBoardReader.fetch()` flow.

Unlike `ui_review_agent.capture.PlaywrightPageCapture` (which needs a real
headless browser and so only gets an opt-in `@pytest.mark.browser` test),
`GitHubProjectsBoardReader` accepts an injectable `httpx.BaseTransport`
(test-only seam, see `board.py`'s docstring), so its full HTTP/GraphQL
parsing flow can be exercised deterministically here with
`httpx.MockTransport` -- no real network call, no opt-in marker needed.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from typing import Any

import httpx
import pytest

from ai_platform.agents.scrum_status_agent.board import (
    GitHubProjectsBoardReader,
    ProjectBoardSnapshot,
    _extract_status,  # pyright: ignore[reportPrivateUsage]
    _truncate,  # pyright: ignore[reportPrivateUsage]
)
from ai_platform.agents.scrum_status_agent.errors import ProjectBoardFetchFailedError


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def _reader(handler: Any, **overrides: Any) -> GitHubProjectsBoardReader:
    defaults: dict[str, Any] = {
        "token": "ghp_test",
        "owner": "octocat",
        "project_number": 1,
        "transport": httpx.MockTransport(handler),
    }
    defaults.update(overrides)
    return GitHubProjectsBoardReader(**defaults)


def _success_response(*, title: str = "Sprint 12", items: list[dict[str, Any]] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "user": {
                        "projectV2": {
                            "title": title,
                            "items": {"nodes": items if items is not None else []},
                        }
                    }
                }
            },
        )

    return handler


# --- pure helpers ------------------------------------------------------


def test_truncate_leaves_short_text_unchanged() -> None:
    assert _truncate("hello", 10) == "hello"


def test_truncate_bounds_long_text() -> None:
    assert _truncate("x" * 20, 5) == "xxxxx"


def test_extract_status_finds_the_status_field() -> None:
    field_values = {
        "nodes": [
            {
                "__typename": "ProjectV2ItemFieldSingleSelectValue",
                "name": "In Progress",
                "field": {"name": "Status"},
            }
        ]
    }
    assert _extract_status(field_values) == "In Progress"


def test_extract_status_ignores_non_status_single_select_fields() -> None:
    field_values = {
        "nodes": [
            {
                "__typename": "ProjectV2ItemFieldSingleSelectValue",
                "name": "P1",
                "field": {"name": "Priority"},
            }
        ]
    }
    assert _extract_status(field_values) == ""


def test_extract_status_handles_missing_or_malformed_shape() -> None:
    assert _extract_status(None) == ""
    assert _extract_status({}) == ""
    assert _extract_status({"nodes": "not a list"}) == ""
    assert _extract_status({"nodes": ["not a dict"]}) == ""


# --- constructor validation ---------------------------------------------


def test_token_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="token"):
        GitHubProjectsBoardReader(token="", owner="octocat", project_number=1)


def test_owner_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="owner"):
        GitHubProjectsBoardReader(token="ghp_test", owner="", project_number=1)


def test_project_number_must_be_positive() -> None:
    with pytest.raises(ValueError, match="project_number"):
        GitHubProjectsBoardReader(token="ghp_test", owner="octocat", project_number=0)


def test_request_timeout_seconds_must_be_positive() -> None:
    with pytest.raises(ValueError, match="request_timeout_seconds"):
        GitHubProjectsBoardReader(
            token="ghp_test", owner="octocat", project_number=1, request_timeout_seconds=0
        )


# --- fetch(): success paths ----------------------------------------------


def test_fetch_returns_empty_snapshot_for_a_board_with_no_items() -> None:
    reader = _reader(_success_response(title="Sprint 12", items=[]))

    snapshot = _run(reader.fetch())

    assert snapshot == ProjectBoardSnapshot(title="Sprint 12", items=())


def test_fetch_parses_issue_items_with_status_and_url() -> None:
    items = [
        {
            "content": {
                "__typename": "Issue",
                "title": "Fix login bug",
                "number": 42,
                "state": "OPEN",
                "url": "https://github.com/octocat/repo/issues/42",
            },
            "fieldValues": {
                "nodes": [
                    {
                        "__typename": "ProjectV2ItemFieldSingleSelectValue",
                        "name": "In Progress",
                        "field": {"name": "Status"},
                    }
                ]
            },
        }
    ]
    reader = _reader(_success_response(items=items))

    snapshot = _run(reader.fetch())

    assert snapshot.title == "Sprint 12"
    assert len(snapshot.items) == 1
    item = snapshot.items[0]
    assert item.title == "Fix login bug"
    assert item.status == "In Progress"
    assert item.url == "https://github.com/octocat/repo/issues/42"


def test_fetch_handles_draft_issue_items_with_no_url() -> None:
    items = [{"content": {"__typename": "DraftIssue", "title": "Write docs"}, "fieldValues": {}}]
    reader = _reader(_success_response(items=items))

    snapshot = _run(reader.fetch())

    assert snapshot.items[0].title == "Write docs"
    assert snapshot.items[0].url == ""
    assert snapshot.items[0].status == ""


def test_fetch_skips_items_with_no_content() -> None:
    items: list[dict[str, Any]] = [
        {"content": None, "fieldValues": {}},
        {"content": {"__typename": "Issue", "title": "Real item", "url": "x"}, "fieldValues": {}},
    ]
    reader = _reader(_success_response(items=items))

    snapshot = _run(reader.fetch())

    assert len(snapshot.items) == 1
    assert snapshot.items[0].title == "Real item"


def test_fetch_truncates_oversized_title_and_status() -> None:
    items = [
        {
            "content": {"__typename": "Issue", "title": "x" * 500, "url": "y"},
            "fieldValues": {
                "nodes": [
                    {
                        "__typename": "ProjectV2ItemFieldSingleSelectValue",
                        "name": "z" * 200,
                        "field": {"name": "Status"},
                    }
                ]
            },
        }
    ]
    reader = _reader(_success_response(items=items))

    snapshot = _run(reader.fetch())

    assert len(snapshot.items[0].title) == 300
    assert len(snapshot.items[0].status) == 100


def test_fetch_sends_the_bearer_token_and_variables() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"data": {"user": {"projectV2": {"title": "T", "items": {"nodes": []}}}}}
        )

    reader = _reader(handler, token="ghp_secret", owner="octocat", project_number=7)
    _run(reader.fetch())

    assert captured["authorization"] == "Bearer ghp_secret"
    assert captured["body"]["variables"] == {"login": "octocat", "number": 7, "first": 100}


# --- fetch(): failure paths -----------------------------------------------


def test_fetch_raises_on_non_200_http_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Bad credentials")

    reader = _reader(handler)

    with pytest.raises(ProjectBoardFetchFailedError, match="401"):
        _run(reader.fetch())


def test_fetch_raises_on_a_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    reader = _reader(handler)

    with pytest.raises(ProjectBoardFetchFailedError, match="request to GitHub failed"):
        _run(reader.fetch())


def test_fetch_raises_on_invalid_json_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    reader = _reader(handler)

    with pytest.raises(ProjectBoardFetchFailedError, match="not valid JSON"):
        _run(reader.fetch())


def test_fetch_raises_on_a_graphql_errors_array() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": [{"message": "Could not resolve to a User"}]})

    reader = _reader(handler)

    with pytest.raises(ProjectBoardFetchFailedError, match="GraphQL errors"):
        _run(reader.fetch())


def test_fetch_raises_when_the_project_does_not_exist() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"user": {"projectV2": None}}})

    reader = _reader(handler, owner="octocat", project_number=99)

    with pytest.raises(ProjectBoardFetchFailedError, match="no projectV2 number 99"):
        _run(reader.fetch())


def test_fetch_raises_on_unexpected_response_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {}})

    reader = _reader(handler)

    with pytest.raises(ProjectBoardFetchFailedError, match="expected project shape"):
        _run(reader.fetch())


def test_fetch_raises_when_title_is_not_a_string() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": {"user": {"projectV2": {"title": 5, "items": {"nodes": []}}}}}
        )

    reader = _reader(handler)

    with pytest.raises(ProjectBoardFetchFailedError, match="title was not a string"):
        _run(reader.fetch())


def test_fetch_raises_when_items_list_is_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": {"user": {"projectV2": {"title": "T", "items": {}}}}}
        )

    reader = _reader(handler)

    with pytest.raises(ProjectBoardFetchFailedError, match="item list was not present"):
        _run(reader.fetch())
