"""Internal async SQL helpers for accepted-request arbitration."""

from datetime import datetime

from ai_platform.adapters.persistence.connection import AsyncDbConnection
from ai_platform.orchestrator.domain.accepted_request import (
    AcceptanceEvidence,
    AcceptedRequestKey,
)
from ai_platform.ports.persistence.errors import PermanentPersistenceError
from ai_platform.ports.persistence.transactions import AcceptedRequestResolution
from ai_platform.shared.identifiers import (
    ActorId,
    IdempotencyScopeId,
    OwnerSubjectId,
    RequestId,
    WorkflowId,
)

_COLUMNS = """
environment, operation, idempotency_scope_id, request_id, workflow_id,
acceptance_actor_id, accepted_owner_subject_id, current_owner_subject_id,
fingerprint, fingerprint_policy_version, policy_identity, policy_revision,
policy_decision, scope_mapping_revision, authorization_evidence, accepted_at
"""


async def insert_accepted_request(
    connection: AsyncDbConnection,
    key: AcceptedRequestKey,
    evidence: AcceptanceEvidence,
    workflow_id: WorkflowId,
) -> AcceptedRequestResolution | None:
    row = await (
        await connection.execute(
            f"""
            INSERT INTO orchestrator.accepted_requests (
                environment, operation, idempotency_scope_id, request_id, workflow_id,
                acceptance_actor_id, accepted_owner_subject_id, current_owner_subject_id,
                fingerprint, fingerprint_policy_version, policy_identity, policy_revision,
                policy_decision, scope_mapping_revision, authorization_evidence, accepted_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (environment, operation, idempotency_scope_id, request_id)
            DO NOTHING
            RETURNING {_COLUMNS}
            """,
            (
                key.environment,
                key.operation,
                key.idempotency_scope_id,
                key.request_id,
                workflow_id,
                evidence.acceptance_actor_id,
                evidence.accepted_owner_subject_id,
                evidence.current_owner_subject_id,
                evidence.fingerprint,
                evidence.fingerprint_policy_version,
                evidence.policy_identity,
                evidence.policy_revision,
                evidence.policy_decision,
                evidence.scope_mapping_revision,
                evidence.authorization_evidence,
                evidence.accepted_at,
            ),
        )
    ).fetchone()
    return None if row is None else resolution_from_row(row)


async def select_accepted_request(
    connection: AsyncDbConnection, key: AcceptedRequestKey
) -> AcceptedRequestResolution | None:
    row = await (
        await connection.execute(
            f"""
            SELECT {_COLUMNS}
            FROM orchestrator.accepted_requests
            WHERE environment = %s AND operation = %s
              AND idempotency_scope_id = %s AND request_id = %s
            """,
            (key.environment, key.operation, key.idempotency_scope_id, key.request_id),
        )
    ).fetchone()
    return None if row is None else resolution_from_row(row)


def resolution_from_row(row: tuple[object, ...]) -> AcceptedRequestResolution:
    if len(row) != 16 or not isinstance(row[15], datetime):
        raise PermanentPersistenceError("Stored accepted-request data is invalid.")
    key = AcceptedRequestKey(
        environment=str(row[0]),
        operation=str(row[1]),
        idempotency_scope_id=IdempotencyScopeId(str(row[2])),
        request_id=RequestId(str(row[3])),
    )
    evidence = AcceptanceEvidence(
        acceptance_actor_id=ActorId(str(row[5])),
        accepted_owner_subject_id=OwnerSubjectId(str(row[6])),
        current_owner_subject_id=OwnerSubjectId(str(row[7])),
        fingerprint=str(row[8]),
        fingerprint_policy_version=str(row[9]),
        policy_identity=str(row[10]),
        policy_revision=str(row[11]),
        policy_decision=str(row[12]),
        scope_mapping_revision=str(row[13]),
        authorization_evidence=str(row[14]),
        accepted_at=row[15],
    )
    return AcceptedRequestResolution(
        key=key, workflow_id=WorkflowId(str(row[4])), evidence=evidence
    )
