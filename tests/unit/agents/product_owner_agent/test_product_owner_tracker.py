"""Tests for `product_owner_agent.tracker` -- the pure helpers, the read
side (same `httpx.MockTransport` pattern as `scrum_master_agent`), and
the six ADR-0030 Decision 1 write mutations.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from typing import Any

import httpx
import pytest

from ai_platform.agents.product_owner_agent.errors import (
    BacklogFetchFailedError,
    TrackerActionFailedError,
)
from ai_platform.agents.product_owner_agent.tracker import (
    GitHubProjectsBacklogClient,
    ProjectBoardSnapshot,
    _extract_status,  # pyright: ignore[reportPrivateUsage]
    _truncate,  # pyright: ignore[reportPrivateUsage]
)


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def _client(handler: Any, **overrides: Any) -> GitHubProjectsBacklogClient:
    defaults: dict[str, Any] = {
        "token": "ghp_test",
        "owner": "octocat",
        "project_number": 1,
        "transport": httpx.MockTransport(handler),
    }
    defaults.update(overrides)
    return GitHubProjectsBacklogClient(**defaults)


def _routed_handler(routes: dict[str, Any]) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        if not request.url.path.endswith("/graphql"):
            return routes["rest"](request)
        body = json.loads(request.content)
        query = body.get("query", "")
        if "addProjectV2DraftIssue" in query:
            return routes["create_mutation"](request)
        if "archiveProjectV2Item" in query:
            return routes["archive_mutation"](request)
        if "updateProjectV2ItemPosition" in query:
            return routes["reprioritize_mutation"](request)
        if "updateProjectV2ItemFieldValue" in query:
            return routes["set_status_mutation"](request)
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
                                {"id": "opt_backlog", "name": "Backlog"},
                                {"id": "opt_todo", "name": "Todo"},
                            ],
                        },
                    }
                }
            }
        },
    )


def _unreachable_rest_handler(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"GitHub must not be called for a malformed URL, got {request.url}")


# --- pure helpers ------------------------------------------------------


def test_truncate_leaves_short_text_unchanged() -> None:
    assert _truncate("hello", 10) == "hello"


def test_extract_status_finds_the_status_field() -> None:
    field_values = {
        "nodes": [
            {
                "__typename": "ProjectV2ItemFieldSingleSelectValue",
                "name": "Backlog",
                "field": {"name": "Status"},
            }
        ]
    }
    assert _extract_status(field_values) == "Backlog"


# --- constructor validation ---------------------------------------------


def test_token_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="token"):
        GitHubProjectsBacklogClient(token="", owner="octocat", project_number=1)


def test_project_number_must_be_positive() -> None:
    with pytest.raises(ValueError, match="project_number"):
        GitHubProjectsBacklogClient(token="ghp_test", owner="octocat", project_number=0)


# --- fetch() -----------------------------------------------------------


def test_fetch_captures_each_items_node_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "user": {
                        "projectV2": {
                            "title": "Backlog",
                            "items": {
                                "nodes": [
                                    {
                                        "id": "PVTI_item1",
                                        "content": {
                                            "__typename": "Issue",
                                            "title": "Write docs",
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


def test_fetch_raises_on_non_200_http_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Bad credentials")

    client = _client(handler)

    with pytest.raises(BacklogFetchFailedError, match="401"):
        _run(client.fetch())


# --- create_ticket -------------------------------------------------------


def test_create_ticket_dispatches_the_mutation() -> None:
    captured: dict[str, Any] = {}

    def create_mutation(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"data": {"addProjectV2DraftIssue": {"projectItem": {"id": "x"}}}}
        )

    handler = _routed_handler({"metadata": _metadata_handler, "create_mutation": create_mutation})
    client = _client(handler)

    _run(client.create_ticket(title="Write onboarding docs", body="Nobody has done this yet"))

    assert captured["body"]["variables"] == {
        "projectId": "PVT_project1",
        "title": "Write onboarding docs",
        "body": "Nobody has done this yet",
    }


def test_create_ticket_raises_on_missing_expected_data() -> None:
    def empty_data_mutation(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"data": {}})

    handler = _routed_handler(
        {"metadata": _metadata_handler, "create_mutation": empty_data_mutation}
    )
    client = _client(handler)

    with pytest.raises(TrackerActionFailedError):
        _run(client.create_ticket(title="x", body="y"))


# --- edit_ticket -------------------------------------------------------------


def test_edit_ticket_patches_the_correct_repo_issue() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": 1})

    client = _client(handler)

    _run(
        client.edit_ticket(
            issue_url="https://github.com/octocat/repo/issues/42",
            title="Updated title",
            body="Updated body",
        )
    )

    assert captured["method"] == "PATCH"
    assert captured["url"] == "https://api.github.com/repos/octocat/repo/issues/42"
    assert captured["body"] == {"title": "Updated title", "body": "Updated body"}


def test_edit_ticket_rejects_a_draft_item_url() -> None:
    client = _client(_unreachable_rest_handler)

    with pytest.raises(TrackerActionFailedError, match="not a recognized issue"):
        _run(client.edit_ticket(issue_url="", title="x", body="y"))


def test_edit_ticket_raises_on_non_200_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Not Found")

    client = _client(handler)

    with pytest.raises(TrackerActionFailedError, match="404"):
        _run(
            client.edit_ticket(
                issue_url="https://github.com/octocat/repo/issues/1", title="x", body="y"
            )
        )


# --- close_ticket ------------------------------------------------------------


def test_close_ticket_patches_the_correct_repo_issue() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": 1, "state": "closed"})

    client = _client(handler)

    _run(client.close_ticket(issue_url="https://github.com/octocat/repo/issues/42"))

    assert captured["method"] == "PATCH"
    assert captured["body"] == {"state": "closed"}


def test_close_ticket_rejects_a_draft_item_url() -> None:
    client = _client(_unreachable_rest_handler)

    with pytest.raises(TrackerActionFailedError, match="not a recognized issue"):
        _run(client.close_ticket(issue_url=""))


# --- archive_draft_ticket -----------------------------------------------------


def test_archive_draft_ticket_dispatches_the_mutation() -> None:
    captured: dict[str, Any] = {}

    def archive_mutation(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": {"archiveProjectV2Item": {"item": {"id": "x"}}}})

    handler = _routed_handler({"metadata": _metadata_handler, "archive_mutation": archive_mutation})
    client = _client(handler)

    _run(client.archive_draft_ticket(item_id="PVTI_item1"))

    assert captured["body"]["variables"] == {"projectId": "PVT_project1", "itemId": "PVTI_item1"}


def test_archive_draft_ticket_raises_on_a_failed_mutation_response() -> None:
    def failed_mutation(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"errors": ["boom"]})

    handler = _routed_handler({"metadata": _metadata_handler, "archive_mutation": failed_mutation})
    client = _client(handler)

    with pytest.raises(TrackerActionFailedError):
        _run(client.archive_draft_ticket(item_id="PVTI_item1"))


# --- reprioritize --------------------------------------------------------------


def test_reprioritize_dispatches_the_mutation_with_after_id() -> None:
    captured: dict[str, Any] = {}

    def reprioritize_mutation(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"data": {"updateProjectV2ItemPosition": {"items": {"totalCount": 1}}}}
        )

    handler = _routed_handler(
        {"metadata": _metadata_handler, "reprioritize_mutation": reprioritize_mutation}
    )
    client = _client(handler)

    _run(client.reprioritize(item_id="PVTI_item1", after_item_id="PVTI_item0"))

    assert captured["body"]["variables"] == {
        "projectId": "PVT_project1",
        "itemId": "PVTI_item1",
        "afterId": "PVTI_item0",
    }


def test_reprioritize_with_no_after_id_sends_null() -> None:
    captured: dict[str, Any] = {}

    def reprioritize_mutation(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"data": {"updateProjectV2ItemPosition": {"items": {"totalCount": 1}}}}
        )

    handler = _routed_handler(
        {"metadata": _metadata_handler, "reprioritize_mutation": reprioritize_mutation}
    )
    client = _client(handler)

    _run(client.reprioritize(item_id="PVTI_item1", after_item_id=None))

    assert captured["body"]["variables"]["afterId"] is None


# --- adjust_sprint_scope -------------------------------------------------------


def test_adjust_sprint_scope_dispatches_the_mutation_with_the_resolved_option_id() -> None:
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

    _run(client.adjust_sprint_scope(item_id="PVTI_item1", status_name="Backlog"))

    assert captured["body"]["variables"] == {
        "projectId": "PVT_project1",
        "itemId": "PVTI_item1",
        "fieldId": "PVTSSF_status",
        "optionId": "opt_backlog",
    }


def test_adjust_sprint_scope_rejects_an_unknown_status_name() -> None:
    handler = _routed_handler({"metadata": _metadata_handler})
    client = _client(handler)

    with pytest.raises(TrackerActionFailedError, match="not a valid Status option"):
        _run(client.adjust_sprint_scope(item_id="PVTI_item1", status_name="Nonexistent"))
