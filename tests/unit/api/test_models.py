"""Tests for the Workflow API's request/response models."""

import pytest
from pydantic import ValidationError

from ai_platform.api.models import WorkflowSubmitRequest


@pytest.mark.parametrize(
    "capability",
    [
        "text.word-count",
        "text.summarize",
        "code.review",
        "ui.review",
        "architecture.review",
        "data.analysis",
        "technical.review",
        "security.review",
        "assignment.route",
    ],
)
def test_submit_request_accepts_every_built_in_capability(capability: str) -> None:
    """ADR-0018/ADR-0019: `code.review`/`ui.review` are submittable
    capabilities, not just the two that existed before them."""
    request = WorkflowSubmitRequest.model_validate(
        {"text": "hello", "capability": capability, "capability_version": "1.0"}
    )

    assert request.capability == capability


def test_submit_request_rejects_an_unknown_capability() -> None:
    with pytest.raises(ValidationError):
        WorkflowSubmitRequest.model_validate(
            {"text": "hello", "capability": "not.a.capability", "capability_version": "1.0"}
        )
