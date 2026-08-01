"""Deterministic exactly-one candidate selection (ADR-0008 Sections 5, 7).

`select_candidate` applies the first-slice compatibility model with exact
matching and no inference: capability name/version exact, requested command
contract in the declaration's exact supported set, required terminal event
contracts within the declared produced set, enabled for the current
environment, and a sufficiently fresh ready availability observation
(ADR-0008 Section 5).

Zero eligible candidates fail closed (`NoEligibleAgentError`). More than one
is a configuration error in this slice (`AmbiguousCandidateError`, ADR-0008
Section 7). Exactly one produces a frozen `SelectionIntent` capturing the
complete evidence for the decision. `now` is always explicit (see
docs/sprint-3/consilium.md, disagreement 2).
"""

from datetime import datetime

from ai_platform.orchestrator.domain.selection import SelectionIntent
from ai_platform.orchestrator.registry.availability import AvailabilityPort, is_fresh
from ai_platform.orchestrator.registry.declarations import CapabilityBinding
from ai_platform.orchestrator.registry.snapshot import RegistrySnapshot


class NoEligibleAgentError(Exception):
    """Raised when no declaration is an eligible candidate (fail-closed)."""


class AmbiguousCandidateError(Exception):
    """Raised when more than one declaration is eligible (config error)."""


def select_candidate(
    snapshot: RegistrySnapshot,
    *,
    capability_name: str,
    capability_version: str,
    command_contract_name: str,
    command_contract_version: str,
    event_contract_names: tuple[str, ...],
    event_contract_versions: tuple[str, ...],
    environment: str,
    availability_port: AvailabilityPort,
    now: datetime,
    selection_policy_version: str,
) -> SelectionIntent:
    """Return the `SelectionIntent` for the single eligible candidate.

    Raises `NoEligibleAgentError` when none match and
    `AmbiguousCandidateError` when more than one matches.
    """
    eligible: list[tuple[CapabilityBinding, str]] = []
    for binding in snapshot.bindings:
        if not _matches_declaration(
            binding,
            capability_name=capability_name,
            capability_version=capability_version,
            command_contract_name=command_contract_name,
            command_contract_version=command_contract_version,
            event_contract_names=event_contract_names,
            event_contract_versions=event_contract_versions,
            environment=environment,
        ):
            continue
        observation = availability_port.observe(
            binding.agent_id, capability_name, capability_version
        )
        if not is_fresh(observation, now=now):
            continue
        eligible.append((binding, observation.classification.value))

    if not eligible:
        raise NoEligibleAgentError(
            "no eligible Agent for capability "
            f"{capability_name!r} {capability_version!r} in environment {environment!r}"
        )
    if len(eligible) > 1:
        conflicting = sorted(binding.agent_id for binding, _ in eligible)
        raise AmbiguousCandidateError(
            "more than one eligible Agent for capability "
            f"{capability_name!r} {capability_version!r} in environment {environment!r}: "
            f"{conflicting}"
        )

    binding, classification = eligible[0]
    observation = availability_port.observe(binding.agent_id, capability_name, capability_version)
    return SelectionIntent(
        agent_id=binding.agent_id,
        capability_name=binding.capability_name,
        capability_version=binding.capability_version,
        implementation_identity=binding.implementation_identity,
        implementation_version=binding.implementation_version,
        command_contract_version=command_contract_version,
        event_contract_versions=event_contract_versions,
        registry_revision=snapshot.revision,
        deployment_declaration_digest=binding.deployment_declaration_digest,
        selection_policy_version=selection_policy_version,
        availability_classification=classification,
        observed_at=observation.observed_at,
        selected_at=now,
    )


def _matches_declaration(
    binding: CapabilityBinding,
    *,
    capability_name: str,
    capability_version: str,
    command_contract_name: str,
    command_contract_version: str,
    event_contract_names: tuple[str, ...],
    event_contract_versions: tuple[str, ...],
    environment: str,
) -> bool:
    """Exact declared compatibility, excluding volatile availability."""
    if not binding.enabled:
        return False
    if binding.environment != environment:
        return False
    if binding.capability_name != capability_name:
        return False
    if binding.capability_version != capability_version:
        return False
    if binding.command_contract_name != command_contract_name:
        return False
    if command_contract_version not in binding.command_contract_versions:
        return False
    if not all(name in binding.event_contract_names for name in event_contract_names):
        return False
    return all(version in binding.event_contract_versions for version in event_contract_versions)
