"""Configuration-backed logical-to-physical Kafka topic mapping."""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from ai_platform.ports.event_bus import LogicalChannel

_ENVIRONMENT_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")


class TopicMappingError(ValueError):
    """A topic mapping is incomplete, ambiguous, or unsafe."""


def _validate_physical_name(value: str) -> None:
    if not value or len(value.encode("utf-8")) > 249:
        raise TopicMappingError("INVALID_PHYSICAL_TOPIC")
    if value != value.strip() or any(ord(character) < 0x20 for character in value):
        raise TopicMappingError("INVALID_PHYSICAL_TOPIC")


@dataclass(frozen=True, slots=True)
class TopicBinding:
    """Physical resources for one logical channel."""

    logical_channel: LogicalChannel
    topic: str
    quarantine_topic: str


class KafkaTopicMapping:
    """Validated immutable mapping used only inside the Kafka adapter."""

    def __init__(self, bindings: Iterable[TopicBinding]) -> None:
        by_channel: dict[LogicalChannel, TopicBinding] = {}
        physical_names: set[str] = set()
        for binding in bindings:
            if binding.logical_channel in by_channel:
                raise TopicMappingError("DUPLICATE_LOGICAL_CHANNEL")
            _validate_physical_name(binding.topic)
            _validate_physical_name(binding.quarantine_topic)
            if binding.topic == binding.quarantine_topic:
                raise TopicMappingError("SOURCE_AND_QUARANTINE_TOPIC_MATCH")
            if binding.topic in physical_names or binding.quarantine_topic in physical_names:
                raise TopicMappingError("DUPLICATE_PHYSICAL_TOPIC")
            physical_names.update((binding.topic, binding.quarantine_topic))
            by_channel[binding.logical_channel] = binding

        missing = set(LogicalChannel).difference(by_channel)
        if missing:
            raise TopicMappingError("MISSING_LOGICAL_CHANNEL")
        self._by_channel = by_channel

    def topic_for(self, channel: LogicalChannel) -> str:
        """Return the configured source topic for a logical channel."""
        return self._by_channel[channel].topic

    def quarantine_topic_for(self, channel: LogicalChannel) -> str:
        """Return the configured quarantine topic for a logical channel."""
        return self._by_channel[channel].quarantine_topic


def default_topic_mapping(*, environment: str) -> KafkaTopicMapping:
    """Build the documented local naming convention as explicit configuration."""
    if _ENVIRONMENT_PATTERN.fullmatch(environment) is None:
        raise TopicMappingError("INVALID_ENVIRONMENT")

    bindings: list[TopicBinding] = []
    for channel in LogicalChannel:
        topic = f"ai-platform.{environment}.{channel.value}.v1"
        bindings.append(
            TopicBinding(
                logical_channel=channel,
                topic=topic,
                quarantine_topic=f"{topic}.quarantine",
            )
        )
    return KafkaTopicMapping(bindings)


_CAPABILITY_SLUG_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9.-]{0,61}[a-z0-9])?")


def command_topic_binding_for_capability(*, environment: str, capability_name: str) -> TopicBinding:
    """Compute the capability-scoped physical task-commands topic (ADR-0014 Section 6).

    `task-commands` remains one logical channel; only its physical mapping
    is capability-scoped, so a second Agent class does not receive the
    first Agent class's commands. `task-outcomes` is never capability-scoped
    and continues to use `KafkaTopicMapping.topic_for` unchanged.
    """
    if _ENVIRONMENT_PATTERN.fullmatch(environment) is None:
        raise TopicMappingError("INVALID_ENVIRONMENT")
    if _CAPABILITY_SLUG_PATTERN.fullmatch(capability_name) is None:
        raise TopicMappingError("INVALID_CAPABILITY_NAME")
    slug = capability_name.replace(".", "-")
    topic = f"ai-platform.{environment}.{LogicalChannel.TASK_COMMANDS.value}.{slug}.v1"
    binding = TopicBinding(
        logical_channel=LogicalChannel.TASK_COMMANDS,
        topic=topic,
        quarantine_topic=f"{topic}.quarantine",
    )
    _validate_physical_name(binding.topic)
    _validate_physical_name(binding.quarantine_topic)
    return binding
