"""The project-board read+write boundary (ADR-0028 Decision 1).

`ProjectTrackerPort` is a narrow seam between `agent.py`'s orchestration
and whatever actually talks to GitHub, the same testability principle
`scrum_status_agent.board.ProjectBoardPort` already established for the
read-only Phase 1 capability -- `agent.py` and its unit/component tests
depend only on this Protocol, never on a real HTTP call.

Unlike Phase 1's board module, this one combines read (fetch, extended
with each item's GraphQL node ID, which the write mutations need to
target a specific card) with the three ADR-0028 Decision 1 write
actions: `set_status`, `add_comment`, `create_draft_item`. Every write
method raises `TrackerActionFailedError` on any failure -- never a
partial/best-effort result -- and none of them ever calls a push or
force-push endpoint (ADR-0028 Decision 4's "no push" boundary is
enforced here, in code, not by the configured PAT's scope).
"""

import re
from dataclasses import dataclass
from typing import Protocol, cast

import httpx

from ai_platform.agents.scrum_master_agent.errors import (
    ProjectBoardFetchFailedError,
    TrackerActionFailedError,
)

_MAX_ITEMS = 100
_MAX_TITLE_LENGTH = 300
_MAX_STATUS_LENGTH = 100
_GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"
_GITHUB_REST_ROOT = "https://api.github.com"
_DEFAULT_REQUEST_TIMEOUT_SECONDS = 10.0

_ISSUE_URL_PATTERN = re.compile(
    r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/(?:issues|pull)/(?P<number>\d+)$"
)

_BOARD_QUERY = """
query($login: String!, $number: Int!, $first: Int!) {
  user(login: $login) {
    projectV2(number: $number) {
      title
      items(first: $first) {
        nodes {
          id
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

_METADATA_QUERY = """
query($login: String!, $number: Int!) {
  user(login: $login) {
    projectV2(number: $number) {
      id
      field(name: "Status") {
        ... on ProjectV2SingleSelectField {
          id
          options { id name }
        }
      }
    }
  }
}
"""

_SET_STATUS_MUTATION = """
mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
  updateProjectV2ItemFieldValue(input: {
    projectId: $projectId, itemId: $itemId, fieldId: $fieldId,
    value: { singleSelectOptionId: $optionId }
  }) {
    projectV2Item { id }
  }
}
"""

_CREATE_DRAFT_ITEM_MUTATION = """
mutation($projectId: ID!, $title: String!, $body: String!) {
  addProjectV2DraftIssue(input: { projectId: $projectId, title: $title, body: $body }) {
    projectItem { id }
  }
}
"""


@dataclass(frozen=True, slots=True)
class BoardItem:
    """One item on the board, bounded/truncated by whatever builds it."""

    item_id: str
    """The Projects v2 item's own GraphQL node ID -- required to target
    this specific card in `set_status`. Not the same as the underlying
    issue/PR's own node ID."""
    title: str
    status: str
    """The item's status-field value, e.g. "In Progress", "Done", or ""
    if the board has no status field or the item has no value set."""
    url: str
    """Empty for a draft issue, which has no URL."""


@dataclass(frozen=True, slots=True)
class ProjectBoardSnapshot:
    title: str
    items: tuple[BoardItem, ...]


class ProjectTrackerPort(Protocol):
    async def fetch(self) -> ProjectBoardSnapshot:
        """Fetch the configured project board's current state. Raises
        `ProjectBoardFetchFailedError` on any failure -- never a partial
        result."""
        ...

    async def set_status(self, *, item_id: str, status_name: str) -> None:
        """Move a card by changing its Status field value to
        `status_name`. Raises `TrackerActionFailedError` if the status
        option doesn't exist on this board or the mutation fails."""
        ...

    async def add_comment(self, *, issue_url: str, body: str) -> None:
        """Comment on an existing issue or pull request. `issue_url` must
        be a `github.com/{owner}/{repo}/issues|pull/{number}` URL (the
        shape every non-draft `BoardItem.url` already has). Raises
        `TrackerActionFailedError` on any failure, including a
        draft-item URL (empty string) that has no issue to comment on."""
        ...

    async def create_draft_item(self, *, title: str, body: str) -> None:
        """Add a draft issue to the board. Raises
        `TrackerActionFailedError` on any failure."""
        ...

    async def close_issue(self, *, issue_url: str) -> None:
        """Close an existing issue or pull request. `issue_url` must be a
        `github.com/{owner}/{repo}/issues|pull/{number}` URL. Raises
        `TrackerActionFailedError` on any failure, including a draft-item
        URL (empty string) that has no issue to close."""
        ...

    async def relabel(self, *, issue_url: str, labels: tuple[str, ...]) -> None:
        """Replace an issue's label set with exactly `labels` (a full
        replace, not an add/remove delta). Raises
        `TrackerActionFailedError` on any failure, including a draft-item
        URL that has no issue to relabel."""
        ...

    async def reassign(self, *, issue_url: str, assignees: tuple[str, ...]) -> None:
        """Replace an issue's assignee set with exactly `assignees` (a
        full replace, not an add/remove delta). Raises
        `TrackerActionFailedError` on any failure, including a draft-item
        URL that has no issue to reassign."""
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


