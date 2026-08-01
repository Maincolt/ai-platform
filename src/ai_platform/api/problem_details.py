"""Problem Details construction (vertical-slice-01.md Section 5, ADR-0004
Section 9).

Builds RFC 9457 Problem Details bodies matching
contracts/json-schema/v1/problem_details.schema.json for every stable
error in Section 5's error table.
"""

from ai_platform.shared.identifiers import CorrelationId


def build_problem_details(
    *,
    problem_type: str,
    title: str,
    status: int,
    detail: str,
    error_code: str,
    correlation_id: CorrelationId,
) -> dict[str, object]:
    return {
        "type": problem_type,
        "title": title,
        "status": status,
        "detail": detail,
        "error_code": error_code,
        "correlation_id": str(correlation_id),
    }


def invalid_request(detail: str, *, correlation_id: CorrelationId) -> dict[str, object]:
    return build_problem_details(
        problem_type="urn:ai-platform:problem:invalid-request",
        title="Invalid Request",
        status=400,
        detail=detail,
        error_code="INVALID_REQUEST",
        correlation_id=correlation_id,
    )


def request_id_conflict(*, correlation_id: CorrelationId) -> dict[str, object]:
    return build_problem_details(
        problem_type="urn:ai-platform:problem:request-id-conflict",
        title="Request ID Conflict",
        status=409,
        detail="The supplied request_id is already mapped to a different accepted request.",
        error_code="REQUEST_ID_CONFLICT",
        correlation_id=correlation_id,
    )


def workflow_not_found(*, correlation_id: CorrelationId) -> dict[str, object]:
    return build_problem_details(
        problem_type="urn:ai-platform:problem:workflow-not-found",
        title="Workflow Not Found",
        status=404,
        detail="No workflow is authorized for disclosure at this identifier.",
        error_code="WORKFLOW_NOT_FOUND",
        correlation_id=correlation_id,
    )


def agent_temporarily_unavailable(*, correlation_id: CorrelationId) -> dict[str, object]:
    return build_problem_details(
        problem_type="urn:ai-platform:problem:agent-temporarily-unavailable",
        title="Agent Temporarily Unavailable",
        status=503,
        detail="No eligible Agent is currently ready for this capability. No records were created.",
        error_code="AGENT_TEMPORARILY_UNAVAILABLE",
        correlation_id=correlation_id,
    )


def internal_processing_failure(*, correlation_id: CorrelationId) -> dict[str, object]:
    return build_problem_details(
        problem_type="urn:ai-platform:problem:internal-processing-failure",
        title="Internal Processing Failure",
        status=500,
        detail="A safe unexpected internal failure occurred. The caller may reuse request_id.",
        error_code="INTERNAL_PROCESSING_FAILURE",
        correlation_id=correlation_id,
    )
