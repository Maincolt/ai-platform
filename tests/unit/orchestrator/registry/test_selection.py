"""Unit tests for deterministic candidate selection (ADR-0008 Sections 5, 7)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from ai_platform.orchestrator.domain.selection import SelectionIntent
from ai_platform.orchestrator.registry.availability import (
    AvailabilityClassification,
    AvailabilityObservation,
)
from ai_platform.orchestrator.registry.declarations import CapabilityBinding
from ai_platform.orchestrator.registry.selection import (
    AmbiguousCandidateError,
    NoEligibleAgentError,
    select_candidate,
)
from ai_platform.orchestrator.registry.snapshot import load_registry_snapshot
from ai_platform.shared.identifiers import AgentId

NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
OBSERVED_AT = NOW - timedelta(seconds=5)

AGENT_A = AgentId("019fbdd6-ab3d-77aa-8e61-4c3bc6d53f69")
AGENT_B = AgentId("019fbdd6-ab3d-77aa-8e61-4c3903e582ad")


# ---------------------------------------------------------------------------
# In-memory AvailabilityPort fake (test-owned, dict-based)
# ---------------------------------------------------------------------------
@dataclass
class FakeAvailabilityPort:
    """Maps agent_id to a fixed observation; defaults to READY within TTL."""

    observations: dict[AgentId, AvailabilityObservation] = field(default_factory=dict)
    default: AvailabilityObservation = field(
        default_factory=lambda: AvailabilityObservation(
            classification=AvailabilityClassification.READY,
            observed_at=OBSERVED_AT,
            ttl_seconds=30.0,
        )
    )

    def observe(
        self, agent_id: AgentId, capability_name: str, capability_version: str
    ) -> AvailabilityObservation:
        return self.observations.get(agent_id, self.default)


def _binding(
    *,
    agent_id: AgentId = AGENT_A,
    capability_name: str = "text.word-count",
    capability_version: str = "1.0",
    command_contract_name: str = "ExecuteTask",
    command_contract_versions: tuple[str, ...] = ("1.0",),
    event_contract_names: tuple[str, ...] = ("TaskCompleted", "TaskFailed"),
    event_contract_versions: tuple[str, ...] = ("1.0",),
    environment: str = "production",
    enabled: bool = True,
    digest: str = "sha256:abc",
) -> CapabilityBinding:
    return CapabilityBinding(
        capability_name=capability_name,
        capability_version=capability_version,
        command_contract_name=command_contract_name,
        command_contract_versions=command_contract_versions,
        event_contract_names=event_contract_names,
        event_contract_versions=event_contract_versions,
        agent_id=agent_id,
        implementation_identity="word-count-agent",
        implementation_version="0.1.0",
        deployment_declaration_digest=digest,
        environment=environment,
        enabled=enabled,
    )


def _select(
    bindings: list[CapabilityBinding],
    *,
    port: FakeAvailabilityPort | None = None,
    command_contract_version: str = "1.0",
    event_contract_names: tuple[str, ...] = ("TaskCompleted",),
    event_contract_versions: tuple[str, ...] = ("1.0",),
    environment: str = "production",
) -> SelectionIntent:
    snapshot = load_registry_snapshot(bindings, revision="rev-1")
    return select_candidate(
        snapshot,
        capability_name="text.word-count",
        capability_version="1.0",
        command_contract_name="ExecuteTask",
        command_contract_version=command_contract_version,
        event_contract_names=event_contract_names,
        event_contract_versions=event_contract_versions,
        environment=environment,
        availability_port=port or FakeAvailabilityPort(),
        now=NOW,
        selection_policy_version="policy-1",
    )


def test_exactly_one_eligible_returns_correct_selection_intent() -> None:
    intent = _select([_binding()])

    assert isinstance(intent, SelectionIntent)
    assert intent.agent_id == AGENT_A
    assert intent.capability_name == "text.word-count"
    assert intent.capability_version == "1.0"
    assert intent.implementation_identity == "word-count-agent"
    assert intent.implementation_version == "0.1.0"
    assert intent.command_contract_version == "1.0"
    assert intent.event_contract_versions == ("1.0",)
    assert intent.registry_revision == "rev-1"
    assert intent.deployment_declaration_digest == "sha256:abc"
    assert intent.selection_policy_version == "policy-1"
    assert intent.availability_classification == "READY"
    assert intent.observed_at == OBSERVED_AT
    assert intent.selected_at == NOW


def test_no_binding_for_capability_raises_no_eligible() -> None:
    binding = _binding(capability_name="text.other")
    with pytest.raises(NoEligibleAgentError, match="text.word-count"):
        _select([binding])


def test_selection_observes_availability_exactly_once_per_eligible_binding() -> None:
    """Regression test: select_candidate must not call observe() a second
    time for the winning candidate after the eligibility pass, since a
    changing/non-idempotent port could otherwise return a different
    observation than the one that actually passed the freshness check."""

    @dataclass
    class CountingAvailabilityPort:
        call_count: int = 0

        def observe(
            self, agent_id: AgentId, capability_name: str, capability_version: str
        ) -> AvailabilityObservation:
            self.call_count += 1
            # A different observed_at on every call simulates a live,
            # changing signal -- if select_candidate observed twice, the
            # second (later) observed_at would leak into the result.
            return AvailabilityObservation(
                classification=AvailabilityClassification.READY,
                observed_at=OBSERVED_AT - timedelta(seconds=self.call_count),
                ttl_seconds=30.0,
            )

    port = CountingAvailabilityPort()
    snapshot = load_registry_snapshot([_binding()], revision="rev-1")
    intent = select_candidate(
        snapshot,
        capability_name="text.word-count",
        capability_version="1.0",
        command_contract_name="ExecuteTask",
        command_contract_version="1.0",
        event_contract_names=("TaskCompleted",),
        event_contract_versions=("1.0",),
        environment="production",
        availability_port=port,
        now=NOW,
        selection_policy_version="policy-1",
    )

    assert port.call_count == 1
    assert intent.observed_at == OBSERVED_AT - timedelta(seconds=1)


def test_disabled_binding_raises_no_eligible() -> None:
    with pytest.raises(NoEligibleAgentError):
        _select([_binding(enabled=False)])


def test_wrong_environment_raises_no_eligible() -> None:
    with pytest.raises(NoEligibleAgentError):
        _select([_binding(environment="staging")])


def test_wrong_capability_version_raises_no_eligible() -> None:
    with pytest.raises(NoEligibleAgentError):
        _select([_binding(capability_version="2.0")])


@pytest.mark.parametrize(
    "classification",
    [
        AvailabilityClassification.STALE,
        AvailabilityClassification.UNKNOWN,
        AvailabilityClassification.UNAVAILABLE,
        AvailabilityClassification.DRAINING,
    ],
)
def test_not_ready_availability_raises_no_eligible(
    classification: AvailabilityClassification,
) -> None:
    port = FakeAvailabilityPort(
        default=AvailabilityObservation(
            classification=classification,
            observed_at=OBSERVED_AT,
            ttl_seconds=30.0,
        )
    )
    with pytest.raises(NoEligibleAgentError):
        _select([_binding()], port=port)


def test_stale_ready_observation_raises_no_eligible() -> None:
    port = FakeAvailabilityPort(
        default=AvailabilityObservation(
            classification=AvailabilityClassification.READY,
            observed_at=NOW - timedelta(seconds=100),
            ttl_seconds=30.0,
        )
    )
    with pytest.raises(NoEligibleAgentError):
        _select([_binding()], port=port)


def test_command_contract_version_mismatch_is_ineligible() -> None:
    binding = _binding(command_contract_versions=("1.0",))
    with pytest.raises(NoEligibleAgentError):
        _select([binding], command_contract_version="2.0")


def test_command_contract_name_mismatch_is_ineligible() -> None:
    binding = _binding(command_contract_name="OtherCommand")
    with pytest.raises(NoEligibleAgentError):
        _select([binding])


def test_missing_required_event_contract_name_is_ineligible() -> None:
    binding = _binding(event_contract_names=("TaskFailed",))
    with pytest.raises(NoEligibleAgentError):
        _select([binding], event_contract_names=("TaskCompleted",))


def test_missing_required_event_contract_version_is_ineligible() -> None:
    binding = _binding(event_contract_versions=("1.0",))
    with pytest.raises(NoEligibleAgentError):
        _select([binding], event_contract_versions=("2.0",))


def test_two_eligible_bindings_raise_ambiguous() -> None:
    bindings = [_binding(agent_id=AGENT_A), _binding(agent_id=AGENT_B)]
    with pytest.raises(AmbiguousCandidateError) as exc_info:
        _select(bindings)

    message = str(exc_info.value)
    assert AGENT_A in message
    assert AGENT_B in message


def test_second_binding_unavailable_leaves_exactly_one_eligible() -> None:
    bindings = [_binding(agent_id=AGENT_A), _binding(agent_id=AGENT_B)]
    port = FakeAvailabilityPort(
        observations={
            AGENT_B: AvailabilityObservation(
                classification=AvailabilityClassification.UNAVAILABLE,
                observed_at=OBSERVED_AT,
                ttl_seconds=30.0,
            )
        }
    )

    intent = _select(bindings, port=port)

    assert intent.agent_id == AGENT_A
