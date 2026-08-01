"""Immutable Agent selection intent (vertical-slice-01.md Section 7).

Frozen before the submission transaction commits atomically with the
workflow. Transaction retries preserve it; it is never recomputed for an
existing workflow.
"""

from dataclasses import dataclass
from datetime import datetime

from ai_platform.orchestrator.domain.identifiers import AgentId


@dataclass(frozen=True, slots=True)
class SelectionIntent:
    """Complete evidence for one deterministic Agent selection decision."""

    agent_id: AgentId
    capability_name: str
    capability_version: str
    implementation_identity: str
    implementation_version: str
    command_contract_version: str
    event_contract_versions: tuple[str, ...]
    registry_revision: str
    deployment_declaration_digest: str
    selection_policy_version: str
    availability_classification: str
    observed_at: datetime
    selected_at: datetime
