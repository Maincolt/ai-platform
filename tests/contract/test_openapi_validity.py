"""Verify the canonical OpenAPI document is valid OpenAPI 3.1.1 and covers
the operations defined in vertical-slice-01.md Section 5.
"""

from __future__ import annotations

from pathlib import Path

from openapi_spec_validator import validate
from openapi_spec_validator.readers import read_from_filename

OPENAPI_DIR = Path(__file__).resolve().parents[2] / "contracts" / "openapi" / "v1"
OPENAPI_FILE = OPENAPI_DIR / "workflow-api.openapi.json"

EXPECTED_OPERATION_IDS = {
    "workflow.submit",
    "workflow.read",
    "health.live",
    "health.ready",
}


def test_openapi_document_exists() -> None:
    assert OPENAPI_FILE.exists(), f"Missing {OPENAPI_FILE}"


def test_openapi_document_is_valid() -> None:
    spec_dict, base_uri = read_from_filename(str(OPENAPI_FILE))
    # No exception raised means the document is a valid OpenAPI 3.1 spec,
    # including resolution of local $ref links to contracts/json-schema/v1/.
    validate(spec_dict, base_uri=base_uri)


def test_openapi_declares_3_1_1() -> None:
    spec_dict, _ = read_from_filename(str(OPENAPI_FILE))
    assert spec_dict["openapi"] == "3.1.1"


def test_openapi_covers_expected_operations() -> None:
    spec_dict, _ = read_from_filename(str(OPENAPI_FILE))
    found_operation_ids = {
        operation["operationId"]
        for path_item in spec_dict["paths"].values()
        for method, operation in path_item.items()
        if method in {"get", "post", "put", "patch", "delete"}
    }
    assert found_operation_ids == EXPECTED_OPERATION_IDS
