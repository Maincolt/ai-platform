"""Product Owner Agent domain errors (ADR-0030).

Same shape as `scrum_master_agent.errors` -- this agent never consumes an
`ExecuteTask` command either, so none of the standard command-lifecycle
errors apply. Its failure modes are its own fetch/dispatch boundaries.
"""


class ProductOwnerAgentError(Exception):
    """Base class for Product Owner Agent domain errors."""


class BacklogFetchFailedError(ProductOwnerAgentError):
    """The read-side board fetch failed (HTTP error, timeout, GraphQL
    error response, or malformed shape). Raised before any AI Router
    call or write action is attempted this cycle."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"backlog fetch failed: {reason}")


class TrackerActionFailedError(ProductOwnerAgentError):
    """One dispatched write action (`create_ticket`/`edit_ticket`/
    `close_ticket`/`reprioritize`/`adjust_sprint_scope`) failed against
    GitHub's API.

    Deliberately does not stop the cycle: each proposed action is
    dispatched independently, and the caller records this as one failed
    `agent.autonomous_actions` row before moving on to the next proposed
    action (ADR-0028 Decision 3, reused unchanged) -- there is nothing to
    roll back, so failing closed on the whole batch would only silently
    drop actions that would have succeeded.
    """

    def __init__(self, action_type: str, reason: str) -> None:
        self.action_type = action_type
        self.reason = reason
        super().__init__(f"tracker action {action_type!r} failed: {reason}")
