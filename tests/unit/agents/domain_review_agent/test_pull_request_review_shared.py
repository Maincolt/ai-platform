"""Tests for `_pull_request_review_shared` -- the REST-only
`GitHubPullRequestReviewClient` (`httpx.MockTransport`-based, same
pattern every prior autonomous role's client tests already use), shared
by both `frontend-specialist-agent` and `postgres-specialist-agent`
(ADR-0033).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from typing import Any

import httpx
import pytest

from ai_platform.agents._pull_request_review_shared import (
    GitHubPullRequestReviewClient,
    PullRequestSnapshot,
)
from ai_platform.agents.domain_review_agent.errors import (
    PullRequestFetchFailedError,
    ReviewActionFailedError,
)


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def _client(handler: Any, **overrides: Any) -> GitHubPullRequestReviewClient:
    defaults: dict[str, Any] = {
        "token": "ghp_test",
        "owner": "octocat",
        "repo": "repo",
        "transport": httpx.MockTransport(handler),
    }
    defaults.update(overrides)
    return GitHubPullRequestReviewClient(**defaults)


def _routed_handler(routes: dict[str, Any]) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/pulls") and request.method == "GET":
            return routes["list_pulls"](request)
        if path.endswith("/reviews"):
            return routes["request_changes"](request)
        if path.endswith("/files"):
            return routes["files"](request)
        raise AssertionError(f"unexpected request: {request.method} {path}")

    return handler


# --- constructor validation ---------------------------------------------


def test_token_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="token"):
        GitHubPullRequestReviewClient(token="", owner="octocat", repo="repo")


def test_repo_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="repo"):
        GitHubPullRequestReviewClient(token="ghp_test", owner="octocat", repo="")


# --- fetch_open_pull_requests --------------------------------------------


def test_fetch_open_pull_requests_captures_changed_file_paths() -> None:
    def list_pulls(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=[{"number": 1, "title": "Add a Vue component"}])

    def files(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200, json=[{"filename": "frontend/dashboard/src/App.vue"}, {"filename": "README.md"}]
        )

    handler = _routed_handler({"list_pulls": list_pulls, "files": files})
    client = _client(handler)

    snapshots = _run(client.fetch_open_pull_requests())

    assert snapshots == (
        PullRequestSnapshot(
            number=1,
            title="Add a Vue component",
            changed_file_paths=("frontend/dashboard/src/App.vue", "README.md"),
        ),
    )


def test_fetch_open_pull_requests_raises_on_non_200_http_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(401, text="Bad credentials")

    client = _client(handler)

    with pytest.raises(PullRequestFetchFailedError, match="401"):
        _run(client.fetch_open_pull_requests())


def test_fetch_open_pull_requests_skips_malformed_entries() -> None:
    def list_pulls(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=[{"number": "not-an-int", "title": "x"}])

    client = _client(list_pulls)

    snapshots = _run(client.fetch_open_pull_requests())

    assert snapshots == ()


def test_files_fetch_raises_on_non_200_http_status() -> None:
    def list_pulls(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=[{"number": 1, "title": "x"}])

    def files(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(500, text="Internal Server Error")

    handler = _routed_handler({"list_pulls": list_pulls, "files": files})
    client = _client(handler)

    with pytest.raises(PullRequestFetchFailedError, match="500"):
        _run(client.fetch_open_pull_requests())


# --- request_changes -----------------------------------------------------


def test_request_changes_posts_the_review() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": 1})

    client = _client(handler)

    _run(client.request_changes(pull_number=42, body="Please use the Composition API here."))

    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.github.com/repos/octocat/repo/pulls/42/reviews"
    assert captured["body"] == {
        "event": "REQUEST_CHANGES",
        "body": "Please use the Composition API here.",
    }


def test_request_changes_raises_on_non_200_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(404, text="Not Found")

    client = _client(handler)

    with pytest.raises(ReviewActionFailedError, match="404"):
        _run(client.request_changes(pull_number=1, body="x"))


def test_request_changes_raises_on_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = _client(handler)

    with pytest.raises(ReviewActionFailedError, match="request to GitHub failed"):
        _run(client.request_changes(pull_number=1, body="x"))
