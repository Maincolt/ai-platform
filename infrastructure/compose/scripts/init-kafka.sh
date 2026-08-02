#!/usr/bin/env bash
# One-shot topic and least-privilege ACL bootstrap for the local Kafka broker.
#
# Runs as the "admin" SCRAM principal, which is listed in super.users and so
# bypasses ACL checks for this administrative work. Every other principal
# created by kafka/entrypoint.sh (orchestrator-producer, orchestrator-consumer,
# agent-producer, agent-consumer) receives only the topic and consumer-group
# access its role requires, matching ADR-0005 Section 17 (Orchestrator writes
# commands and reads outcomes; the Test Agent reads commands and writes
# outcomes; quarantine access stays with the consumer that detects the
# rejection).
set -euo pipefail

KAFKA_HOME="${KAFKA_HOME:-/opt/kafka}"
BOOTSTRAP="kafka:9092"
ENVIRONMENT="development"
PREFIX="ai-platform.${ENVIRONMENT}"

TASK_COMMANDS="${PREFIX}.task-commands.v1"
TASK_COMMANDS_DLQ="${TASK_COMMANDS}.quarantine"
TASK_OUTCOMES="${PREFIX}.task-outcomes.v1"
TASK_OUTCOMES_DLQ="${TASK_OUTCOMES}.quarantine"

ORCHESTRATOR_OUTCOME_GROUP="ai-platform-orchestrator-outcomes"
AGENT_COMMAND_GROUP="ai-platform-agent-commands"

admin_password="$(cat /run/secrets/kafka_admin_password)"
cat > /tmp/admin-client.properties <<ADMIN
security.protocol=SASL_PLAINTEXT
sasl.mechanism=SCRAM-SHA-256
sasl.jaas.config=org.apache.kafka.common.security.scram.ScramLoginModule required username="admin" password="${admin_password}";
ADMIN

topics() { "${KAFKA_HOME}/bin/kafka-topics.sh" --bootstrap-server "${BOOTSTRAP}" --command-config /tmp/admin-client.properties "$@"; }
acls() { "${KAFKA_HOME}/bin/kafka-acls.sh" --bootstrap-server "${BOOTSTRAP}" --command-config /tmp/admin-client.properties "$@"; }

echo "Waiting for Kafka to accept admin connections..."
until topics --list >/dev/null 2>&1; do
    sleep 2
done

echo "Creating platform topics (idempotent)..."
for topic in "${TASK_COMMANDS}" "${TASK_COMMANDS_DLQ}" "${TASK_OUTCOMES}" "${TASK_OUTCOMES_DLQ}"; do
    topics --create --if-not-exists --topic "${topic}" --partitions 3 --replication-factor 1
done

echo "Granting least-privilege ACLs..."

acls --add --allow-principal "User:orchestrator-producer" \
    --operation Write --operation Describe --topic "${TASK_COMMANDS}"

acls --add --allow-principal "User:orchestrator-consumer" \
    --operation Read --operation Describe --topic "${TASK_OUTCOMES}"
acls --add --allow-principal "User:orchestrator-consumer" \
    --operation Write --operation Describe --topic "${TASK_OUTCOMES_DLQ}"
acls --add --allow-principal "User:orchestrator-consumer" \
    --operation Read --group "${ORCHESTRATOR_OUTCOME_GROUP}"

acls --add --allow-principal "User:agent-producer" \
    --operation Write --operation Describe --topic "${TASK_OUTCOMES}"

acls --add --allow-principal "User:agent-consumer" \
    --operation Read --operation Describe --topic "${TASK_COMMANDS}"
acls --add --allow-principal "User:agent-consumer" \
    --operation Write --operation Describe --topic "${TASK_COMMANDS_DLQ}"
acls --add --allow-principal "User:agent-consumer" \
    --operation Read --group "${AGENT_COMMAND_GROUP}"

echo "Kafka topic and ACL bootstrap complete."
