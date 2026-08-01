"""Verify every canonical JSON Schema document is a valid Draft 2020-12 schema."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

JSON_SCHEMA_DIR = Path(__file__).resolve().parents[2] / "contracts" / "json-schema" / "v1"
SCHEMA_FILES = sorted(JSON_SCHEMA_DIR.glob("*.schema.json"))


def test_at_least_one_schema_exists() -> None:
    assert SCHEMA_FILES, f"No schema files found under {JSON_SCHEMA_DIR}"


def _load_schema(schema_path: Path) -> dict[str, object]:
    return json.loads(schema_path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("schema_path", SCHEMA_FILES, ids=lambda p: p.name)
def test_schema_is_valid_draft_2020_12(schema_path: Path) -> None:
    schema = _load_schema(schema_path)
    Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("schema_path", SCHEMA_FILES, ids=lambda p: p.name)
def test_schema_declares_2020_12_dialect(schema_path: Path) -> None:
    schema = _load_schema(schema_path)
    assert schema.get("$schema") == "https://json-schema.org/draft/2020-12/schema"


@pytest.mark.parametrize("schema_path", SCHEMA_FILES, ids=lambda p: p.name)
def test_schema_has_stable_versioned_id(schema_path: Path) -> None:
    schema = _load_schema(schema_path)
    schema_id = schema.get("$id", "")
    assert isinstance(schema_id, str) and schema_id.startswith("urn:ai-platform:contract:"), (
        f"{schema_path.name} $id must be a stable urn:ai-platform:contract:... URN, "
        f"got {schema_id!r}"
    )
