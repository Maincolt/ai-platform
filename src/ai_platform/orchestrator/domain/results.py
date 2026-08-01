"""Public workflow result/failure value objects.

Mirror the public fields in contracts/json-schema/v1/workflow_submit_response.schema.json
and workflow_read_response.schema.json.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    """Present only when the workflow state is COMPLETED."""

    word_count: int

    def __post_init__(self) -> None:
        if self.word_count < 0:
            raise ValueError("word_count must be non-negative")


@dataclass(frozen=True, slots=True)
class WorkflowFailure:
    """Present only when the workflow state is FAILED. `code` is UPPER_SNAKE_CASE."""

    code: str
    detail: str
