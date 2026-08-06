"""Public workflow result/failure value objects.

Mirror the public fields in contracts/json-schema/v1/workflow_submit_response.schema.json
and workflow_read_response.schema.json.
"""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    """Present only when the workflow state is COMPLETED.

    A capability-owned, JSON-compatible payload (e.g. `{"word_count": 9}`
    for `text.word-count`, `{"summary": "..."}` for `text.summarize`) --
    see ADR-0015. Per-capability shape/value validation belongs to the
    capability that produces it, not to this generic value object.
    """

    result_data: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.result_data:
            raise ValueError("result_data must not be empty")


@dataclass(frozen=True, slots=True)
class WorkflowFailure:
    """Present only when the workflow state is FAILED. `code` is UPPER_SNAKE_CASE."""

    code: str
    detail: str
