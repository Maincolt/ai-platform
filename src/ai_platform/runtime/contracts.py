"""Bounded inbound message parsing and canonical-contract validation."""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from jsonschema import Draft202012Validator, FormatChecker

from ai_platform.shared.identifiers import MessageId

_UUID7_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


class MessageValidationError(Exception):
    """Safe validation failure with optional already-trusted message identity."""

    def __init__(self, reason_code: str, *, validated_message_id: MessageId | None = None) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.validated_message_id = validated_message_id


@dataclass(frozen=True, slots=True)
class ValidatedMessage:
    data: Mapping[str, object]
    message_id: MessageId
    immutable_bytes: bytes
    immutable_sha256: str


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise MessageValidationError("DUPLICATE_JSON_PROPERTY")
        result[key] = value
    return result


class JsonSchemaMessageValidator:
    """Validate UTF-8 JSON messages without trusting partial envelopes."""

    def __init__(
        self,
        schemas: Mapping[tuple[str, str], Mapping[str, object]],
        *,
        maximum_bytes: int = 65_536,
    ) -> None:
        if maximum_bytes < 1:
            raise ValueError("maximum_bytes must be positive")
        if not schemas:
            raise ValueError("at least one message schema is required")
        self._maximum_bytes = maximum_bytes
        self._validators = {
            identity: Draft202012Validator(schema, format_checker=FormatChecker())
            for identity, schema in schemas.items()
        }

    def validate(self, value: bytes | None) -> ValidatedMessage:
        if value is None or not value:
            raise MessageValidationError("EMPTY_MESSAGE")
        if len(value) > self._maximum_bytes:
            raise MessageValidationError("MESSAGE_TOO_LARGE")
        try:
            decoded = value.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise MessageValidationError("INVALID_UTF8") from exc
        try:
            parsed: object = json.loads(decoded, object_pairs_hook=_reject_duplicate_keys)
        except MessageValidationError:
            raise
        except (json.JSONDecodeError, RecursionError) as exc:
            raise MessageValidationError("MALFORMED_JSON") from exc
        if not isinstance(parsed, dict):
            raise MessageValidationError("MESSAGE_NOT_OBJECT")
        message_data = cast(dict[str, object], parsed)

        raw_message_id = message_data.get("message_id")
        if not isinstance(raw_message_id, str) or _UUID7_PATTERN.fullmatch(raw_message_id) is None:
            raise MessageValidationError("INVALID_MESSAGE_ID")
        message_id = MessageId(raw_message_id)

        contract_name = message_data.get("contract_name")
        contract_version = message_data.get("contract_version")
        if not isinstance(contract_name, str) or not isinstance(contract_version, str):
            raise MessageValidationError(
                "MISSING_CONTRACT_IDENTITY", validated_message_id=message_id
            )
        validator = self._validators.get((contract_name, contract_version))
        if validator is None:
            raise MessageValidationError("UNSUPPORTED_CONTRACT", validated_message_id=message_id)
        errors = list(
            validator.iter_errors(message_data)  # pyright: ignore[reportArgumentType, reportUnknownMemberType]
        )
        if errors:
            raise MessageValidationError("SCHEMA_INVALID", validated_message_id=message_id)

        return ValidatedMessage(
            data=message_data,
            message_id=message_id,
            immutable_bytes=value,
            immutable_sha256=hashlib.sha256(value).hexdigest(),
        )
