"""Canonical immutable message encoding shared by platform components."""

from collections.abc import Mapping, Sequence
from typing import cast

import rfc8785

type JsonValue = None | bool | int | float | str | Sequence[JsonValue] | Mapping[str, JsonValue]


def canonical_message_bytes(message: Mapping[str, object]) -> bytes:
    """Encode one validated message once for durable outbox storage.

    Publishers must send the returned bytes verbatim on every attempt. They
    never reconstruct or reserialize a message from database fields.
    """

    encoded = rfc8785.dumps(cast(JsonValue, message))
    if not encoded:
        raise ValueError("A canonical message must not be empty")
    return encoded
