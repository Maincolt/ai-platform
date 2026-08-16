"""Principal Developer Agent domain errors (ADR-0031).

Same shape as `scrum_master_agent.errors`/`product_owner_agent.errors` --
this agent never consumes an `ExecuteTask` command either, so none of the
standard command-lifecycle errors apply. Its failure modes are its own
fetch/dispatch boundaries.
"""


class PrincipalDeveloperAgentError(Exception):
    """Base class for Principal Developer Agent domain errors."""


class PullRequestFetchFailedError(PrincipalDeveloperAgentError):
    """The read-side open-pull-request fetch failed (HTTP error, timeout,
    or malformed shape). Raised before any AI Router call or write
    action is attempted this cycle."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"pull request fetch failed: {reason}")


class SourceControlActionFailedError(PrincipalDeveloperAgentError):
    """One dispatched action (`request_changes`/`merge`) failed --
    including `merge` being refused because the PR was no longer
    `mergeable_state == "clean"` when re-checked immediately before the
    merge call (ADR-0031 Decision 1).

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
        super().__init__(f"source control action {action_type!r} failed: {reason}")
