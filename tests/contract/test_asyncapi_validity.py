"""Structural validation of the canonical AsyncAPI document.

This is intentionally NOT full AsyncAPI 3.0.0 meta-schema conformance
validation. See contracts/README.md, "Known Phase 1 Simplifications", for
why: the official meta-schema is split across many externally hosted files
and vendoring it is deferred. Instead this test checks the specific
structure this platform's tooling relies on: the two channels, the four
operations, and that every declared message payload resolves to one of our
own valid JSON Schema documents.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONTRACTS_ROOT = Path(__file__).resolve().parents[2] / "contracts"
ASYNCAPI_FILE = CONTRACTS_ROOT / "asyncapi" / "v1" / "workflow-events.asyncapi.json"

EXPECTED_CHANNELS = {"task-commands", "task-outcomes"}
EXPECTED_MESSAGES = {"ExecuteTask", "TaskCompleted", "TaskFailed"}
EXPECTED_OPERATIONS = {
    "publishExecuteTask",
    "consumeExecuteTask",
    "publishTaskOutcome",
    "consumeTaskOutcome",
}


def _load() -> dict[str, Any]:
    return json.loads(ASYNCAPI_FILE.read_text(encoding="utf-8"))


def test_asyncapi_document_exists() -> None:
    assert ASYNCAPI_FILE.exists(), f"Missing {ASYNCAPI_FILE}"


def test_asyncapi_declares_3_0_0() -> None:
    document = _load()
    assert document["asyncapi"] == "3.0.0"
    assert "info" in document


def test_asyncapi_declares_expected_channels() -> None:
    document = _load()
    assert set(document["channels"].keys()) == EXPECTED_CHANNELS


def test_asyncapi_declares_expected_operations() -> None:
    document = _load()
    assert set(document["operations"].keys()) == EXPECTED_OPERATIONS


def test_asyncapi_declares_expected_messages() -> None:
    document = _load()
    assert set(document["components"]["messages"].keys()) == EXPECTED_MESSAGES


def test_asyncapi_message_payloads_resolve_to_existing_valid_schema_files() -> None:
    document = _load()
    asyncapi_dir = ASYNCAPI_FILE.parent
    for name, message in document["components"]["messages"].items():
        ref = message["payload"]["$ref"]
        resolved = (asyncapi_dir / ref).resolve()
        assert resolved.is_file(), f"{name} payload $ref does not resolve to a file: {ref}"
        schema = json.loads(resolved.read_text(encoding="utf-8"))
        assert schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema"
