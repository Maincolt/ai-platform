"""Workflow repository ports (ADR-0006 Section 4).

Named after the transactions in vertical-slice-01.md Section 11, not
generic CRUD verbs, per ADR-0006's explicit rejection of a generic
create/read/update shape for these capabilities.
"""

from typing import Protocol

from ai_platform.orchestrator.domain.identifiers import WorkflowId
from ai_platform.orchestrator.domain.workflow import Workflow


class WorkflowRepositoryPort(Protocol):
    """Current-snapshot storage with compare-and-set by revision."""

    def get_by_id(self, workflow_id: WorkflowId) -> Workflow | None:
        """Return the current snapshot, or None if it does not exist."""
        ...

    def save_new(self, workflow: Workflow) -> None:
        """Atomically persist a newly accepted workflow's initial snapshot
        and history (the none -> RECEIVED -> PENDING -> DISPATCHED
        submission transaction, Section 11)."""
        ...

    def save_transition(self, workflow: Workflow, *, expected_revision: int) -> None:
        """Compare-and-set the snapshot and append its latest transition.

        Implementations must raise a stable conflict classification (not a
        database-specific exception) if `expected_revision` no longer
        matches the stored revision.
        """
        ...
