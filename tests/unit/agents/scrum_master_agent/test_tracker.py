"""Tests for `scrum_master_agent.tracker` -- the pure helpers, the read
side (mirroring `scrum_status_agent.board`'s `httpx.MockTransport`
pattern), and the three ADR-0028 Decision 1 write mutations.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from typing import Any

import httpx
import pytest

from ai_platform.agents.scrum_master_agent.errors import (
    ProjectBoardFetchFailedError,
    TrackerActionFailedError,
)
from ai_platform.agents.scrum_master_agent.tracker import (
    GitHubProjectsTrackerClient,
    ProjectBoardSnapshot,
    _extract_status,  # pyright: ignore[reportPrivateUsage]
    _truncate,  # pyright: ignore[reportPrivateUsage]
)


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def _client(handler: Any, **overrides: Any) -> GitHubProjectsTrackerClient:
    defaults: dict[str, Any] = {
        "token": "ghp_test",
        "owner": "octocat",
        "project_number": 1,
        "transport": httpx.MockTransport(handler),
    }
    defaults.update(overrides)
    return GitHubProjectsTrackerClient(**defaults)


def _routed_handler(routes: dict[str, Any]) -> Any:
    """Dispatch by GraphQL operation name (parsed from the request body's
    `query` string) or REST path, matching the tracker's three distinct
    call shapes without needing three separate transports."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/comments"):
            return routes["comment"](request)
        body = json.loads(request.content)
        query = body.get("query", "")
        if "updateProjectV2ItemFieldValue" in query:
            return routes["set_status_mutation"](request)
        if "addProjectV2DraftIssue" in query:
            return routes["create_draft_mutation"](request)
        if 'field(name: "Status")' in query:
            return routes["metadata"](request)
        return routes["board"](request)

    return handler


def _metadata_handler(request: httpx.Request) -> httpx.Response:
    del request
    return _metadata_response()


def _metadata_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": {
                "user": {
                    "projectV2": {
                        "id": "PVT_project1",
                        "field": {
                            "id": "PVTSSF_status",
                            "options": [
                                {"id": "opt_todo", "name": "Todo"},
                                {"id": "opt_in_progress", "name": "In Progress"},
                                {"id": "opt_done", "name": "Done"},
                            ],
                        },
                    }
                }
            }
        },
    )


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


# --- constructor validation ---------------------------------------------


def test_token_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="token"):
        GitHubProjectsTrackerClient(token="", owner="octocat", project_number=1)


def test_project_number_must_be_positive() -> None:
    with pytest.raises(ValueError, match="project_number"):
        GitHubProjectsTrackerClient(token="ghp_test", owner="octocat", project_number=0)


# --- fetch(): success and item_id -----------------------------------------


def test_fetch_captures_each_items_node_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "user": {
                        "projectV2": {
                            "title": "Sprint 12",
                            "items": {
                                "nodes": [
                                    {
                                        "id": "PVTI_item1",
                                        "content": {
                                            "__typename": "Issue",
                                            "title": "Fix bug",
                                            "url": "https://github.com/octocat/repo/issues/1",
                                        },
                                        "fieldValues": {"nodes": []},
                                    }
                                ]
                            },
                        }
                    }
                }
            },
        )

    client = _client(handler)

    snapshot = _run(client.fetch())

    assert isinstance(snapshot, ProjectBoardSnapshot)
    assert snapshot.items[0].item_id == "PVTI_item1"
    assert snapshot.items[0].title == "Fix bug"


def test_fetch_skips_items_with_no_node_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "user": {
                        "projectV2": {
                            "title": "T",
                            "items": {
                                "nodes": [
                                    {
                                        "id": None,
                                        "content": {
                                            "__typename": "Issue",
                                            "title": "x",
                                            "url": "y",
                                        },
                                        "fieldValues": {},
                                    }
                                ]
                            },
                        }
                    }
                }
            },
        )

    client = _client(handler)

    snapshot = _run(client.fetch())

    assert snapshot.items == ()


def test_fetch_raises_on_non_200_http_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Bad credentials")

    client = _client(handler)

    with pytest.raises(ProjectBoardFetchFailedError, match="401"):
        _run(client.fetch())


# --- set_status ------------------------------------------------------------


def test_set_status_dispatches_the_mutation_with_the_resolved_option_id() -> None:
    captured: dict[str, Any] = {}

    def set_status_mutation(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"data": {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "x"}}}}
        )

    handler = _routed_handler(
        {"metadata": _metadata_handler, "set_status_mutation": set_status_mutation}
    )
    client = _client(handler)

    _run(client.set_status(item_id="PVTI_item1", status_name="In Progress"))

    variables = captured["body"]["variables"]
    assert variables == {
        "projectId": "PVT_project1",
        "itemId": "PVTI_item1",
        "fieldId": "PVTSSF_status",
        "optionId": "opt_in_progress",
    }


