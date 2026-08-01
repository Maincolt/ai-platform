"""Adapter binding the Capability Registry to `CandidateSelectorPort`.

This is the integration seam between the two Sprint 3 work streams: the
Registry module (built independently against the fixed interface spec) and
the Orchestrator application services, which depend only on
`CandidateSelectorPort` (see docs/sprint-3/plan.md task 8).
"""

from dataclasses import dataclass
from datetime import datetime

from ai_platform.orchestrator.application.candidate_selection import (
    CandidateSelectionConfigurationError,
    CandidateSelectorPort,
    NoEligibleCandidateError,
)
from ai_platform.orchestrator.domain.selection import SelectionIntent
from ai_platform.orchestrator.registry.availability import AvailabilityPort
from ai_platform.orchestrator.registry.selection import (
    AmbiguousCandidateError,
    NoEligibleAgentError,
    select_candidate,
)
from ai_platform.orchestrator.registry.snapshot import RegistrySnapshot


@dataclass(frozen=True, slots=True)
class RegistryCandidateSelector(CandidateSelectorPort):
    """Binds one immutable `RegistrySnapshot` and `AvailabilityPort` to the
    `CandidateSelectorPort` interface `SubmissionOrchestrator` depends on.

    Translates the Registry's own exceptions into the application-owned
    ones so `SubmissionOrchestrator` never needs to import from
    `ai_platform.orchestrator.registry` directly.
    """

    snapshot: RegistrySnapshot
    availability_port: AvailabilityPort
    selection_policy_version: str

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
        try:
            return select_candidate(
                self.snapshot,
                capability_name=capability_name,
                capability_version=capability_version,
                command_contract_name=command_contract_name,
                command_contract_version=command_contract_version,
                event_contract_names=event_contract_names,
                event_contract_versions=event_contract_versions,
                environment=environment,
                availability_port=self.availability_port,
                now=now,
                selection_policy_version=self.selection_policy_version,
            )
        except NoEligibleAgentError as exc:
            raise NoEligibleCandidateError(str(exc)) from exc
        except AmbiguousCandidateError as exc:
            raise CandidateSelectionConfigurationError(str(exc)) from exc
