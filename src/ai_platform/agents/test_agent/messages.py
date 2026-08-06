"""Building TaskCompleted/TaskFailed event payloads from domain data.

Matches contracts/json-schema/v1/task_completed.schema.json and
task_failed.schema.json (Sprint 1) and vertical-slice-01.md Section 10.
Kept as small pure functions, separate from the lifecycle class, so their
shape can be tested and evolved independently of execution orchestration.
"""

from collections.abc import Mapping
from datetime import datetime

from ai_platform.shared.identifiers import (
    AgentId,
    CorrelationId,
    MessageId,
    TaskAttemptId,
    TaskId,
    WorkflowId,
)


def _iso8601_utc(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_task_completed_payload(
    *,
    message_id: str,
    correlation_id: CorrelationId,
    causation_id: MessageId,
    workflow_id: WorkflowId,
    task_id: TaskId,
    task_attempt_id: TaskAttemptId,
    agent_component: str,
    agent_instance_id: AgentId,
    text: str,
    result_data: Mapping[str, object],
    capability_name: str,
    capability_version: str,
    completed_at: datetime,
    created_at: datetime,
) -> dict[str, object]:
    """Build the immutable TaskCompleted envelope+payload dict."""
    return {
        "message_id": message_id,
        "message_kind": "event",
        "contract_name": "TaskCompleted",
        "contract_version": "1.0",
        "created_at": _iso8601_utc(created_at),
        "correlation_id": str(correlation_id),
        "causation_id": str(causation_id),
        "workflow_id": str(workflow_id),
        "task_id": str(task_id),
        "task_attempt_id": str(task_attempt_id),
        "producer": {
            "component": agent_component,
            "instance_id": str(agent_instance_id),
        },
        "payload": {
            "text": text,
            "result": dict(result_data),
            "completed_at": _iso8601_utc(completed_at),
            "capability": capability_name,
            "capability_version": capability_version,
            "agent": {
                "component": agent_component,
                "instance_id": str(agent_instance_id),
            },
        },
    }


def build_task_failed_payload(
    *,
    message_id: str,
    correlation_id: CorrelationId,
    causation_id: MessageId,
    workflow_id: WorkflowId,
    task_id: TaskId,
    task_attempt_id: TaskAttemptId,
    agent_component: str,
    agent_instance_id: AgentId,
    failure_code: str,
    summary: str,
    capability_name: str,
    capability_version: str,
    failed_at: datetime,
    created_at: datetime,
) -> dict[str, object]:
    """Build the immutable TaskFailed envelope+payload dict."""
    return {
        "message_id": message_id,
        "message_kind": "event",
        "contract_name": "TaskFailed",
        "contract_version": "1.0",
        "created_at": _iso8601_utc(created_at),
        "correlation_id": str(correlation_id),
        "causation_id": str(causation_id),
        "workflow_id": str(workflow_id),
        "task_id": str(task_id),
        "task_attempt_id": str(task_attempt_id),
        "producer": {
            "component": agent_component,
            "instance_id": str(agent_instance_id),
        },
        "payload": {
            "failure_code": failure_code,
            "summary": summary,
            "failed_at": _iso8601_utc(failed_at),
            "capability": capability_name,
            "capability_version": capability_version,
            "agent": {
                "component": agent_component,
                "instance_id": str(agent_instance_id),
            },
        },
    }
