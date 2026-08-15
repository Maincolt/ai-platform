#!/usr/bin/env bash
# Custom entrypoint for the single-node local Apache Kafka (KRaft) broker.
#
# The stock apache/kafka image cannot bootstrap SASL/SCRAM credentials by
# itself: the broker enforces SASL_PLAINTEXT on the client listener from the
# first byte, so no admin connection exists yet to create the first SCRAM
# user. `kafka-storage.sh format --add-scram` seeds every required principal
# directly into the KRaft metadata log before the broker ever starts
# listening, which avoids that bootstrap deadlock. `--ignore-formatted` makes
# repeat container starts a no-op against the already-formatted log
# directory, so credentials are seeded exactly once and persist afterward.
set -euo pipefail

KAFKA_HOME="${KAFKA_HOME:-/opt/kafka}"
CONFIG_DIR="/tmp/kafka-config"
mkdir -p "${CONFIG_DIR}"

admin_password="$(cat /run/secrets/kafka_admin_password)"
orchestrator_producer_password="$(cat /run/secrets/kafka_orchestrator_producer_password)"
orchestrator_consumer_password="$(cat /run/secrets/kafka_orchestrator_consumer_password)"
agent_producer_password="$(cat /run/secrets/kafka_agent_producer_password)"
agent_consumer_password="$(cat /run/secrets/kafka_agent_consumer_password)"
summarize_agent_producer_password="$(cat /run/secrets/kafka_summarize_agent_producer_password)"
summarize_agent_consumer_password="$(cat /run/secrets/kafka_summarize_agent_consumer_password)"
review_agent_producer_password="$(cat /run/secrets/kafka_review_agent_producer_password)"
review_agent_consumer_password="$(cat /run/secrets/kafka_review_agent_consumer_password)"
ui_review_agent_producer_password="$(cat /run/secrets/kafka_ui_review_agent_producer_password)"
ui_review_agent_consumer_password="$(cat /run/secrets/kafka_ui_review_agent_consumer_password)"
architecture_review_agent_producer_password="$(cat /run/secrets/kafka_architecture_review_agent_producer_password)"
architecture_review_agent_consumer_password="$(cat /run/secrets/kafka_architecture_review_agent_consumer_password)"
data_analysis_agent_producer_password="$(cat /run/secrets/kafka_data_analysis_agent_producer_password)"
data_analysis_agent_consumer_password="$(cat /run/secrets/kafka_data_analysis_agent_consumer_password)"
technical_review_agent_producer_password="$(cat /run/secrets/kafka_technical_review_agent_producer_password)"
technical_review_agent_consumer_password="$(cat /run/secrets/kafka_technical_review_agent_consumer_password)"

cat > "${CONFIG_DIR}/server.properties" <<PROPERTIES
process.roles=broker,controller
node.id=1
controller.quorum.voters=1@kafka:9093
listeners=PLAINTEXT_CONTROLLER://0.0.0.0:9093,BROKER://0.0.0.0:9092,EXTERNAL://0.0.0.0:19093
advertised.listeners=PLAINTEXT_CONTROLLER://kafka:9093,BROKER://kafka:9092,EXTERNAL://${KAFKA_EXTERNAL_ADVERTISED_HOST:-localhost}:19093
listener.security.protocol.map=PLAINTEXT_CONTROLLER:PLAINTEXT,BROKER:SASL_PLAINTEXT,EXTERNAL:SASL_PLAINTEXT
controller.listener.names=PLAINTEXT_CONTROLLER
inter.broker.listener.name=BROKER

sasl.enabled.mechanisms=SCRAM-SHA-256
sasl.mechanism.inter.broker.protocol=SCRAM-SHA-256
listener.name.broker.sasl.enabled.mechanisms=SCRAM-SHA-256
listener.name.broker.scram-sha-256.sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="admin" password="${admin_password}";
listener.name.external.sasl.enabled.mechanisms=SCRAM-SHA-256
listener.name.external.scram-sha-256.sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="admin" password="${admin_password}";

authorizer.class.name=org.apache.kafka.metadata.authorizer.StandardAuthorizer
# ANONYMOUS is the unavoidable principal on the unauthenticated, container-
# network-only controller listener; it is not published to the host and
# carries no client traffic. admin is the operational bootstrap principal
# used only by infrastructure/compose/scripts/init-kafka.sh.
super.users=User:admin;User:ANONYMOUS
allow.everyone.if.no.acl.found=false

log.dirs=/var/lib/kafka/data
num.partitions=1
auto.create.topics.enable=false
offsets.topic.replication.factor=1
transaction.state.log.replication.factor=1
transaction.state.log.min.isr=1
default.replication.factor=1
min.insync.replicas=1
PROPERTIES

cat > /tmp/admin-client.properties <<ADMIN
security.protocol=SASL_PLAINTEXT
sasl.mechanism=SCRAM-SHA-256
sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="admin" password="${admin_password}";
ADMIN

echo "Formatting KRaft storage (no-op if already formatted)..."
"${KAFKA_HOME}/bin/kafka-storage.sh" format \
    --cluster-id "${KAFKA_CLUSTER_ID}" \
    --config "${CONFIG_DIR}/server.properties" \
    --ignore-formatted \
    --add-scram "SCRAM-SHA-256=[name=admin,password=${admin_password}]" \
    --add-scram "SCRAM-SHA-256=[name=orchestrator-producer,password=${orchestrator_producer_password}]" \
    --add-scram "SCRAM-SHA-256=[name=orchestrator-consumer,password=${orchestrator_consumer_password}]" \
    --add-scram "SCRAM-SHA-256=[name=agent-producer,password=${agent_producer_password}]" \
    --add-scram "SCRAM-SHA-256=[name=agent-consumer,password=${agent_consumer_password}]" \
    --add-scram "SCRAM-SHA-256=[name=summarize-agent-producer,password=${summarize_agent_producer_password}]" \
    --add-scram "SCRAM-SHA-256=[name=summarize-agent-consumer,password=${summarize_agent_consumer_password}]" \
    --add-scram "SCRAM-SHA-256=[name=review-agent-producer,password=${review_agent_producer_password}]" \
    --add-scram "SCRAM-SHA-256=[name=review-agent-consumer,password=${review_agent_consumer_password}]" \
    --add-scram "SCRAM-SHA-256=[name=ui-review-agent-producer,password=${ui_review_agent_producer_password}]" \
    --add-scram "SCRAM-SHA-256=[name=ui-review-agent-consumer,password=${ui_review_agent_consumer_password}]" \
    --add-scram "SCRAM-SHA-256=[name=architecture-review-agent-producer,password=${architecture_review_agent_producer_password}]" \
    --add-scram "SCRAM-SHA-256=[name=architecture-review-agent-consumer,password=${architecture_review_agent_consumer_password}]" \
    --add-scram "SCRAM-SHA-256=[name=data-analysis-agent-producer,password=${data_analysis_agent_producer_password}]" \
    --add-scram "SCRAM-SHA-256=[name=data-analysis-agent-consumer,password=${data_analysis_agent_consumer_password}]" \
    --add-scram "SCRAM-SHA-256=[name=technical-review-agent-producer,password=${technical_review_agent_producer_password}]" \
    --add-scram "SCRAM-SHA-256=[name=technical-review-agent-consumer,password=${technical_review_agent_consumer_password}]"

echo "Starting Kafka broker..."
exec "${KAFKA_HOME}/bin/kafka-server-start.sh" "${CONFIG_DIR}/server.properties"
