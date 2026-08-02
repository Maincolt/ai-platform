"""Least-privilege Kafka client security configuration.

Credential values remain adapter-local and are deliberately excluded from
representations and validation errors.
"""

from dataclasses import dataclass, field
from enum import Enum


class KafkaSecurityProtocol(Enum):
    """Approved security modes for the first-slice Kafka adapter."""

    SASL_SSL = "SASL_SSL"
    LOCAL_DEVELOPMENT_SASL_PLAINTEXT = "SASL_PLAINTEXT"


class KafkaSecurityConfigurationError(ValueError):
    """Stable, secret-free security configuration failure."""

    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _is_approved_protocol(value: object) -> bool:
    return isinstance(value, KafkaSecurityProtocol)


def _is_nonempty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


@dataclass(frozen=True, slots=True, repr=False)
class KafkaSecurityConfig:
    """Immutable credentials for one least-privilege Kafka client principal."""

    security_protocol: KafkaSecurityProtocol
    username: str = field(repr=False)
    password: str = field(repr=False)
    ca_file: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not _is_approved_protocol(self.security_protocol):
            raise KafkaSecurityConfigurationError("INVALID_SECURITY_PROTOCOL")
        if not _is_nonempty_text(self.username):
            raise KafkaSecurityConfigurationError("EMPTY_USERNAME")
        if not _is_nonempty_text(self.password):
            raise KafkaSecurityConfigurationError("EMPTY_PASSWORD")
        if self.ca_file is not None:
            if not _is_nonempty_text(self.ca_file):
                raise KafkaSecurityConfigurationError("EMPTY_CA_FILE")
            if self.security_protocol is KafkaSecurityProtocol.LOCAL_DEVELOPMENT_SASL_PLAINTEXT:
                raise KafkaSecurityConfigurationError("CA_FILE_REQUIRES_TLS")

    def __repr__(self) -> str:
        ca_state = "configured" if self.ca_file is not None else "platform-default"
        return (
            "KafkaSecurityConfig("
            f"security_protocol={self.security_protocol.name}, "
            "username=<redacted>, password=<redacted>, "
            f"ca_file=<{ca_state}>)"
        )

    def client_properties(self) -> dict[str, str]:
        """Return the native-client properties at the adapter's final boundary."""
        properties: dict[str, str] = {
            "security.protocol": self.security_protocol.value,
            "sasl.mechanism": "SCRAM-SHA-256",
            "sasl.username": self.username,
            "sasl.password": self.password,
        }
        if self.ca_file is not None:
            properties["ssl.ca.location"] = self.ca_file
        return properties
