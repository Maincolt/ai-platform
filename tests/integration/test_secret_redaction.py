"""External-service secret-redaction guarantee for real Kafka credentials.

Constructs a real `KafkaSecurityConfig` (`src/ai_platform/adapters/event_bus/security.py`)
from the same real SCRAM credential files
`infrastructure/compose/scripts/init-kafka.sh` provisions, and proves the
Section 19 "Security boundary" secret/redaction guarantee against the actual
secret value, not a synthetic placeholder that could pass by accident: the
real password never appears in `repr()`, `str()`, or any exception raised by
constructing the config with an invalid combination of otherwise-real fields.
"""

from __future__ import annotations

import pytest

from ai_platform.adapters.event_bus.security import (
    KafkaSecurityConfig,
    KafkaSecurityConfigurationError,
    KafkaSecurityProtocol,
)

pytestmark = pytest.mark.external_service


@pytest.fixture
def real_orchestrator_producer_security(
    kafka_principal_client_configs: dict[str, dict[str, object]],
) -> KafkaSecurityConfig:
    config = kafka_principal_client_configs["orchestrator-producer"]
    return KafkaSecurityConfig(
        security_protocol=KafkaSecurityProtocol.LOCAL_DEVELOPMENT_SASL_PLAINTEXT,
        username=str(config["sasl.username"]),
        password=str(config["sasl.password"]),
    )


def test_repr_never_contains_the_real_password(
    real_orchestrator_producer_security: KafkaSecurityConfig,
) -> None:
    password = real_orchestrator_producer_security.password
    assert password, "fixture did not resolve a real, nonempty secret"
    assert password not in repr(real_orchestrator_producer_security)


def test_str_never_contains_the_real_password(
    real_orchestrator_producer_security: KafkaSecurityConfig,
) -> None:
    password = real_orchestrator_producer_security.password
    assert password not in str(real_orchestrator_producer_security)


def test_repr_never_contains_the_real_username(
    real_orchestrator_producer_security: KafkaSecurityConfig,
) -> None:
    # username is also adapter-internal identity, not meant for casual display.
    assert real_orchestrator_producer_security.username not in repr(
        real_orchestrator_producer_security
    )


def test_client_properties_carries_the_real_credentials_for_the_broker_boundary(
    real_orchestrator_producer_security: KafkaSecurityConfig,
    kafka_principal_client_configs: dict[str, dict[str, object]],
) -> None:
    """The redaction is a display/log concern only: the adapter's one boundary
    method that hands credentials to the native client must still carry the
    real secret, or authentication against the real broker would silently
    break."""
    expected = kafka_principal_client_configs["orchestrator-producer"]
    properties = real_orchestrator_producer_security.client_properties()
    assert properties["sasl.username"] == expected["sasl.username"]
    assert properties["sasl.password"] == expected["sasl.password"]


def test_invalid_configuration_error_does_not_leak_the_real_password(
    kafka_principal_client_configs: dict[str, dict[str, object]],
) -> None:
    """Force a real validation failure (TLS-only `ca_file` under the local
    plaintext protocol) using an otherwise-real credential pair, and confirm
    the raised error carries only a stable reason code -- never the secret."""
    config = kafka_principal_client_configs["orchestrator-producer"]
    password = str(config["sasl.password"])

    with pytest.raises(KafkaSecurityConfigurationError) as excinfo:
        KafkaSecurityConfig(
            security_protocol=KafkaSecurityProtocol.LOCAL_DEVELOPMENT_SASL_PLAINTEXT,
            username=str(config["sasl.username"]),
            password=password,
            ca_file="/tmp/not-applicable.pem",
        )

    assert excinfo.value.reason_code == "CA_FILE_REQUIRES_TLS"
    assert password not in str(excinfo.value)
    assert password not in repr(excinfo.value)
