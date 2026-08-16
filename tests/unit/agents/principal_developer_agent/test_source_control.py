"""Tests for `principal_developer_agent.source_control` -- the REST-only
`GitHubSourceControlClient` (`httpx.MockTransport`-based, same pattern
every prior autonomous role's tracker tests already use), including the
`merge()` TOCTOU re-check (ADR-0031 Decision 1).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from typing import Any

import httpx
import pytest

from ai_platform.agents.principal_developer_agent.errors import (
    PullRequestFetchFailedError,
    SourceControlActionFailedError,
)
from ai_platform.agents.principal_developer_agent.source_control import (
    GitHubSourceControlClient,
    PullRequestSnapshot,
)


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def _client(handler: Any, **overrides: Any) -> GitHubSourceControlClient:
    defaults: dict[str, Any] = {
        "token": "ghp_test",
        "owner": "octocat",
        "repo": "repo",
        "transport": httpx.MockTransport(handler),
    }
    defaults.update(overrides)
    return GitHubSourceControlClient(**defaults)


def _routed_handler(routes: dict[str, Any]) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/pulls") and request.method == "GET":
            return routes["list_pulls"](request)
        if path.endswith("/merge"):
            return routes["merge"](request)
        if path.endswith("/reviews"):
            return routes["request_changes"](request)
        if path.endswith("/pulls/1") or "/pulls/" in path:
            return routes["pull_detail"](request)
        raise AssertionError(f"unexpected request: {request.method} {path}")

    return handler


# --- constructor validation ---------------------------------------------


def test_token_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="token"):
        GitHubSourceControlClient(token="", owner="octocat", repo="repo")


def test_repo_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="repo"):
        GitHubSourceControlClient(token="ghp_test", owner="octocat", repo="")


# --- fetch_open_pull_requests --------------------------------------------


def test_fetch_open_pull_requests_captures_mergeable_state() -> None:
    def list_pulls(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=[{"number": 1, "title": "Fix bug"}])

    def pull_detail(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"number": 1, "mergeable_state": "clean"})

    handler = _routed_handler({"list_pulls": list_pulls, "pull_detail": pull_detail})
    client = _client(handler)

    snapshots = _run(client.fetch_open_pull_requests())

    assert snapshots == (PullRequestSnapshot(number=1, title="Fix bug", mergeable_state="clean"),)


def test_fetch_open_pull_requests_defaults_to_unknown_when_null() -> None:
    def list_pulls(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=[{"number": 1, "title": "Fix bug"}])

    def pull_detail(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"number": 1, "mergeable_state": None})

    handler = _routed_handler({"list_pulls": list_pulls, "pull_detail": pull_detail})
    client = _client(handler)

    snapshots = _run(client.fetch_open_pull_requests())

    assert snapshots[0].mergeable_state == "unknown"


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


# --- request_changes -----------------------------------------------------


def test_request_changes_posts_the_review() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": 1})

    client = _client(handler)

    _run(client.request_changes(pull_number=42, body="Please add tests."))

    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.github.com/repos/octocat/repo/pulls/42/reviews"
    assert captured["body"] == {"event": "REQUEST_CHANGES", "body": "Please add tests."}


def test_request_changes_raises_on_non_200_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(404, text="Not Found")

    client = _client(handler)

    with pytest.raises(SourceControlActionFailedError, match="404"):
        _run(client.request_changes(pull_number=1, body="x"))


def test_request_changes_raises_on_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = _client(handler)

    with pytest.raises(SourceControlActionFailedError, match="request to GitHub failed"):
        _run(client.request_changes(pull_number=1, body="x"))


# --- merge -----------------------------------------------------------------


def test_merge_dispatches_when_still_clean() -> None:
    captured: dict[str, Any] = {}

    def pull_detail(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"mergeable_state": "clean"})

    def merge(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"merged": True})

    handler = _routed_handler({"pull_detail": pull_detail, "merge": merge})
    client = _client(handler)

    _run(client.merge(pull_number=42))

    assert captured["method"] == "PUT"
    assert captured["url"] == "https://api.github.com/repos/octocat/repo/pulls/42/merge"


def test_merge_refuses_when_no_longer_clean() -> None:
    def pull_detail(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"mergeable_state": "blocked"})

    def unreachable_merge(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"merge must not be called, got {request.url}")

    handler = _routed_handler({"pull_detail": pull_detail, "merge": unreachable_merge})
    client = _client(handler)

    with pytest.raises(SourceControlActionFailedError, match="no longer mergeable"):
        _run(client.merge(pull_number=42))


def test_merge_raises_on_non_200_merge_response() -> None:
    def pull_detail(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"mergeable_state": "clean"})

    def merge(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(405, text="Method Not Allowed")

    handler = _routed_handler({"pull_detail": pull_detail, "merge": merge})
    client = _client(handler)

    with pytest.raises(SourceControlActionFailedError, match="405"):
        _run(client.merge(pull_number=42))
