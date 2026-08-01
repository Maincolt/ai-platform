"""Immutable registry snapshot and validation (ADR-0008 Sections 2, 7).

`load_registry_snapshot` performs complete declaration validation and
conflict rejection, then produces one immutable in-process snapshot derived
from a complete Registry revision. Missing, partial, conflicting, or invalid
data is rejected wholesale (fail-closed); no partially valid subset is
activated (ADR-0008 Section 7).

A conflict is more than one *enabled* declaration for the same
(agent_id, capability_name, capability_version, environment): a disabled
declaration can coexist because it can never be selected.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from ai_platform.orchestrator.registry.declarations import CapabilityBinding


class RegistryValidationError(Exception):
    """Raised when declarations are invalid, incomplete, or conflicting."""


@dataclass(frozen=True, slots=True)
class RegistrySnapshot:
    """One immutable, validated snapshot of a complete Registry revision."""

    revision: str
    bindings: tuple[CapabilityBinding, ...]


def load_registry_snapshot(
    raw_bindings: Sequence[CapabilityBinding], *, revision: str
) -> RegistrySnapshot:
    """Validate declarations and reject duplicates/conflicts (ADR-0008 2, 7).

    Rejects any binding with an empty required identity field, and any pair
    of *enabled* bindings that share the same
    (agent_id, capability_name, capability_version, environment) tuple.
    Disabled duplicates are permitted because a disabled declaration can
    never be selected. Validation is all-or-nothing.
    """
    if not revision:
        raise RegistryValidationError("registry revision must be a non-empty string")

    for binding in raw_bindings:
        _validate_required_fields(binding)

    _reject_enabled_conflicts(raw_bindings)

    return RegistrySnapshot(revision=revision, bindings=tuple(raw_bindings))


def _validate_required_fields(binding: CapabilityBinding) -> None:
    required = {
        "capability_name": binding.capability_name,
        "capability_version": binding.capability_version,
        "agent_id": binding.agent_id,
        "environment": binding.environment,
    }
    empty = [name for name, value in required.items() if not value]
    if empty:
        raise RegistryValidationError(
            f"binding has empty required field(s) {sorted(empty)}: "
            f"agent_id={binding.agent_id!r}, capability_name={binding.capability_name!r}, "
            f"capability_version={binding.capability_version!r}, "
            f"environment={binding.environment!r}"
        )


def _reject_enabled_conflicts(bindings: Sequence[CapabilityBinding]) -> None:
    seen: dict[tuple[str, str, str, str], CapabilityBinding] = {}
    for binding in bindings:
        if not binding.enabled:
            continue
        key = (
            binding.agent_id,
            binding.capability_name,
            binding.capability_version,
            binding.environment,
        )
        existing = seen.get(key)
        if existing is not None:
            raise RegistryValidationError(
                "conflicting enabled declarations for the same "
                "(agent_id, capability_name, capability_version, environment): "
                f"agent_id={binding.agent_id!r}, capability_name={binding.capability_name!r}, "
                f"capability_version={binding.capability_version!r}, "
                f"environment={binding.environment!r}; conflicting digests "
                f"{existing.deployment_declaration_digest!r} and "
                f"{binding.deployment_declaration_digest!r}"
            )
        seen[key] = binding
