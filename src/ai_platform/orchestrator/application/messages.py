"""Building the ExecuteTask outbox payload from domain data.

Matches contracts/json-schema/v1/execute_task.schema.json (Sprint 1) and
vertical-slice-01.md Section 10. Kept as a small pure function, separate
from SubmissionOrchestrator, so its shape can be tested and evolved
independently of transaction orchestration.
"""

from datetime import datetime

from ai_platform.orchestrator.domain.identifiers import (
    CorrelationId,
    RequestId,
    TaskAttemptId,
    TaskId,
    WorkflowId,
)
from ai_platform.orchestrator.domain.selection import SelectionIntent


def _iso8601_utc(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_execute_task_payload(
    *,
    message_id: str,
    correlation_id: CorrelationId,
    workflow_id: WorkflowId,
    task_id: TaskId,
    task_attempt_id: TaskAttemptId,
    orchestrator_component: str,
    orchestrator_instance_id: str,
    request_id: RequestId,
    input_text: str,
    selection: SelectionIntent,
    task_result_deadline: datetime,
    created_at: datetime,
) -> dict[str, object]:
    """Build the immutable ExecuteTask envelope+payload dict.

    `causation_id` is always null: this is always the root command for a
    workflow (Section 10).
    """
    return {
        "message_id": message_id,
        "message_kind": "command",
        "contract_name": "ExecuteTask",
        "contract_version": "1.0",
        "created_at": _iso8601_utc(created_at),
        "correlation_id": str(correlation_id),
        "causation_id": None,
        "workflow_id": str(workflow_id),
        "task_id": str(task_id),
        "task_attempt_id": str(task_attempt_id),
        "producer": {
            "component": orchestrator_component,
            "instance_id": orchestrator_instance_id,
        },
        "payload": {
            "request_id": str(request_id),
            "input": input_text,
            "capability": selection.capability_name,
            "capability_version": selection.capability_version,
            "selected_agent": {
                "component": selection.implementation_identity,
                "instance_id": str(selection.agent_id),
            },
            "attempt_number": 1,
            "task_result_deadline": _iso8601_utc(task_result_deadline),
        },
    }
