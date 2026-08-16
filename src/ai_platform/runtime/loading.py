"""Bounded loaders for trusted Registry and canonical contract artifacts."""

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import cast
from urllib.parse import urlsplit

from ai_platform.orchestrator.registry.declarations import CapabilityBinding
from ai_platform.orchestrator.registry.snapshot import (
    RegistrySnapshot,
    RegistryValidationError,
    load_registry_snapshot,
)
from ai_platform.shared.identifiers import AgentId

_MESSAGE_SCHEMAS = {
    "ExecuteTask": "execute_task.schema.json",
    "TaskCompleted": "task_completed.schema.json",
    "TaskFailed": "task_failed.schema.json",
}
_CONTRACT_VERSION = "1.0"


class ArtifactLoadingError(ValueError):
    """A required Git-owned artifact is unavailable, malformed, or inconsistent."""


def _reject_duplicate_properties(pairs: list[tuple[str, object]]) -> dict[str, object]:
    document: dict[str, object] = {}
    for key, value in pairs:
        if key in document:
            raise ArtifactLoadingError("DUPLICATE_JSON_PROPERTY")
        document[key] = value
    return document


def _load_json_object(path: Path, *, maximum_bytes: int) -> dict[str, object]:
    if maximum_bytes < 1:
        raise ValueError("maximum_bytes must be positive")
    try:
        with path.open("rb") as stream:
            raw = stream.read(maximum_bytes + 1)
    except OSError:
        raise ArtifactLoadingError("ARTIFACT_UNAVAILABLE") from None
    if len(raw) > maximum_bytes:
        raise ArtifactLoadingError("ARTIFACT_TOO_LARGE")
    try:
        decoded = raw.decode("utf-8", errors="strict")
        parsed: object = json.loads(decoded, object_pairs_hook=_reject_duplicate_properties)
    except ArtifactLoadingError:
        raise
    except UnicodeDecodeError, json.JSONDecodeError, RecursionError:
        raise ArtifactLoadingError("ARTIFACT_MALFORMED") from None
    if not isinstance(parsed, dict):
        raise ArtifactLoadingError("ARTIFACT_NOT_OBJECT")
    return cast(dict[str, object], parsed)


def load_registry_artifact(path: Path, *, maximum_bytes: int = 262_144) -> RegistrySnapshot:
    """Load and atomically validate one complete configuration-backed Registry."""
    document = _load_json_object(path, maximum_bytes=maximum_bytes)
    revision = _required_string(document, "revision")
    raw_bindings = document.get("bindings")
    if not isinstance(raw_bindings, list):
        raise ArtifactLoadingError("REGISTRY_BINDINGS_NOT_ARRAY")
    typed_bindings = cast(list[object], raw_bindings)
    bindings = tuple(_parse_binding(item) for item in typed_bindings)
    try:
        return load_registry_snapshot(bindings, revision=revision)
    except RegistryValidationError:
        raise ArtifactLoadingError("REGISTRY_VALIDATION_FAILED") from None


# ADR-0014 Section 6 / ADR-0015 / ADR-0018: registry.json now carries one
# binding per built-in Agent class (text.word-count, text.summarize,
# code.review), not exactly one binding overall. Every Agent deployment
# (test-agent, summarize-agent, review-agent, ...) points
# AI_PLATFORM_AGENT_DECLARATION_PATH at the same shared registry.json and
# selects its own binding by (environment, agent_id, implementation_identity,
# deployment_declaration_digest) rather than by position/count.
_SUPPORTED_CAPABILITY_NAMES = frozenset(
    {
        "text.word-count",
        "text.summarize",
        "code.review",
        "ui.review",
        "architecture.review",
        "data.analysis",
        "technical.review",
        "security.review",
        "scrum.status",
        "assignment.route",
    }
)


def load_agent_deployment_declaration(
    path: Path,
    *,
    environment: str,
    agent_id: AgentId,
    implementation_identity: str,
    declaration_digest: str,
    maximum_bytes: int = 262_144,
) -> tuple[str, CapabilityBinding]:
    """Load one Git-owned declaration and match it to one Agent deployment's metadata."""
    snapshot = load_registry_artifact(path, maximum_bytes=maximum_bytes)
    # Select by agent_id, not position/count: each Agent deployment declares
    # its own agent_id, which is expected to identify exactly one binding in
    # the shared registry.json regardless of how many other Agent classes'
    # bindings are also present.
    candidates = [candidate for candidate in snapshot.bindings if candidate.agent_id == agent_id]
    if len(candidates) != 1:
        raise ArtifactLoadingError("AGENT_DECLARATION_REQUIRES_EXACTLY_ONE_BINDING_FOR_AGENT_ID")
    binding = candidates[0]
    expected = (
        binding.environment == environment
        and binding.implementation_identity == implementation_identity
        and binding.deployment_declaration_digest == declaration_digest
        and binding.enabled
        and binding.capability_name in _SUPPORTED_CAPABILITY_NAMES
        and binding.capability_version == "1.0"
        and binding.command_contract_name == "ExecuteTask"
        and binding.command_contract_versions == ("1.0",)
        and binding.event_contract_names == ("TaskCompleted", "TaskFailed")
        and binding.event_contract_versions == ("1.0", "1.0")
    )
    if not expected:
        raise ArtifactLoadingError("AGENT_DECLARATION_MISMATCH")
    return snapshot.revision, binding


