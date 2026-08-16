"""Scrum Master Agent domain errors (ADR-0028).

Unlike every prior Agent module, these are not the standard five
`ExecuteTask`-lifecycle errors (`CapabilityMismatchError`,
`CommandIdentityConflictError`, etc.) -- this agent never consumes a
command, so none of that lifecycle applies. Its failure modes are its
own two fetch/dispatch boundaries instead.
"""


class ScrumMasterAgentError(Exception):
    """Base class for Scrum Master Agent domain errors."""


class ProjectBoardFetchFailedError(ScrumMasterAgentError):
    """The read-side board fetch failed (HTTP error, timeout, GraphQL
    error response, or malformed shape). Raised before any AI Router
    call or write action is attempted this cycle."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"project board fetch failed: {reason}")


class TrackerActionFailedError(ScrumMasterAgentError):
    """One dispatched write action (`set_status`/`add_comment`/
    `create_draft_item`) failed against GitHub's API.

    Deliberately does not stop the cycle: each proposed action is
    dispatched independently, and the caller records this as one
    failed `agent.autonomous_actions` row before moving on to the next
    proposed action (ADR-0028 Decision 3) -- there is nothing to roll
    back, so failing closed on the whole batch would only silently
    drop actions that would have succeeded.
    """

    def __init__(self, action_type: str, reason: str) -> None:
        self.action_type = action_type
        self.reason = reason
        super().__init__(f"tracker action {action_type!r} failed: {reason}")
