"""The Workflow API (vertical-slice-01.md Section 5).

Maps Sprint 3's SubmissionOrchestrator/TerminalEventProcessor domain
outcomes to HTTP, applying ADR-0012 correlation normalization to every
response that can safely be produced.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ai_platform.api import problem_details
from ai_platform.api.correlation import normalize_correlation_id
from ai_platform.api.dependencies import AppState, build_app_state
from ai_platform.api.fingerprint import compute_fingerprint
from ai_platform.api.ids import Uuid7IdentifierFactory
from ai_platform.api.models import (
    AgentsListResponse,
    AgentStatusModel,
    WorkflowFailureModel,
    WorkflowReadResponse,
    WorkflowResultModel,
    WorkflowSubmitRequest,
    WorkflowSubmitResponse,
)
from ai_platform.orchestrator.application.submission import (
    SubmissionDisposition,
    SubmissionRequest,
)
from ai_platform.orchestrator.domain.workflow import Workflow
from ai_platform.orchestrator.registry.availability import is_fresh
from ai_platform.shared.identifiers import CorrelationId, RequestId, WorkflowId

_NEVER_OBSERVED = datetime.min.replace(tzinfo=UTC)

CORRELATION_HEADER = "Correlation-Id"

app = FastAPI(
    title="AI Platform Workflow API",
    version="1.0.0",
    description=(
        "Vertical Slice 01 Workflow API. See "
        "contracts/openapi/v1/workflow-api.openapi.json for the canonical contract."
    ),
)

_app_state = build_app_state()


def get_app_state() -> AppState:
    return _app_state


def configure_app_state(state: AppState) -> None:
    """Install the process-lifetime state before the concrete API server starts."""
    global _app_state
    _app_state = state


def _effective_correlation_id(request: Request) -> CorrelationId:
    raw_value = request.headers.get(CORRELATION_HEADER)
    return normalize_correlation_id(raw_value).effective_correlation_id


def _result_model(workflow: Workflow) -> WorkflowResultModel | None:
    if workflow.result is None:
        return None
    return WorkflowResultModel(**workflow.result.result_data)


def _failure_model(workflow: Workflow) -> WorkflowFailureModel | None:
    if workflow.failure is None:
        return None
    return WorkflowFailureModel(code=workflow.failure.code, detail=workflow.failure.detail)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    correlation_id = _effective_correlation_id(request)
    body = problem_details.invalid_request(
        "The request body did not conform to the workflow.submit contract.",
        correlation_id=correlation_id,
    )
    return JSONResponse(
        status_code=400,
        content=body,
        headers={CORRELATION_HEADER: str(correlation_id)},
        media_type="application/problem+json",
    )


@app.exception_handler(StarletteHTTPException)
async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Preserves FastAPI/Starlette's own HTTPException status codes (e.g.
    404 for an unmatched route, 405 for an unsupported method) as safe
    Problem Details, rather than letting the catch-all Exception handler
    below turn every one of them into an opaque 500 (HTTPException is a
    subclass of Exception, so it must be handled explicitly and first)."""
    correlation_id = _effective_correlation_id(request)
    body = problem_details.build_problem_details(
        problem_type="urn:ai-platform:problem:http-error",
        title="HTTP Error",
        status=exc.status_code,
        detail=str(exc.detail) if exc.detail else "An HTTP error occurred.",
        error_code=f"HTTP_{exc.status_code}",
        correlation_id=correlation_id,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        headers={CORRELATION_HEADER: str(correlation_id)},
        media_type="application/problem+json",
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    correlation_id = _effective_correlation_id(request)
    body = problem_details.internal_processing_failure(correlation_id=correlation_id)
    return JSONResponse(
        status_code=500,
        content=body,
        headers={CORRELATION_HEADER: str(correlation_id)},
        media_type="application/problem+json",
    )


@app.post("/api/v1/workflows", status_code=202)
async def submit_workflow(
    request: Request,
    body: WorkflowSubmitRequest,
    state: Annotated[AppState, Depends(get_app_state)],
) -> JSONResponse:
    correlation_id = _effective_correlation_id(request)
    now = datetime.now(UTC)
    trusted_context = state.security_policy.resolve(semantic_operation="workflow.submit")

    request_id = (
        RequestId(body.request_id)
        if body.request_id is not None
        else RequestId(Uuid7IdentifierFactory().new_id())
    )
    fingerprint = compute_fingerprint(
        text=body.text,
        capability_name=body.capability,
        capability_version=body.capability_version,
    )

    submission_request = SubmissionRequest(
        environment=trusted_context.environment,
        operation=trusted_context.semantic_operation,
        idempotency_scope_id=trusted_context.idempotency_scope_id,
        request_id=request_id,
        correlation_id=correlation_id,
        acceptance_actor_id=trusted_context.current_actor_id,
        accepted_owner_subject_id=trusted_context.current_owner_subject_id,
        current_owner_subject_id=trusted_context.current_owner_subject_id,
        fingerprint=fingerprint,
        fingerprint_policy_version="1.0",
        policy_identity=trusted_context.policy_identity,
        policy_revision=trusted_context.policy_revision,
        policy_decision=trusted_context.policy_decision,
        scope_mapping_revision=trusted_context.scope_mapping_revision,
        authorization_evidence=trusted_context.authorization_evidence,
        text=body.text,
        capability_name=body.capability,
        capability_version=body.capability_version,
        command_contract_name="ExecuteTask",
        command_contract_version="1.0",
        event_contract_names=("TaskCompleted", "TaskFailed"),
        event_contract_versions=("1.0", "1.0"),
        task_result_deadline=now + state.task_result_timeout,
    )

    result = await state.submission_orchestrator.submit(submission_request, now=now)

    if result.disposition == SubmissionDisposition.NO_ELIGIBLE_AGENT:
        return JSONResponse(
            status_code=503,
            content=problem_details.agent_temporarily_unavailable(correlation_id=correlation_id),
            headers={CORRELATION_HEADER: str(correlation_id)},
            media_type="application/problem+json",
        )
    if result.disposition == SubmissionDisposition.CONFIGURATION_ERROR:
        return JSONResponse(
            status_code=500,
            content=problem_details.internal_processing_failure(correlation_id=correlation_id),
            headers={CORRELATION_HEADER: str(correlation_id)},
            media_type="application/problem+json",
        )
    if result.disposition == SubmissionDisposition.FINGERPRINT_CONFLICT:
        return JSONResponse(
            status_code=409,
            content=problem_details.request_id_conflict(correlation_id=correlation_id),
            headers={CORRELATION_HEADER: str(correlation_id)},
            media_type="application/problem+json",
        )
    if result.disposition == SubmissionDisposition.OWNER_INTENT_MISMATCH:
        return JSONResponse(
            status_code=404,
            content=problem_details.workflow_not_found(correlation_id=correlation_id),
            headers={CORRELATION_HEADER: str(correlation_id)},
            media_type="application/problem+json",
        )
    if result.disposition == SubmissionDisposition.FINGERPRINT_POLICY_UNAVAILABLE:
        return JSONResponse(
            status_code=500,
            content=problem_details.internal_processing_failure(correlation_id=correlation_id),
            headers={CORRELATION_HEADER: str(correlation_id)},
            media_type="application/problem+json",
        )

    assert result.workflow is not None
    workflow = result.workflow
    status_code = 202 if result.disposition == SubmissionDisposition.NEW else 200
    response_body = WorkflowSubmitResponse(
        request_id=str(request_id),
        correlation_id=str(workflow.correlation_id),
        workflow_id=str(workflow.workflow_id),
        state=workflow.state.value if workflow.state is not None else "RECEIVED",
        result=_result_model(workflow),
        failure=_failure_model(workflow),
    )
    return JSONResponse(
        status_code=status_code,
        content=response_body.model_dump(exclude_none=True),
        headers={CORRELATION_HEADER: str(correlation_id)},
    )


@app.get("/api/v1/workflows/{workflow_id}")
async def read_workflow(
    request: Request,
    workflow_id: str,
    state: Annotated[AppState, Depends(get_app_state)],
) -> JSONResponse:
    correlation_id = _effective_correlation_id(request)
    trusted_context = state.security_policy.resolve(semantic_operation="workflow.read")
    workflow = await state.workflow_access_query.get_authorized(
        WorkflowId(workflow_id),
        environment=trusted_context.environment,
        current_owner_subject_id=trusted_context.current_owner_subject_id,
    )
    if workflow is None:
        return JSONResponse(
            status_code=404,
            content=problem_details.workflow_not_found(correlation_id=correlation_id),
            headers={CORRELATION_HEADER: str(correlation_id)},
            media_type="application/problem+json",
        )

    created_at = workflow.history[0].occurred_at if workflow.history else datetime.now(UTC)
    updated_at = workflow.history[-1].occurred_at if workflow.history else created_at

    response_body = WorkflowReadResponse(
        request_id=str(workflow.request_id),
        correlation_id=str(workflow.correlation_id),
        workflow_id=str(workflow.workflow_id),
        state=workflow.state.value if workflow.state is not None else "RECEIVED",
        revision=max(workflow.revision, 1),
        created_at=created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        updated_at=updated_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        result=_result_model(workflow),
        failure=_failure_model(workflow),
    )
    return JSONResponse(
        status_code=200,
        content=response_body.model_dump(exclude_none=True),
        headers={CORRELATION_HEADER: str(correlation_id)},
    )


@app.get("/api/v1/agents")
async def list_agents(
    request: Request,
    state: Annotated[AppState, Depends(get_app_state)],
) -> JSONResponse:
    """Read-only Capability Registry status: every declared Agent binding
    and its current readiness observation. Never affects candidate
    selection -- it reads the same registry/availability state
    `SubmissionOrchestrator` already uses, it does not compute its own."""
    correlation_id = _effective_correlation_id(request)
    now = datetime.now(UTC)
    agents: list[AgentStatusModel] = []
    if state.registry_snapshot is not None:
        for binding in state.registry_snapshot.bindings:
            observation = (
                state.availability_port.observe(
                    binding.agent_id, binding.capability_name, binding.capability_version
                )
                if state.availability_port is not None
                else None
            )
            agents.append(
                AgentStatusModel(
                    agent_id=str(binding.agent_id),
                    capability=binding.capability_name,
                    capability_version=binding.capability_version,
                    implementation_identity=binding.implementation_identity,
                    environment=binding.environment,
                    enabled=binding.enabled,
                    status=(
                        observation.classification.value if observation is not None else "UNKNOWN"
                    ),
                    fresh=is_fresh(observation, now=now) if observation is not None else False,
                    last_observed_at=(
                        observation.observed_at.strftime("%Y-%m-%dT%H:%M:%SZ")
                        if observation is not None and observation.observed_at != _NEVER_OBSERVED
                        else None
                    ),
                )
            )
    response_body = AgentsListResponse(agents=agents)
    return JSONResponse(
        status_code=200,
        content=response_body.model_dump(),
        headers={CORRELATION_HEADER: str(correlation_id)},
    )


@app.get("/health/live")
async def health_live() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/health/ready")
async def health_ready(state: Annotated[AppState, Depends(get_app_state)]) -> dict[str, str]:
    """Report core readiness without coupling it to Agent availability."""
    snapshot = await state.readiness.snapshot()
    if snapshot.ready and state.registry_loaded:
        return {"status": "ready"}
    raise StarletteHTTPException(status_code=503, detail="Core dependencies are not ready.")