def _parse_binding(value: object) -> CapabilityBinding:
    if not isinstance(value, dict):
        raise ArtifactLoadingError("REGISTRY_BINDING_NOT_OBJECT")
    binding = cast(dict[str, object], value)
    enabled = binding.get("enabled")
    if not isinstance(enabled, bool):
        raise ArtifactLoadingError("REGISTRY_BINDING_ENABLED_NOT_BOOLEAN")
    event_names = _required_string_tuple(binding, "event_contract_names")
    event_versions = _required_string_tuple(binding, "event_contract_versions")
    if len(event_names) != len(event_versions):
        raise ArtifactLoadingError("REGISTRY_EVENT_CONTRACT_LENGTH_MISMATCH")
    return CapabilityBinding(
        capability_name=_required_string(binding, "capability_name"),
        capability_version=_required_string(binding, "capability_version"),
        command_contract_name=_required_string(binding, "command_contract_name"),
        command_contract_versions=_required_string_tuple(binding, "command_contract_versions"),
        event_contract_names=event_names,
        event_contract_versions=event_versions,
        agent_id=AgentId(_required_string(binding, "agent_id")),
        implementation_identity=_required_string(binding, "implementation_identity"),
        implementation_version=_required_string(binding, "implementation_version"),
        deployment_declaration_digest=_required_string(binding, "deployment_declaration_digest"),
        environment=_required_string(binding, "environment"),
        enabled=enabled,
        readiness_url=_required_readiness_url(binding, "readiness_url"),
    )


def _required_readiness_url(document: Mapping[str, object], key: str) -> str:
    """A binding's own readiness endpoint (ADR-0017 Decision 5).

    Deliberately *not* restricted to a loopback literal, unlike this
    platform's other locally-exposed endpoints (`runtime/configuration.py`'s
    API-host/Agent-readiness-host checks): a binding is not necessarily
    reachable via a shared-network-namespace loopback trick the way
    `test-agent` is -- `summarize-agent`'s real address is its own Compose
    service DNS name (`summarize-agent:8100`), never loopback. The
    Registry artifact is a trusted, Git-owned deployment input (the same
    trust level as `docker-compose.yml` itself), not a boundary crossed by
    untrusted input, so only well-formedness (an `http(s)` scheme with a
    hostname) is validated here, not reachability topology.
    """
    value = _required_string(document, key)
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ArtifactLoadingError(f"REGISTRY_BINDING_READINESS_URL_MALFORMED:{key}")
    return value


def _required_string(document: Mapping[str, object], key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ArtifactLoadingError(f"MISSING_OR_INVALID_FIELD:{key}")
    return value


def _required_string_tuple(document: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = document.get(key)
    if not isinstance(value, list) or not value:
        raise ArtifactLoadingError(f"MISSING_OR_INVALID_FIELD:{key}")
    values = tuple(cast(list[object], value))
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise ArtifactLoadingError(f"MISSING_OR_INVALID_FIELD:{key}")
    return cast(tuple[str, ...], values)


def load_canonical_message_schemas(
    schema_directory: Path,
    *,
    contract_names: Iterable[str] = tuple(_MESSAGE_SCHEMAS),
    maximum_schema_bytes: int = 262_144,
) -> Mapping[tuple[str, str], Mapping[str, object]]:
    """Load exact first-slice schemas and verify their declared identities."""
    loaded: dict[tuple[str, str], Mapping[str, object]] = {}
    names = tuple(contract_names)
    if not names:
        raise ArtifactLoadingError("NO_CONTRACTS_REQUESTED")
    for contract_name in names:
        filename = _MESSAGE_SCHEMAS.get(contract_name)
        if filename is None:
            raise ArtifactLoadingError("UNSUPPORTED_CONTRACT_ARTIFACT")
        schema = _load_json_object(
            schema_directory / filename,
            maximum_bytes=maximum_schema_bytes,
        )
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise ArtifactLoadingError("SCHEMA_DIALECT_MISMATCH")
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            raise ArtifactLoadingError("SCHEMA_IDENTITY_MISSING")
        typed_properties = cast(dict[str, object], properties)
        if not _property_has_const(typed_properties, "contract_name", contract_name):
            raise ArtifactLoadingError("SCHEMA_IDENTITY_MISMATCH")
        if not _property_has_const(typed_properties, "contract_version", _CONTRACT_VERSION):
            raise ArtifactLoadingError("SCHEMA_IDENTITY_MISMATCH")
        loaded[(contract_name, _CONTRACT_VERSION)] = MappingProxyType(schema)
    return MappingProxyType(loaded)


def _property_has_const(
    properties: Mapping[str, object], property_name: str, expected: str
) -> bool:
    value = properties.get(property_name)
    if not isinstance(value, dict):
        return False
    return cast(dict[str, object], value).get("const") == expected
