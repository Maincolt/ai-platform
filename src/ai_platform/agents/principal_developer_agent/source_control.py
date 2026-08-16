"""The pull-request review+merge boundary (ADR-0031 Decision 1).

`SourceControlPort` is the same narrow-seam testability principle every
prior autonomous role's tracker Protocol already established --
`agent.py` and its unit/component tests depend only on this Protocol,
never on a real HTTP call. REST-only, unlike `scrum_master_agent`/
`product_owner_agent`'s GraphQL+REST mix -- this role operates on a
repository's pull requests directly, never the Projects v2 board, so
there is no GraphQL surface here at all.

Two actions: `request_changes` (no eligibility gate -- any open PR is a
valid target) and `merge` (gated on GitHub's own computed
`mergeable_state == "clean"`, re-checked immediately before the merge
call itself to close the TOCTOU gap between the cycle's initial fetch
and the actual dispatch -- the single most important safety check in
this whole role, given `merge` is the platform's first genuinely
irreversible autonomous action). Neither this module nor the credential
it uses ever calls a push or force-push endpoint -- the same "the
boundary is what the code implements, not what the token could
theoretically do" pattern every prior role's client already established.
"""

from dataclasses import dataclass
from typing import Protocol, cast

import httpx

from ai_platform.agents.principal_developer_agent.errors import (
    PullRequestFetchFailedError,
    SourceControlActionFailedError,
)

_MAX_PULL_REQUESTS = 50
_MAX_TITLE_LENGTH = 300
_GITHUB_REST_ROOT = "https://api.github.com"
_DEFAULT_REQUEST_TIMEOUT_SECONDS = 10.0
_MERGEABLE_STATE_CLEAN = "clean"


@dataclass(frozen=True, slots=True)
class PullRequestSnapshot:
    """One open pull request, bounded/truncated by whatever builds it."""

    number: int
    title: str
    mergeable_state: str
    """GitHub's own computed merge-eligibility signal (e.g. "clean",
    "blocked", "dirty", "unstable"), or "unknown" if GitHub has not
    finished computing it yet -- never treated as mergeable in that
    case."""


class SourceControlPort(Protocol):
    async def fetch_open_pull_requests(self) -> tuple[PullRequestSnapshot, ...]:
        """Fetch the configured repository's open pull requests, each
        with GitHub's current `mergeable_state`. Raises
        `PullRequestFetchFailedError` on any failure -- never a partial
        result."""
        ...

    async def request_changes(self, *, pull_number: int, body: str) -> None:
        """Leave a "changes requested" review on a pull request. No
        merge-eligibility gate -- any open PR is a valid target. Raises
        `SourceControlActionFailedError` on any failure."""
        ...

    async def merge(self, *, pull_number: int) -> None:
        """Merge a pull request. Re-fetches `mergeable_state`
        immediately before merging and raises
        `SourceControlActionFailedError` without merging if it is no
        longer exactly "clean" -- closes the gap between the cycle's
        initial fetch and this dispatch. Never pushes or force-pushes;
        this is the same REST call a human clicking GitHub's own "Merge
        pull request" button would trigger, subject to the same branch-
        protection rules."""
        ...


def _truncate(text: str, maximum_length: int) -> str:
    return text if len(text) <= maximum_length else text[:maximum_length]


class GitHubSourceControlClient:
    """The real, GitHub-REST-backed `SourceControlPort` implementation. A
    fresh `httpx.AsyncClient` per call, matching every prior fetch-based
    capability's "no persistent state reused across calls" discipline."""

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
            mergeable_state = await self._fetch_mergeable_state(number)
            snapshots.append(
                PullRequestSnapshot(
                    number=number,
                    title=_truncate(title, _MAX_TITLE_LENGTH),
                    mergeable_state=mergeable_state,
                )
            )
        return tuple(snapshots)

    async def _fetch_mergeable_state(self, pull_number: int) -> str:
        url = f"{_GITHUB_REST_ROOT}/repos/{self._owner}/{self._repo}/pulls/{pull_number}"
        try:
            async with self._client() as client:
                response = await client.get(url, headers=self._headers())
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
        if not isinstance(parsed_body, dict):
            raise PullRequestFetchFailedError("GitHub response body was not a JSON object")
        state = cast(dict[str, object], parsed_body).get("mergeable_state")
        return state if isinstance(state, str) and state else "unknown"

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
            raise SourceControlActionFailedError(
                "request_changes", f"request to GitHub failed: {error}"
            ) from error
        if response.status_code != 200:
            raise SourceControlActionFailedError(
                "request_changes",
                f"GitHub returned HTTP {response.status_code}: {response.text[:500]}",
            )

    async def merge(self, *, pull_number: int) -> None:
        try:
            current_state = await self._fetch_mergeable_state(pull_number)
        except PullRequestFetchFailedError as error:
            raise SourceControlActionFailedError("merge", str(error)) from error
        if current_state != _MERGEABLE_STATE_CLEAN:
            raise SourceControlActionFailedError(
                "merge",
                f"PR #{pull_number} is no longer mergeable (mergeable_state={current_state!r})",
            )

        url = f"{_GITHUB_REST_ROOT}/repos/{self._owner}/{self._repo}/pulls/{pull_number}/merge"
        try:
            async with self._client() as client:
                response = await client.put(url, headers=self._headers())
        except httpx.HTTPError as error:
            raise SourceControlActionFailedError(
                "merge", f"request to GitHub failed: {error}"
            ) from error
        if response.status_code != 200:
            raise SourceControlActionFailedError(
                "merge", f"GitHub returned HTTP {response.status_code}: {response.text[:500]}"
            )
