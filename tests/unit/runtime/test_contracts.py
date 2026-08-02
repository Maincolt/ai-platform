"""Broker-free tests for bounded inbound message validation."""

import json

import pytest

from ai_platform.runtime.contracts import JsonSchemaMessageValidator, MessageValidationError

MESSAGE_ID = "018f23a7-6b4d-7c91-8a2e-123456789abc"


def _validator() -> JsonSchemaMessageValidator:
    return JsonSchemaMessageValidator(
        {
            ("Example", "1.0"): {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "additionalProperties": False,
                "required": ["message_id", "contract_name", "contract_version", "value"],
                "properties": {
                    "message_id": {"type": "string"},
                    "contract_name": {"const": "Example"},
                    "contract_version": {"const": "1.0"},
                    "value": {"type": "integer"},
                },
            }
        },
        maximum_bytes=1024,
    )


def _message(**changes: object) -> bytes:
    value: dict[str, object] = {
        "message_id": MESSAGE_ID,
        "contract_name": "Example",
        "contract_version": "1.0",
        "value": 3,
    }
    value.update(changes)
    return json.dumps(value).encode()


def test_valid_message_preserves_exact_bytes_and_digest() -> None:
    raw = _message()
    validated = _validator().validate(raw)
    assert validated.immutable_bytes == raw
    assert len(validated.immutable_sha256) == 64
    assert validated.message_id == MESSAGE_ID


@pytest.mark.parametrize("raw", [None, b"", b"\xff", b"[]", b"not-json"])
def test_pre_identity_damage_has_no_trusted_message_id(raw: bytes | None) -> None:
    with pytest.raises(MessageValidationError) as captured:
        _validator().validate(raw)
    assert captured.value.validated_message_id is None


def test_duplicate_property_is_rejected_before_identity_is_trusted() -> None:
    raw = (
        '{"message_id":"'
        + MESSAGE_ID
        + '","message_id":"'
        + MESSAGE_ID
        + '","contract_name":"Example","contract_version":"1.0","value":3}'
    ).encode()
    with pytest.raises(MessageValidationError, match="DUPLICATE_JSON_PROPERTY") as captured:
        _validator().validate(raw)
    assert captured.value.validated_message_id is None


def test_schema_failure_retains_validated_message_identity_for_domain_rejection() -> None:
    with pytest.raises(MessageValidationError, match="SCHEMA_INVALID") as captured:
        _validator().validate(_message(value="wrong"))
    assert captured.value.validated_message_id == MESSAGE_ID


def test_unsupported_contract_retains_validated_message_identity() -> None:
    with pytest.raises(MessageValidationError, match="UNSUPPORTED_CONTRACT") as captured:
        _validator().validate(_message(contract_name="Unknown"))
    assert captured.value.validated_message_id == MESSAGE_ID


def test_size_is_bounded_before_parsing() -> None:
    validator = JsonSchemaMessageValidator(
        {("Example", "1.0"): {"type": "object"}}, maximum_bytes=4
    )
    with pytest.raises(MessageValidationError, match="MESSAGE_TOO_LARGE"):
        validator.validate(b"12345")
