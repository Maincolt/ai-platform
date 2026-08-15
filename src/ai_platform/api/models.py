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
    capability: Literal[
        "text.word-count",
        "text.summarize",
        "code.review",
        "ui.review",
        "architecture.review",
        "data.analysis",
    ]
    capability_version: Literal["1.0"]


class WorkflowResultModel(BaseModel):
    """Generic, capability-scoped result payload (ADR-0015 Section 4).

    Deliberately looser than the internal event contracts: the caller
    already knows which capability it submitted and can interpret the
    result accordingly (e.g. `word_count` for `text.word-count`,
    `summary` for `text.summarize`).
    """

    model_config = ConfigDict(extra="allow")


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


class AgentStatusModel(BaseModel):
    """One Capability Registry binding plus its current readiness observation."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    capability: str
    capability_version: str
    implementation_identity: str
    environment: str
    enabled: bool
    status: Literal["READY", "STALE", "UNKNOWN", "UNAVAILABLE", "DRAINING"]
    fresh: bool
    last_observed_at: str | None = None


class AgentsListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agents: list[AgentStatusModel]


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
