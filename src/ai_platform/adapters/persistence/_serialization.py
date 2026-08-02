"""Database encodings for immutable transport metadata."""

import base64
from typing import cast

from ai_platform.ports.persistence.errors import PermanentPersistenceError


def encode_headers(headers: tuple[tuple[str, bytes], ...]) -> list[list[str]]:
    return [[name, base64.b64encode(value).decode("ascii")] for name, value in headers]


def decode_headers(value: object) -> tuple[tuple[str, bytes], ...]:
    if not isinstance(value, list):
        raise PermanentPersistenceError("Stored message headers are invalid.")
    decoded: list[tuple[str, bytes]] = []
    raw_pairs = cast(list[object], value)
    for pair_value in raw_pairs:
        pair = cast(list[object], pair_value) if isinstance(pair_value, list) else []
        if len(pair) != 2 or not isinstance(pair[0], str) or not isinstance(pair[1], str):
            raise PermanentPersistenceError("Stored message headers are invalid.")
        try:
            decoded.append((pair[0], base64.b64decode(pair[1], validate=True)))
        except ValueError as exc:
            raise PermanentPersistenceError("Stored message headers are invalid.") from exc
    return tuple(decoded)
