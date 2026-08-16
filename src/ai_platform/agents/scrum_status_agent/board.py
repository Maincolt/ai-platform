"""The deterministic, read-only project-board-fetch boundary (ADR-0027
Decision 3).

`ProjectBoardPort` is a narrow seam between `agent.py`'s orchestration and
whatever actually talks to GitHub, the same testability principle
`AIRouterPort` already gives `agent.py` for the provider call: `agent.py`
and its unit/component tests depend only on this Protocol, never on a
real HTTP call -- `GitHubProjectsBoardReader` below is the only piece of
this module that actually reaches GitHub's API.

Every method here is read-only by construction: the Protocol has no
operation that creates, edits, or moves anything on the board. `fetch()`
takes no caller-supplied target (unlike `ui_review_agent.PageCapturePort
.capture(url)`) -- the project owner/number are server-side configuration
(ADR-0027 Decision 4), not part of the request.
"""

from dataclasses import dataclass
from typing import Protocol, cast

import httpx

from ai_platform.agents.scrum_status_agent.errors import ProjectBoardFetchFailedError

_MAX_ITEMS = 100
_MAX_TITLE_LENGTH = 300
_MAX_STATUS_LENGTH = 100
_GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"
_DEFAULT_REQUEST_TIMEOUT_SECONDS = 10.0

_PROJECT_QUERY = """
query($login: String!, $number: Int!, $first: Int!) {
  user(login: $login) {
    projectV2(number: $number) {
      title
      items(first: $first) {
        nodes {
          content {
            __typename
            ... on Issue { title number state url }
            ... on PullRequest { title number state url }
            ... on DraftIssue { title }
          }
          fieldValues(first: 20) {
            nodes {
              __typename
              ... on ProjectV2ItemFieldSingleSelectValue {
                name
                field { ... on ProjectV2SingleSelectField { name } }
              }
            }
          }
        }
      }
    }
  }
}
"""


@dataclass(frozen=True, slots=True)
class BoardItem:
    """One item on the board, bounded/truncated by whatever builds it."""

    title: str
    status: str
    """The item's status-field value, e.g. "In Progress", "Done", or ""
    if the board has no status field or the item has no value set."""
    url: str
    """Empty for a draft issue, which has no URL."""


@dataclass(frozen=True, slots=True)
class ProjectBoardSnapshot:
    """The bounded set of signals fetched from one project board.

    Bounds (`_MAX_ITEMS`/`_MAX_TITLE_LENGTH`/`_MAX_STATUS_LENGTH`) are
    enforced by whatever builds this dataclass (`ProjectBoardPort.fetch()`
    implementations), not by the dataclass itself -- a fake test double is
    free to construct a `ProjectBoardSnapshot` directly without
    re-deriving them.
    """

    title: str
    items: tuple[BoardItem, ...]


class ProjectBoardPort(Protocol):
    async def fetch(self) -> ProjectBoardSnapshot:
        """Fetch the configured project board's current state.

        The board to fetch is server-side configuration (ADR-0027
        Decision 4), not a caller-supplied parameter -- this method takes
        no arguments. Raises `ProjectBoardFetchFailedError` on any HTTP
        error, timeout, GraphQL error response, or malformed shape --
        never a partial result.
        """
        ...


def _truncate(text: str, maximum_length: int) -> str:
    return text if len(text) <= maximum_length else text[:maximum_length]


def _extract_status(field_values: object) -> str:
    if not isinstance(field_values, dict):
        return ""
    field_values = cast(dict[str, object], field_values)
    nodes = field_values.get("nodes")
    if not isinstance(nodes, list):
        return ""
    nodes = cast(list[object], nodes)
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node = cast(dict[str, object], node)
        if node.get("__typename") != "ProjectV2ItemFieldSingleSelectValue":
            continue
        field = node.get("field")
        field_name = cast(dict[str, object], field).get("name") if isinstance(field, dict) else None
        if field_name == "Status":
            name = node.get("name")
            return name if isinstance(name, str) else ""
    return ""


