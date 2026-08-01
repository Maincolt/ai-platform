"""Capability declarations (ADR-0008 Section 3; vertical-slice-01.md Section 7).

A `CapabilityBinding` is one trusted, already-parsed registry declaration.
It identifies the capability, the accepted command contract and its exact
supported versions, the produced terminal-event contracts and versions, the
logical Agent deployment, its implementation and declaration provenance, the
environment, and administrative enablement. Compatibility is always declared
and validated exactly; syntax alone never proves it (ADR-0008 Section 5).
"""

from dataclasses import dataclass

from ai_platform.shared.identifiers import AgentId


@dataclass(frozen=True, slots=True)
class CapabilityBinding:
    """One trusted logical registry binding for a capability deployment."""

    capability_name: str
    capability_version: str
    command_contract_name: str
    command_contract_versions: tuple[str, ...]
    event_contract_names: tuple[str, ...]
    event_contract_versions: tuple[str, ...]
    agent_id: AgentId
    implementation_identity: str
    implementation_version: str
    deployment_declaration_digest: str
    environment: str
    enabled: bool
