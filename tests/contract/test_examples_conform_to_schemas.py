"""Verify every example validates against its declared canonical schema, and
that every schema has at least one example (Sprint 1 task 9).

Convention: an example file's schema is named
"<first dot-separated segment of the example filename>.schema.json", e.g.
"workflow_submit_request.valid.json" validates against
"workflow_submit_request.schema.json".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

CONTRACTS_ROOT = Path(__file__).resolve().parents[2] / "contracts"
JSON_SCHEMA_DIR = CONTRACTS_ROOT / "json-schema" / "v1"
EXAMPLES_DIR = CONTRACTS_ROOT / "examples" / "v1"

EXAMPLE_FILES = sorted(EXAMPLES_DIR.glob("*.json"))
SCHEMA_FILES = sorted(JSON_SCHEMA_DIR.glob("*.schema.json"))


def _schema_name_for_example(example_path: Path) -> str:
    base = example_path.name.split(".")[0]
    return f"{base}.schema.json"


def test_at_least_one_example_exists() -> None:
    assert EXAMPLE_FILES, f"No example files found under {EXAMPLES_DIR}"


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("example_path", EXAMPLE_FILES, ids=lambda p: p.name)
def test_example_conforms_to_its_declared_schema(example_path: Path) -> None:
    schema_path = JSON_SCHEMA_DIR / _schema_name_for_example(example_path)
    assert schema_path.exists(), (
        f"{example_path.name} has no matching schema file {schema_path.name}"
    )

    schema = _load_json(schema_path)
    instance = _load_json(example_path)

    # jsonschema's third-party type stubs do not fully type `validate`.
    Draft202012Validator(schema).validate(instance)  # pyright: ignore[reportUnknownMemberType]


@pytest.mark.parametrize("schema_path", SCHEMA_FILES, ids=lambda p: p.name)
def test_every_schema_has_at_least_one_example(schema_path: Path) -> None:
    base = schema_path.name.removesuffix(".schema.json")
    matching = [p for p in EXAMPLE_FILES if p.name.split(".")[0] == base]
    assert matching, f"{schema_path.name} has no example under {EXAMPLES_DIR}"