def test_set_status_caches_metadata_across_calls() -> None:
    metadata_calls = 0

    def metadata(request: httpx.Request) -> httpx.Response:
        nonlocal metadata_calls
        metadata_calls += 1
        return _metadata_response()

    def set_status_mutation(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "x"}}}}
        )

    handler = _routed_handler({"metadata": metadata, "set_status_mutation": set_status_mutation})
    client = _client(handler)

    _run(client.set_status(item_id="PVTI_item1", status_name="Todo"))
    _run(client.set_status(item_id="PVTI_item2", status_name="Done"))

    assert metadata_calls == 1


def test_set_status_rejects_an_unknown_status_name() -> None:
    handler = _routed_handler({"metadata": _metadata_handler})
    client = _client(handler)

    with pytest.raises(TrackerActionFailedError, match="not a valid Status option"):
        _run(client.set_status(item_id="PVTI_item1", status_name="Nonexistent"))


def test_set_status_raises_on_a_failed_mutation_response() -> None:
    def failed_mutation(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"errors": ["boom"]})

    handler = _routed_handler(
        {"metadata": _metadata_handler, "set_status_mutation": failed_mutation}
    )
    client = _client(handler)

    with pytest.raises(TrackerActionFailedError):
        _run(client.set_status(item_id="PVTI_item1", status_name="Todo"))


# --- create_draft_item -------------------------------------------------------


def test_create_draft_item_dispatches_the_mutation() -> None:
    captured: dict[str, Any] = {}

    def create_draft_mutation(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"data": {"addProjectV2DraftIssue": {"projectItem": {"id": "x"}}}}
        )

    handler = _routed_handler(
        {"metadata": _metadata_handler, "create_draft_mutation": create_draft_mutation}
    )
    client = _client(handler)

    _run(client.create_draft_item(title="Write docs", body="Explain the thing"))

    variables = captured["body"]["variables"]
    assert variables == {
        "projectId": "PVT_project1",
        "title": "Write docs",
        "body": "Explain the thing",
    }


def test_create_draft_item_raises_on_missing_expected_data() -> None:
    def empty_data_mutation(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"data": {}})

    handler = _routed_handler(
        {"metadata": _metadata_handler, "create_draft_mutation": empty_data_mutation}
    )
    client = _client(handler)

    with pytest.raises(TrackerActionFailedError):
        _run(client.create_draft_item(title="x", body="y"))


# --- add_comment -------------------------------------------------------------


def test_add_comment_posts_to_the_correct_repo_issue() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"id": 1})

    client = _client(handler)

    _run(
        client.add_comment(issue_url="https://github.com/octocat/repo/issues/42", body="Looks good")
    )

    assert captured["url"] == "https://api.github.com/repos/octocat/repo/issues/42/comments"
    assert captured["body"] == {"body": "Looks good"}


def test_add_comment_works_against_a_pull_request_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"id": 1})

    client = _client(handler)

    _run(client.add_comment(issue_url="https://github.com/octocat/repo/pull/7", body="x"))


def _unreachable_comment_handler(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"GitHub must not be called for a malformed URL, got {request.url}")


def test_add_comment_rejects_a_malformed_url() -> None:
    client = _client(_unreachable_comment_handler)

    with pytest.raises(TrackerActionFailedError, match="not a recognized issue"):
        _run(client.add_comment(issue_url="", body="x"))


def test_add_comment_rejects_a_draft_item_url() -> None:
    """Draft items have an empty `url` (`scrum_master_agent.tracker
    .BoardItem.url`) -- there is no issue to comment on."""
    client = _client(_unreachable_comment_handler)

    with pytest.raises(TrackerActionFailedError, match="not a recognized issue"):
        _run(client.add_comment(issue_url="", body="x"))


def test_add_comment_raises_on_non_201_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Not Found")

    client = _client(handler)

    with pytest.raises(TrackerActionFailedError, match="404"):
        _run(client.add_comment(issue_url="https://github.com/octocat/repo/issues/1", body="x"))


def test_add_comment_raises_on_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = _client(handler)

    with pytest.raises(TrackerActionFailedError, match="request to GitHub failed"):
        _run(client.add_comment(issue_url="https://github.com/octocat/repo/issues/1", body="x"))
