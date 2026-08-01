"""Trusted request context (vertical-slice-01.md Section 4,
"Local-Development API Boundary").

LocalDevelopmentAuthorizationPolicy has no client credential and does not
identify an individual human. It resolves every API call to one synthetic,
nonportable principal: all callers within this boundary are
indistinguishable and share replay and ownership authority. This is the
*only* policy implementation in this slice -- multi-principal
authorization and owner-mismatch disclosure paths are structurally
unreachable and intentionally not implemented (see docs/sprint-5/consilium.md).
"""

from dataclasses import dataclass

from ai_platform.shared.identifiers import ActorId, IdempotencyScopeId, OwnerSubjectId

_SYNTHETIC_ENVIRONMENT = "local-development"
_SYNTHETIC_SCOPE_ID = IdempotencyScopeId("local-development-synthetic-scope")
_SYNTHETIC_ACTOR_ID = ActorId("local-development-synthetic-actor")
_SYNTHETIC_OWNER_ID = OwnerSubjectId("local-development-synthetic-owner")
_POLICY_IDENTITY = "LocalDevelopmentAuthorizationPolicy"
_POLICY_REVISION = "1"


@dataclass(frozen=True, slots=True)
class TrustedRequestContext:
    """Everything the trusted security adapter resolves for one API call."""

    environment: str
    idempotency_scope_id: IdempotencyScopeId
    current_actor_id: ActorId
    owner_subject_id: OwnerSubjectId
    policy_identity: str
    policy_revision: str
    semantic_operation: str


class LocalDevelopmentAuthorizationPolicy:
    """Resolves the one fixed synthetic context for every call.

    No client credential is validated because none exists in this policy.
    The synthetic scope/actor/owner values are internal and can never be
    supplied or learned by a client (ADR-0010 Section 4).
    """

    def resolve(self, *, semantic_operation: str) -> TrustedRequestContext:
        return TrustedRequestContext(
            environment=_SYNTHETIC_ENVIRONMENT,
            idempotency_scope_id=_SYNTHETIC_SCOPE_ID,
            current_actor_id=_SYNTHETIC_ACTOR_ID,
            owner_subject_id=_SYNTHETIC_OWNER_ID,
            policy_identity=_POLICY_IDENTITY,
            policy_revision=_POLICY_REVISION,
            semantic_operation=semantic_operation,
        )
