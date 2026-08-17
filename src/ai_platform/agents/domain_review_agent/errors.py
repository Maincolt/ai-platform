"""Domain Review Agent domain errors (ADR-0033).

Same shape as every prior autonomous role's errors module -- this agent
never consumes an `ExecuteTask` command either, so none of the standard
command-lifecycle errors apply.
"""


class DomainReviewAgentError(Exception):
    """Base class for Domain Review Agent domain errors."""


class PullRequestFetchFailedError(DomainReviewAgentError):
    """The read-side open-pull-request (or changed-file-path) fetch
    failed. Raised before any AI Router call or write action is
    attempted this cycle."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"pull request fetch failed: {reason}")


class ReviewActionFailedError(DomainReviewAgentError):
    """The one dispatched action (`request_changes`) failed against
    GitHub's API.

    Deliberately does not stop the cycle: each proposed action is
    dispatched independently, and the caller records this as one failed
    `agent.autonomous_actions` row before moving on to the next proposed
    action (ADR-0028 Decision 3, reused unchanged).
    """

    def __init__(self, action_type: str, reason: str) -> None:
        self.action_type = action_type
        self.reason = reason
        super().__init__(f"review action {action_type!r} failed: {reason}")
