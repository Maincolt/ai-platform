import uuid

from ai_platform.runtime.ids import Uuid7IdentifierFactory


def test_new_id_is_a_valid_uuid_string() -> None:
    factory = Uuid7IdentifierFactory()

    value = factory.new_id()

    assert uuid.UUID(value) is not None


def test_new_id_is_genuinely_version_7() -> None:
    factory = Uuid7IdentifierFactory()

    value = factory.new_id()

    parsed = uuid.UUID(value)
    assert parsed.version == 7
    assert parsed.variant == uuid.RFC_4122


def test_successive_ids_are_distinct() -> None:
    factory = Uuid7IdentifierFactory()

    generated = [factory.new_id() for _ in range(1000)]

    assert len(set(generated)) == len(generated)


def test_successive_ids_sort_in_generation_order() -> None:
    """UUIDv7's defining property: lexicographic order matches generation order."""
    factory = Uuid7IdentifierFactory()

    generated = [factory.new_id() for _ in range(1000)]

    assert generated == sorted(generated)