class GitHubProjectsTrackerClient:
    """The real, GitHub-GraphQL/REST-backed `ProjectTrackerPort`
    implementation. A fresh `httpx.AsyncClient` per call, matching every
    prior fetch-based capability's "no persistent state reused across
    calls" discipline."""

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
        production callers never pass it."""
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
        self._project_id: str | None = None
        self._status_field_id: str | None = None
        self._status_options: dict[str, str] | None = None

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._request_timeout_seconds, transport=self._transport)

    async def _graphql(self, query: str, variables: dict[str, object]) -> dict[str, object]:
        try:
            async with self._client() as client:
                response = await client.post(
                    _GITHUB_GRAPHQL_URL,
                    json={"query": query, "variables": variables},
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
        return body

    async def fetch(self) -> ProjectBoardSnapshot:
        body = await self._graphql(
            _BOARD_QUERY,
            {"login": self._owner, "number": self._project_number, "first": _MAX_ITEMS},
        )
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
            item_id = node.get("id")
            content = node.get("content")
            if not isinstance(item_id, str) or not item_id or not isinstance(content, dict):
                continue
            content = cast(dict[str, object], content)
            item_title = content.get("title")
            if not isinstance(item_title, str) or not item_title:
                continue
            url = content.get("url")
            items.append(
                BoardItem(
                    item_id=item_id,
                    title=_truncate(item_title, _MAX_TITLE_LENGTH),
                    status=_truncate(_extract_status(node.get("fieldValues")), _MAX_STATUS_LENGTH),
                    url=url if isinstance(url, str) else "",
                )
            )

        return ProjectBoardSnapshot(title=_truncate(title, _MAX_TITLE_LENGTH), items=tuple(items))

    async def _ensure_metadata(self) -> tuple[str, str, dict[str, str]]:
        if (
            self._project_id is not None
            and self._status_field_id is not None
            and self._status_options is not None
        ):
            return self._project_id, self._status_field_id, self._status_options

        body = await self._graphql(
            _METADATA_QUERY, {"login": self._owner, "number": self._project_number}
        )
        try:
            data = cast(dict[str, object], body["data"])
            user = cast(dict[str, object], data["user"])
            project = cast(dict[str, object], user["projectV2"])
            project_id = project["id"]
            field = cast(dict[str, object], project["field"])
            field_id = field["id"]
            options = cast(list[object], field["options"])
        except (KeyError, TypeError) as error:
            raise TrackerActionFailedError(
                "set_status", f"could not resolve project/Status field metadata: {error}"
            ) from error
        if not isinstance(project_id, str) or not isinstance(field_id, str):
            raise TrackerActionFailedError(
                "set_status", "project or Status field ID was not a string"
            )

        option_map: dict[str, str] = {}
        for option in options:
            if not isinstance(option, dict):
                continue
            option = cast(dict[str, object], option)
            name, option_id = option.get("name"), option.get("id")
            if isinstance(name, str) and isinstance(option_id, str):
                option_map[name] = option_id

        self._project_id, self._status_field_id, self._status_options = (
            project_id,
            field_id,
            option_map,
        )
        return project_id, field_id, option_map

    async def set_status(self, *, item_id: str, status_name: str) -> None:
        try:
            project_id, field_id, options = await self._ensure_metadata()
        except ProjectBoardFetchFailedError as error:
            raise TrackerActionFailedError("set_status", str(error)) from error
        option_id = options.get(status_name)
        if option_id is None:
            raise TrackerActionFailedError(
                "set_status", f"{status_name!r} is not a valid Status option on this board"
            )
        try:
            body = await self._graphql(
                _SET_STATUS_MUTATION,
                {
                    "projectId": project_id,
                    "itemId": item_id,
                    "fieldId": field_id,
                    "optionId": option_id,
                },
            )
        except ProjectBoardFetchFailedError as error:
            raise TrackerActionFailedError("set_status", str(error)) from error
        if "updateProjectV2ItemFieldValue" not in cast(dict[str, object], body.get("data", {})):
            raise TrackerActionFailedError("set_status", "mutation response missing expected data")

    async def create_draft_item(self, *, title: str, body: str) -> None:
        try:
            project_id, _field_id, _options = await self._ensure_metadata()
        except ProjectBoardFetchFailedError as error:
            raise TrackerActionFailedError("create_draft_item", str(error)) from error
        try:
            response_body = await self._graphql(
                _CREATE_DRAFT_ITEM_MUTATION,
                {"projectId": project_id, "title": title, "body": body},
            )
        except ProjectBoardFetchFailedError as error:
            raise TrackerActionFailedError("create_draft_item", str(error)) from error
        if "addProjectV2DraftIssue" not in cast(dict[str, object], response_body.get("data", {})):
            raise TrackerActionFailedError(
                "create_draft_item", "mutation response missing expected data"
            )

    async def add_comment(self, *, issue_url: str, body: str) -> None:
        match = _ISSUE_URL_PATTERN.match(issue_url)
        if match is None:
            raise TrackerActionFailedError(
                "add_comment", f"{issue_url!r} is not a recognized issue/PR URL"
            )
        owner, repo, number = match["owner"], match["repo"], match["number"]
        url = f"{_GITHUB_REST_ROOT}/repos/{owner}/{repo}/issues/{number}/comments"
        try:
            async with self._client() as client:
                response = await client.post(
                    url,
                    json={"body": body},
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/vnd.github+json",
                    },
                )
        except httpx.HTTPError as error:
            raise TrackerActionFailedError(
                "add_comment", f"request to GitHub failed: {error}"
            ) from error
        if response.status_code != 201:
            raise TrackerActionFailedError(
                "add_comment", f"GitHub returned HTTP {response.status_code}: {response.text[:500]}"
            )

    def _parse_issue_url(self, action: str, issue_url: str) -> tuple[str, str, str]:
        match = _ISSUE_URL_PATTERN.match(issue_url)
        if match is None:
            raise TrackerActionFailedError(
                action, f"{issue_url!r} is not a recognized issue/PR URL"
            )
        return match["owner"], match["repo"], match["number"]

    async def _patch_issue(self, action: str, issue_url: str, payload: dict[str, object]) -> None:
        owner, repo, number = self._parse_issue_url(action, issue_url)
        url = f"{_GITHUB_REST_ROOT}/repos/{owner}/{repo}/issues/{number}"
        try:
            async with self._client() as client:
                response = await client.patch(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/vnd.github+json",
                    },
                )
        except httpx.HTTPError as error:
            raise TrackerActionFailedError(action, f"request to GitHub failed: {error}") from error
        if response.status_code != 200:
            raise TrackerActionFailedError(
                action, f"GitHub returned HTTP {response.status_code}: {response.text[:500]}"
            )

    async def close_issue(self, *, issue_url: str) -> None:
        await self._patch_issue("close_issue", issue_url, {"state": "closed"})

    async def relabel(self, *, issue_url: str, labels: tuple[str, ...]) -> None:
        owner, repo, number = self._parse_issue_url("relabel", issue_url)
        url = f"{_GITHUB_REST_ROOT}/repos/{owner}/{repo}/issues/{number}/labels"
        try:
            async with self._client() as client:
                response = await client.put(
                    url,
                    json={"labels": list(labels)},
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Accept": "application/vnd.github+json",
                    },
                )
        except httpx.HTTPError as error:
            raise TrackerActionFailedError(
                "relabel", f"request to GitHub failed: {error}"
            ) from error
        if response.status_code != 200:
            raise TrackerActionFailedError(
                "relabel", f"GitHub returned HTTP {response.status_code}: {response.text[:500]}"
            )

    async def reassign(self, *, issue_url: str, assignees: tuple[str, ...]) -> None:
        await self._patch_issue("reassign", issue_url, {"assignees": list(assignees)})
