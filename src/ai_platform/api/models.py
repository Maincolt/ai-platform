"""Request/response models mirroring contracts/json-schema/v1/*.

Kept intentionally close to the canonical schemas from Sprint 1 so the two
stay easy to compare; `tests/contract/` continues to validate the schema
documents themselves.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

_UUIDV7_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"


class WorkflowSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str | None = Field(default=None, pattern=_UUIDV7_PATTERN)
    text: str = Field(min_length=1, max_length=10000)
    capability: Literal["text.word-count"]
    capability_version: Literal["1.0"]


class WorkflowResultModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    word_count: int = Field(ge=0)


class WorkflowFailureModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    detail: str


class WorkflowSubmitResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(pattern=_UUIDV7_PATTERN)
    correlation_id: str = Field(pattern=_UUIDV7_PATTERN)
    workflow_id: str = Field(pattern=_UUIDV7_PATTERN)
    state: Literal["RECEIVED", "PENDING", "DISPATCHED", "COMPLETED", "FAILED"]
    result: WorkflowResultModel | None = None
    failure: WorkflowFailureModel | None = None


class WorkflowReadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(pattern=_UUIDV7_PATTERN)
    correlation_id: str = Field(pattern=_UUIDV7_PATTERN)
    workflow_id: str = Field(pattern=_UUIDV7_PATTERN)
    state: Literal["RECEIVED", "PENDING", "DISPATCHED", "COMPLETED", "FAILED"]
    revision: int = Field(ge=1)
    created_at: str
    updated_at: str
    result: WorkflowResultModel | None = None
    failure: WorkflowFailureModel | None = None
