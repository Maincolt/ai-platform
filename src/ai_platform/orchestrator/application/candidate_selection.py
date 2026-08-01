"""The seam between Orchestrator application services and the Capability
Registry (built independently this sprint; see docs/sprint-3/plan.md).

`SubmissionOrchestrator` depends only on `CandidateSelectorPort`, never on
`ai_platform.orchestrator.registry` directly, so the two work streams
integrate through this narrow interface (task 8 of the sprint plan).
"""

from datetime import datetime
from typing import Protocol

from ai_platform.orchestrator.domain.selection import SelectionIntent


class NoEligibleCandidateError(Exception):
    """No candidate satisfies declaration, compatibility, and freshness."""


class CandidateSelectionConfigurationError(Exception):
    """More than one eligible candidate; a first-slice configuration error
    (ADR-0008 Section 7), never a normal runtime condition."""


class CandidateSelectorPort(Protocol):
    def select(
        self,
        *,
        capability_name: str,
        capability_version: str,
        command_contract_name: str,
        command_contract_version: str,
        event_contract_names: tuple[str, ...],
        event_contract_versions: tuple[str, ...],
        environment: str,
        now: datetime,
    ) -> SelectionIntent:
        """Raise NoEligibleCandidateError or CandidateSelectionConfigurationError
        when no single eligible candidate exists."""
        ...
