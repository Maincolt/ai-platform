"""Typed identifiers shared across platform components (ADR-0004 Section 5).

All identifiers are lowercase UUIDv7 strings on the wire, per the schemas
under contracts/json-schema/v1/. These are NewType aliases for
static-typing clarity at module boundaries; they do not validate format at
runtime. Runtime format validation belongs to the contract/adapter
boundary (Phase 5/6), not domain construction.

Deliberately placed under shared/, not orchestrator/domain/: these
identifiers appear in the common message envelope (ADR-0004) used by both
the Orchestrator and Agent sides, which are separate deployables that must
not import each other's internal modules (ADR-0001, ADR-0007 Section 1).
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
