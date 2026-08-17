"""The pull-request review boundary shared by every domain-scoped review
role (ADR-0033) -- `frontend-specialist-agent` and
`postgres-specialist-agent` today, and any future one built the same
way. Unlike every prior pair of autonomous roles, these two are
structurally identical (same one action, same dispatch logic, differing
only in role name, prompt wording, and which file paths define "their"
pull requests), so this module -- and `domain_review_agent.agent` --
is genuinely shared, not just the two pure helpers in
`_autonomous_shared.py`.

`PullRequestReviewPort` deliberately has **no `merge` method at all** --
ADR-0033 Decision 1's "no merge" boundary is structural, not a policy
`domain_review_agent` chooses to honor. REST-only, same shape as
`principal_developer_agent.source_control.GitHubSourceControlClient`
minus everything merge-related, extended with a changed-files fetch
that client didn't need.
"""

from dataclasses import dataclass
from typing import Protocol, cast

import httpx

from ai_platform.agents.domain_review_agent.errors import (
    PullRequestFetchFailedError,
    ReviewActionFailedError,
)

_MAX_PULL_REQUESTS = 50
_MAX_CHANGED_FILES = 100
_MAX_TITLE_LENGTH = 300
_MAX_PATH_LENGTH = 500
_GITHUB_REST_ROOT = "https://api.github.com"
_DEFAULT_REQUEST_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class PullRequestSnapshot:
    """One open pull request, bounded/truncated by whatever builds it."""

    number: int
    title: str
    changed_file_paths: tuple[str, ...]
    """Bounded to `_MAX_CHANGED_FILES` entries -- a domain filter only
    needs to know whether *any* changed path matches, not see every
    file in an unusually large PR."""


class PullRequestReviewPort(Protocol):
    async def fetch_open_pull_requests(self) -> tuple[PullRequestSnapshot, ...]:
        """Fetch the configured repository's open pull requests, each
        with its changed file paths. Raises `PullRequestFetchFailedError`
        on any failure -- never a partial result."""
        ...

    async def request_changes(self, *, pull_number: int, body: str) -> None:
        """Leave a "changes requested" review on a pull request. Raises
        `ReviewActionFailedError` on any failure."""
        ...


class GitHubPullRequestReviewClient:
    """The real, GitHub-REST-backed `PullRequestReviewPort`
    implementation. A fresh `httpx.AsyncClient` per call, matching every
    prior fetch-based capability's "no persistent state reused across
    calls" discipline."""

    def __init__(
        self,
        *,
        token: str,
        owner: str,
        repo: str,
        request_timeout_seconds: float = _DEFAULT_REQUEST_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """`transport` is a test-only seam (e.g. `httpx.MockTransport`) --
        production callers never pass it."""
        if not token:
            raise ValueError("token must be non-empty")
        if not owner:
            raise ValueError("owner must be non-empty")
        if not repo:
            raise ValueError("repo must be non-empty")
        if request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        self._token = token
        self._owner = owner
        self._repo = repo
        self._request_timeout_seconds = request_timeout_seconds
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._request_timeout_seconds, transport=self._transport)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
        }

    async def fetch_open_pull_requests(self) -> tuple[PullRequestSnapshot, ...]:
        url = f"{_GITHUB_REST_ROOT}/repos/{self._owner}/{self._repo}/pulls"
        try:
            async with self._client() as client:
                response = await client.get(
                    url,
                    params={"state": "open", "per_page": str(_MAX_PULL_REQUESTS)},
                    headers=self._headers(),
                )
        except httpx.HTTPError as error:
            raise PullRequestFetchFailedError(f"request to GitHub failed: {error}") from error
        if response.status_code != 200:
            raise PullRequestFetchFailedError(
                f"GitHub returned HTTP {response.status_code}: {response.text[:500]}"
            )
        try:
            parsed_body: object = response.json()
        except ValueError as error:
            raise PullRequestFetchFailedError(
                f"GitHub response was not valid JSON: {error}"
            ) from error
        if not isinstance(parsed_body, list):
            raise PullRequestFetchFailedError("GitHub response body was not a JSON array")
        summaries = cast(list[object], parsed_body)

        snapshots: list[PullRequestSnapshot] = []
        for summary in summaries[:_MAX_PULL_REQUESTS]:
            if not isinstance(summary, dict):
                continue
            summary = cast(dict[str, object], summary)
            number = summary.get("number")
            title = summary.get("title")
            if not isinstance(number, int) or not isinstance(title, str) or not title:
                continue
            changed_file_paths = await self._fetch_changed_file_paths(number)
            snapshots.append(
                PullRequestSnapshot(
                    number=number,
                    title=title[:_MAX_TITLE_LENGTH],
                    changed_file_paths=changed_file_paths,
                )
            )
        return tuple(snapshots)

    async def _fetch_changed_file_paths(self, pull_number: int) -> tuple[str, ...]:
        url = f"{_GITHUB_REST_ROOT}/repos/{self._owner}/{self._repo}/pulls/{pull_number}/files"
        try:
            async with self._client() as client:
                response = await client.get(
                    url,
                    params={"per_page": str(_MAX_CHANGED_FILES)},
                    headers=self._headers(),
                )
        except httpx.HTTPError as error:
            raise PullRequestFetchFailedError(f"request to GitHub failed: {error}") from error
        if response.status_code != 200:
            raise PullRequestFetchFailedError(
                f"GitHub returned HTTP {response.status_code}: {response.text[:500]}"
            )
        try:
            parsed_body: object = response.json()
        except ValueError as error:
            raise PullRequestFetchFailedError(
                f"GitHub response was not valid JSON: {error}"
            ) from error
        if not isinstance(parsed_body, list):
            raise PullRequestFetchFailedError("GitHub response body was not a JSON array")
        entries = cast(list[object], parsed_body)

        paths: list[str] = []
        for entry in entries[:_MAX_CHANGED_FILES]:
            if not isinstance(entry, dict):
                continue
            filename = cast(dict[str, object], entry).get("filename")
            if isinstance(filename, str) and filename:
                paths.append(filename[:_MAX_PATH_LENGTH])
        return tuple(paths)

    async def request_changes(self, *, pull_number: int, body: str) -> None:
        url = f"{_GITHUB_REST_ROOT}/repos/{self._owner}/{self._repo}/pulls/{pull_number}/reviews"
        try:
            async with self._client() as client:
                response = await client.post(
                    url,
                    json={"event": "REQUEST_CHANGES", "body": body},
                    headers=self._headers(),
                )
        except httpx.HTTPError as error:
            raise ReviewActionFailedError(
                "request_changes", f"request to GitHub failed: {error}"
            ) from error
        if response.status_code != 200:
            raise ReviewActionFailedError(
                "request_changes",
                f"GitHub returned HTTP {response.status_code}: {response.text[:500]}",
            )
