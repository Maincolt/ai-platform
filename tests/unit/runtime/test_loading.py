"""Tests for bounded Registry and canonical schema artifact loading."""

import json
from pathlib import Path
from typing import cast

import pytest

from ai_platform.runtime.loading import (
    ArtifactLoadingError,
    load_agent_deployment_declaration,
    load_canonical_message_schemas,
    load_registry_artifact,
)
from ai_platform.shared.identifiers import AgentId


def _registry_document() -> dict[str, object]:
    return {
        "revision": "sprint-6",
        "bindings": [
            {
                "capability_name": "test.echo",
                "capability_version": "1.0",
                "command_contract_name": "ExecuteTask",
                "command_contract_versions": ["1.0"],
                "event_contract_names": ["TaskCompleted", "TaskFailed"],
                "event_contract_versions": ["1.0", "1.0"],
                "agent_id": "018f23a7-6b4d-7c91-8a2e-123456789abc",
                "implementation_identity": "test-agent",
                "implementation_version": "1.0",
                "deployment_declaration_digest": "sha256:declaration",
                "environment": "development",
                "enabled": True,
                "readiness_url": "http://127.0.0.1:8100/health/ready",
            }
        ],
    }


def test_load_registry_artifact_returns_complete_validated_snapshot(tmp_path: Path) -> None:
    artifact = tmp_path / "registry.json"
    artifact.write_text(json.dumps(_registry_document()), encoding="utf-8")

    snapshot = load_registry_artifact(artifact)

    assert snapshot.revision == "sprint-6"
    assert len(snapshot.bindings) == 1
    assert snapshot.bindings[0].implementation_identity == "test-agent"


def test_load_registry_artifact_rejects_duplicate_json_properties(tmp_path: Path) -> None:
    artifact = tmp_path / "registry.json"
    artifact.write_text('{"revision":"one","revision":"two","bindings":[]}', encoding="utf-8")

    with pytest.raises(ArtifactLoadingError, match="DUPLICATE_JSON_PROPERTY"):
        load_registry_artifact(artifact)


def test_load_canonical_message_schemas_uses_exact_contract_identity() -> None:
    schemas = load_canonical_message_schemas(
        Path("contracts/json-schema/v1"),
        contract_names=("ExecuteTask", "TaskCompleted", "TaskFailed"),
    )

    assert set(schemas) == {
        ("ExecuteTask", "1.0"),
        ("TaskCompleted", "1.0"),
        ("TaskFailed", "1.0"),
    }


def test_load_canonical_message_schemas_rejects_unknown_contract() -> None:
    with pytest.raises(ArtifactLoadingError, match="UNSUPPORTED_CONTRACT_ARTIFACT"):
        load_canonical_message_schemas(
            Path("contracts/json-schema/v1"),
            contract_names=("Unknown",),
        )


def test_agent_declaration_must_match_builtin_capability_and_runtime_identity(
    tmp_path: Path,
) -> None:
    document = _registry_document()
    binding = cast(list[dict[str, object]], document["bindings"])[0]
    binding["capability_name"] = "text.word-count"
    artifact = tmp_path / "declaration.json"
    artifact.write_text(json.dumps(document), encoding="utf-8")

    revision, loaded = load_agent_deployment_declaration(
        artifact,
        environment="development",
        agent_id=AgentId("018f23a7-6b4d-7c91-8a2e-123456789abc"),
        implementation_identity="test-agent",
        declaration_digest="sha256:declaration",
    )

    assert revision == "sprint-6"
    assert loaded.command_contract_versions == ("1.0",)


def test_agent_declaration_accepts_code_review_capability(tmp_path: Path) -> None:
    """ADR-0018: `code.review` is a supported built-in capability, not just
    `text.word-count`/`text.summarize`."""
    document = _registry_document()
    binding = cast(list[dict[str, object]], document["bindings"])[0]
    binding["capability_name"] = "code.review"
    artifact = tmp_path / "declaration.json"
    artifact.write_text(json.dumps(document), encoding="utf-8")

    revision, loaded = load_agent_deployment_declaration(
        artifact,
        environment="development",
        agent_id=AgentId("018f23a7-6b4d-7c91-8a2e-123456789abc"),
        implementation_identity="test-agent",
        declaration_digest="sha256:declaration",
    )

    assert revision == "sprint-6"
    assert loaded.capability_name == "code.review"


def test_agent_declaration_accepts_ui_review_capability(tmp_path: Path) -> None:
    """ADR-0019: `ui.review` is a supported built-in capability. Regression
    test for the exact gap ADR-0018 already documented once -- a new
    capability must be added to `_SUPPORTED_CAPABILITY_NAMES` or Agent
    startup fails with `AGENT_DECLARATION_MISMATCH`."""
    document = _registry_document()
    binding = cast(list[dict[str, object]], document["bindings"])[0]
    binding["capability_name"] = "ui.review"
    artifact = tmp_path / "declaration.json"
    artifact.write_text(json.dumps(document), encoding="utf-8")

    revision, loaded = load_agent_deployment_declaration(
        artifact,
        environment="development",
        agent_id=AgentId("018f23a7-6b4d-7c91-8a2e-123456789abc"),
        implementation_identity="test-agent",
        declaration_digest="sha256:declaration",
    )

    assert revision == "sprint-6"
    assert loaded.capability_name == "ui.review"