class GitHubProjectsBoardReader:
    """The real, GitHub-GraphQL-backed `ProjectBoardPort` implementation.

    Reads only -- the GraphQL query has no mutation, and the configured
    PAT is expected to be scoped to `read:project` only (ADR-0027
    Decision 5). A fresh `httpx.AsyncClient` per call, matching
    `PlaywrightPageCapture`'s "no persistent state reused across
    submissions" discipline.
    """

    def __init__(
        self,
        *,
        token: str,
        owner: str,
        project_number: int,
        request_timeout_seconds: float = _DEFAULT_REQUEST_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """`transport` is a test-only seam (e.g. `httpx.MockTransport`) --
        production callers never pass it, letting `httpx.AsyncClient` use
        its real network transport."""
        if not token:
            raise ValueError("token must be non-empty")
        if not owner:
            raise ValueError("owner must be non-empty")
        if project_number <= 0:
            raise ValueError("project_number must be positive")
        if request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        self._token = token
        self._owner = owner
        self._project_number = project_number
        self._request_timeout_seconds = request_timeout_seconds
        self._transport = transport

    async def fetch(self) -> ProjectBoardSnapshot:
        try:
            async with httpx.AsyncClient(
                timeout=self._request_timeout_seconds, transport=self._transport
            ) as client:
                response = await client.post(
                    _GITHUB_GRAPHQL_URL,
                    json={
                        "query": _PROJECT_QUERY,
                        "variables": {
                            "login": self._owner,
                            "number": self._project_number,
                            "first": _MAX_ITEMS,
                        },
                    },
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/vnd.github+json",
                    },
                )
        except httpx.HTTPError as error:
            raise ProjectBoardFetchFailedError(f"request to GitHub failed: {error}") from error

        if response.status_code != 200:
            raise ProjectBoardFetchFailedError(
                f"GitHub returned HTTP {response.status_code}: {response.text[:500]}"
            )
        try:
            parsed_body: object = response.json()
        except ValueError as error:
            raise ProjectBoardFetchFailedError(
                f"GitHub response was not valid JSON: {error}"
            ) from error

        if not isinstance(parsed_body, dict):
            raise ProjectBoardFetchFailedError("GitHub response body was not a JSON object")
        body = cast(dict[str, object], parsed_body)
        if body.get("errors"):
            raise ProjectBoardFetchFailedError(f"GitHub returned GraphQL errors: {body['errors']}")

        try:
            data = cast(dict[str, object], body["data"])
            user = cast(dict[str, object], data["user"])
            project = user["projectV2"]
        except (KeyError, TypeError) as error:
            raise ProjectBoardFetchFailedError(
                f"GitHub response did not contain the expected project shape: {error}"
            ) from error
        if project is None:
            raise ProjectBoardFetchFailedError(
                f"no projectV2 number {self._project_number} found for user {self._owner!r}"
            )
        if not isinstance(project, dict):
            raise ProjectBoardFetchFailedError("GitHub response's projectV2 was not an object")
        project = cast(dict[str, object], project)

        title = project.get("title")
        if not isinstance(title, str):
            raise ProjectBoardFetchFailedError("GitHub response's project title was not a string")

        items_container = project.get("items")
        nodes = (
            cast(dict[str, object], items_container).get("nodes")
            if isinstance(items_container, dict)
            else None
        )
        if not isinstance(nodes, list):
            raise ProjectBoardFetchFailedError("GitHub response's item list was not present")
        nodes = cast(list[object], nodes)

        items: list[BoardItem] = []
        for node in nodes[:_MAX_ITEMS]:
            if not isinstance(node, dict):
                continue
            node = cast(dict[str, object], node)
            content = node.get("content")
            if not isinstance(content, dict):
                continue
            content = cast(dict[str, object], content)
            item_title = content.get("title")
            if not isinstance(item_title, str) or not item_title:
                continue
            url = content.get("url")
            items.append(
                BoardItem(
                    title=_truncate(item_title, _MAX_TITLE_LENGTH),
                    status=_truncate(_extract_status(node.get("fieldValues")), _MAX_STATUS_LENGTH),
                    url=url if isinstance(url, str) else "",
                )
            )

        return ProjectBoardSnapshot(title=_truncate(title, _MAX_TITLE_LENGTH), items=tuple(items))
