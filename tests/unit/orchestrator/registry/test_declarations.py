"""Unit tests for `CapabilityBinding` declarations (ADR-0008 Section 3)."""

from __future__ import annotations

import pytest

from ai_platform.orchestrator.registry.declarations import CapabilityBinding
from ai_platform.shared.identifiers import AgentId


def _binding() -> CapabilityBinding:
    return CapabilityBinding(
        capability_name="text.word-count",
        capability_version="1.0",
        command_contract_name="ExecuteTask",
        command_contract_versions=("1.0",),
        event_contract_names=("TaskCompleted", "TaskFailed"),
        event_contract_versions=("1.0",),
        agent_id=AgentId("019fbdd6-ab3d-77aa-8e61-4c3bc6d53f69"),
        implementation_identity="word-count-agent",
        implementation_version="0.1.0",
        deployment_declaration_digest="sha256:abc",
        environment="production",
        enabled=True,
    )


def test_binding_is_frozen() -> None:
    binding = _binding()
    with pytest.raises((AttributeError, TypeError)):
        binding.enabled = False  # type: ignore[misc]


def test_binding_uses_slots() -> None:
    binding = _binding()
    assert not hasattr(binding, "__dict__")


def test_binding_equality_is_by_value() -> None:
    assert _binding() == _binding()