def test_agent_declaration_accepts_architecture_review_capability(tmp_path: Path) -> None:
    """ADR-0020: `architecture.review` is a supported built-in capability.
    Regression test for the exact gap ADR-0018 already documented once --
    a new capability must be added to `_SUPPORTED_CAPABILITY_NAMES` or
    Agent startup fails with `AGENT_DECLARATION_MISMATCH`."""
    document = _registry_document()
    binding = cast(list[dict[str, object]], document["bindings"])[0]
    binding["capability_name"] = "architecture.review"
    artifact = tmp_path / "declaration.json"
    artifact.write_text(json.dumps(document), encoding="utf-8")

    revision, loaded = load_agent_deployment_declaration(
        artifact,
        environment="development",
        agent_id=AgentId("018f23a7-6b4d-7c91-8a2e-123456789abc"),
        implementation_identity="test-agent",
        declaration_digest="sha256:declaration",
    )

    assert revision == "sprint-6"
    assert loaded.capability_name == "architecture.review"


def test_agent_declaration_accepts_data_analysis_capability(tmp_path: Path) -> None:
    """ADR-0021: `data.analysis` is a supported built-in capability.
    Regression test for the exact gap ADR-0018 already documented once --
    a new capability must be added to `_SUPPORTED_CAPABILITY_NAMES` or
    Agent startup fails with `AGENT_DECLARATION_MISMATCH`."""
    document = _registry_document()
    binding = cast(list[dict[str, object]], document["bindings"])[0]
    binding["capability_name"] = "data.analysis"
    artifact = tmp_path / "declaration.json"
    artifact.write_text(json.dumps(document), encoding="utf-8")

    revision, loaded = load_agent_deployment_declaration(
        artifact,
        environment="development",
        agent_id=AgentId("018f23a7-6b4d-7c91-8a2e-123456789abc"),
        implementation_identity="test-agent",
        declaration_digest="sha256:declaration",
    )

    assert revision == "sprint-6"
    assert loaded.capability_name == "data.analysis"


def test_agent_declaration_accepts_technical_review_capability(tmp_path: Path) -> None:
    """ADR-0022: `technical.review` is a supported built-in capability.
    Regression test for the exact gap ADR-0018 already documented once --
    a new capability must be added to `_SUPPORTED_CAPABILITY_NAMES` or
    Agent startup fails with `AGENT_DECLARATION_MISMATCH`."""
    document = _registry_document()
    binding = cast(list[dict[str, object]], document["bindings"])[0]
    binding["capability_name"] = "technical.review"
    artifact = tmp_path / "declaration.json"
    artifact.write_text(json.dumps(document), encoding="utf-8")

    revision, loaded = load_agent_deployment_declaration(
        artifact,
        environment="development",
        agent_id=AgentId("018f23a7-6b4d-7c91-8a2e-123456789abc"),
        implementation_identity="test-agent",
        declaration_digest="sha256:declaration",
    )

    assert revision == "sprint-6"
    assert loaded.capability_name == "technical.review"


def test_agent_declaration_accepts_security_review_capability(tmp_path: Path) -> None:
    """ADR-0025: `security.review` is a supported built-in capability.
    Regression test for the exact gap ADR-0018 already documented once --
    a new capability must be added to `_SUPPORTED_CAPABILITY_NAMES` or
    Agent startup fails with `AGENT_DECLARATION_MISMATCH`."""
    document = _registry_document()
    binding = cast(list[dict[str, object]], document["bindings"])[0]
    binding["capability_name"] = "security.review"
    artifact = tmp_path / "declaration.json"
    artifact.write_text(json.dumps(document), encoding="utf-8")

    revision, loaded = load_agent_deployment_declaration(
        artifact,
        environment="development",
        agent_id=AgentId("018f23a7-6b4d-7c91-8a2e-123456789abc"),
        implementation_identity="test-agent",
        declaration_digest="sha256:declaration",
    )

    assert revision == "sprint-6"
    assert loaded.capability_name == "security.review"


def test_agent_declaration_accepts_assignment_route_capability(tmp_path: Path) -> None:
    """ADR-0023: `assignment.route` is a supported built-in capability.
    Regression test for the exact gap ADR-0018 already documented once --
    a new capability must be added to `_SUPPORTED_CAPABILITY_NAMES` or
    Agent startup fails with `AGENT_DECLARATION_MISMATCH`."""
    document = _registry_document()
    binding = cast(list[dict[str, object]], document["bindings"])[0]
    binding["capability_name"] = "assignment.route"
    artifact = tmp_path / "declaration.json"
    artifact.write_text(json.dumps(document), encoding="utf-8")

    revision, loaded = load_agent_deployment_declaration(
        artifact,
        environment="development",
        agent_id=AgentId("018f23a7-6b4d-7c91-8a2e-123456789abc"),
        implementation_identity="test-agent",
        declaration_digest="sha256:declaration",
    )

    assert revision == "sprint-6"
    assert loaded.capability_name == "assignment.route"


def test_agent_declaration_mismatch_refuses_loading(tmp_path: Path) -> None:
    document = _registry_document()
    binding = cast(list[dict[str, object]], document["bindings"])[0]
    binding["capability_name"] = "text.word-count"
    artifact = tmp_path / "declaration.json"
    artifact.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ArtifactLoadingError, match="AGENT_DECLARATION_MISMATCH"):
        load_agent_deployment_declaration(
            artifact,
            environment="development",
            agent_id=AgentId("018f23a7-6b4d-7c91-8a2e-123456789abc"),
            implementation_identity="wrong-agent",
            declaration_digest="sha256:declaration",
        )
