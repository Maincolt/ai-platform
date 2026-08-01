"""Accepted-request arbitration port (vertical-slice-01.md Section 6, ADR-0011)."""

from typing import Protocol

from ai_platform.orchestrator.domain.accepted_request import (
    AcceptanceEvidence,
    AcceptedRequestKey,
)
from ai_platform.orchestrator.domain.identifiers import WorkflowId


class AcceptedRequestRepositoryPort(Protocol):
    """Atomic arbitration of the composite accepted-request key.

    Implementations must resolve concurrent submissions of the same key to
    exactly one winner through database-enforced uniqueness, never a
    process-local lock or existence precheck (ADR-0006 Section 5).
    """

    def create_or_resolve(
        self,
        key: AcceptedRequestKey,
        evidence: AcceptanceEvidence,
        workflow_id: WorkflowId,
    ) -> tuple[WorkflowId, AcceptanceEvidence, bool]:
        """Create the mapping if new, or resolve the existing one.

        Returns `(resolved_workflow_id, resolved_evidence, is_new)`. Callers
        compare the submitted evidence's fingerprint against the resolved
        evidence's fingerprint (see
        `ai_platform.orchestrator.domain.accepted_request.compare_fingerprint`)
        to classify a resolved-but-not-new result as an equivalent replay or
        a fingerprint conflict.
        """
        ...
