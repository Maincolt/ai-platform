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
    readiness_url: str
    """This deployment's own readiness endpoint (ADR-0017 Decision 5).

    Per-binding rather than a single platform-wide value: distinct Agent
    deployments are not uniformly reachable at the same address (e.g. one
    deployment sharing its platform process's network namespace vs. another
    reachable at its own Compose service DNS name), so no single URL can
    serve every binding.
    """
