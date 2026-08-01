"""Typed identifiers for workflow domain objects.

All identifiers are lowercase UUIDv7 strings on the wire, per ADR-0004
Section 5 and the schemas under contracts/json-schema/v1/. These are
NewType aliases for static-typing clarity at module boundaries; they do not
validate format at runtime. Runtime format validation belongs to the
contract/adapter boundary (Phase 5/6), not domain construction.
"""

from typing import NewType

WorkflowId = NewType("WorkflowId", str)
TaskId = NewType("TaskId", str)
TaskAttemptId = NewType("TaskAttemptId", str)
RequestId = NewType("RequestId", str)
CorrelationId = NewType("CorrelationId", str)
MessageId = NewType("MessageId", str)
ActorId = NewType("ActorId", str)
OwnerSubjectId = NewType("OwnerSubjectId", str)
IdempotencyScopeId = NewType("IdempotencyScopeId", str)
AgentId = NewType("AgentId", str)
