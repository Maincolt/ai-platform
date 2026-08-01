"""Unit tests for snapshot loading, validation, and conflict rejection.

Covers ADR-0008 Sections 2 and 7: complete validation, duplicate/conflict
rejection for enabled declarations, and disabled-duplicate tolerance.
"""

from __future__ import annotations

import pytest

from ai_platform.orchestrator.domain.identifiers import AgentId
from ai_platform.orchestrator.registry.declarations import CapabilityBinding
from ai_platform.orchestrator.registry.snapshot import (
    RegistrySnapshot,
    RegistryValidationError,
    load_registry_snapshot,
)

AGENT_A = AgentId("019fbdd6-ab3d-77aa-8e61-4c3bc6d53f69")
AGENT_B = AgentId("019fbdd6-ab3d-77aa-8e61-4c3903e582ad")


def _binding(
    *,
    agent_id: AgentId = AGENT_A,
    capability_name: str = "text.word-count",
    capability_version: str = "1.0",
    environment: str = "production",
    enabled: bool = True,
    digest: str = "sha256:abc",
) -> CapabilityBinding:
    return CapabilityBinding(
        capability_name=capability_name,
        capability_version=capability_version,
        command_contract_name="ExecuteTask",
        command_contract_versions=("1.0",),
        event_contract_names=("TaskCompleted", "TaskFailed"),
        event_contract_versions=("1.0",),
        agent_id=agent_id,
        implementation_identity="word-count-agent",
        implementation_version="0.1.0",
        deployment_declaration_digest=digest,
        environment=environment,
        enabled=enabled,
    )


def test_valid_distinct_bindings_load_successfully() -> None:
    bindings = [
        _binding(agent_id=AGENT_A),
        _binding(agent_id=AGENT_B),
        _binding(agent_id=AGENT_A, environment="staging"),
        _binding(agent_id=AGENT_A, capability_version="2.0"),
    ]

    snapshot = load_registry_snapshot(bindings, revision="rev-1")

    assert isinstance(snapshot, RegistrySnapshot)
    assert snapshot.revision == "rev-1"
    assert snapshot.bindings == tuple(bindings)


def test_empty_bindings_load_successfully() -> None:
    snapshot = load_registry_snapshot([], revision="rev-1")
    assert snapshot.bindings == ()


def test_duplicate_enabled_bindings_raise() -> None:
    bindings = [
        _binding(digest="sha256:one"),
        _binding(digest="sha256:two"),
    ]

    with pytest.raises(RegistryValidationError, match="conflicting enabled declarations"):
        load_registry_snapshot(bindings, revision="rev-1")


def test_disabled_duplicate_does_not_raise() -> None:
    bindings = [
        _binding(enabled=True, digest="sha256:enabled"),
        _binding(enabled=False, digest="sha256:disabled"),
    ]

    snapshot = load_registry_snapshot(bindings, revision="rev-1")

    assert len(snapshot.bindings) == 2


def test_two_disabled_duplicates_do_not_raise() -> None:
    bindings = [
        _binding(enabled=False, digest="sha256:one"),
        _binding(enabled=False, digest="sha256:two"),
    ]

    snapshot = load_registry_snapshot(bindings, revision="rev-1")

    assert len(snapshot.bindings) == 2


@pytest.mark.parametrize(
    "field",
    ["capability_name", "capability_version", "agent_id", "environment"],
)
def test_empty_required_field_raises(field: str) -> None:
    kwargs = {field: AgentId("") if field == "agent_id" else ""}
    bindings = [_binding(**kwargs)]  # type: ignore[arg-type]

    with pytest.raises(RegistryValidationError, match="empty required field"):
        load_registry_snapshot(bindings, revision="rev-1")


def test_empty_revision_raises() -> None:
    with pytest.raises(RegistryValidationError, match="revision"):
        load_registry_snapshot([_binding()], revision="")


def test_snapshot_is_frozen() -> None:
    snapshot = load_registry_snapshot([_binding()], revision="rev-1")
    with pytest.raises((AttributeError, TypeError)):
        snapshot.revision = "rev-2"  # type: ignore[misc]
