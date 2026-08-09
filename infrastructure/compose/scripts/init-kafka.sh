#!/usr/bin/env bash
# One-shot topic and least-privilege ACL bootstrap for the local Kafka broker.
#
# Runs as the "admin" SCRAM principal, which is listed in super.users and so
# bypasses ACL checks for this administrative work. Every other principal
# created by kafka/entrypoint.sh (orchestrator-producer, orchestrator-consumer,
# agent-producer, agent-consumer, summarize-agent-producer,
# summarize-agent-consumer, review-agent-producer, review-agent-consumer)
# receives only the topic and consumer-group access its role requires,
# matching ADR-0005 Section 17 (Orchestrator writes commands and reads
# outcomes; each Agent class reads only its own capability-scoped commands
# and writes outcomes; quarantine access stays with the consumer that
# detects the rejection).
#
# Sprint 9 / ADR-0014 Section 6: task-commands is now capability-scoped at
# the physical-topic level -- one topic (+ quarantine companion) per Agent
# class -- so a second Agent class's consumer group never receives the
# first Agent class's commands. task-outcomes remains a single shared
# topic/consumer group per capability-agnostic outcome correlation.
set -euo pipefail

KAFKA_HOME="${KAFKA_HOME:-/opt/kafka}"
BOOTSTRAP="kafka:9092"
ENVIRONMENT="development"
PREFIX="ai-platform.${ENVIRONMENT}"

TASK_COMMANDS_WORD_COUNT="${PREFIX}.task-commands.text-word-count.v1"
TASK_COMMANDS_WORD_COUNT_DLQ="${TASK_COMMANDS_WORD_COUNT}.quarantine"
TASK_COMMANDS_SUMMARIZE="${PREFIX}.task-commands.text-summarize.v1"
TASK_COMMANDS_SUMMARIZE_DLQ="${TASK_COMMANDS_SUMMARIZE}.quarantine"
TASK_COMMANDS_REVIEW="${PREFIX}.task-commands.code-review.v1"
TASK_COMMANDS_REVIEW_DLQ="${TASK_COMMANDS_REVIEW}.quarantine"
TASK_OUTCOMES="${PREFIX}.task-outcomes.v1"
TASK_OUTCOMES_DLQ="${TASK_OUTCOMES}.quarantine"

ORCHESTRATOR_OUTCOME_GROUP="ai-platform-orchestrator-outcomes"
AGENT_COMMAND_GROUP="ai-platform-agent-commands"
SUMMARIZE_AGENT_COMMAND_GROUP="ai-platform-summarize-agent-commands"
REVIEW_AGENT_COMMAND_GROUP="ai-platform-review-agent-commands"

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
for topic in "${TASK_COMMANDS_WORD_COUNT}" "${TASK_COMMANDS_WORD_COUNT_DLQ}" \
    "${TASK_COMMANDS_SUMMARIZE}" "${TASK_COMMANDS_SUMMARIZE_DLQ}" \
    "${TASK_COMMANDS_REVIEW}" "${TASK_COMMANDS_REVIEW_DLQ}" \
    "${TASK_OUTCOMES}" "${TASK_OUTCOMES_DLQ}"; do
    topics --create --if-not-exists --topic "${topic}" --partitions 3 --replication-factor 1
done

echo "Granting least-privilege ACLs..."

acls --add --allow-principal "User:orchestrator-producer" \
    --operation Write --operation Describe --topic "${TASK_COMMANDS_WORD_COUNT}"
acls --add --allow-principal "User:orchestrator-producer" \
    --operation Write --operation Describe --topic "${TASK_COMMANDS_SUMMARIZE}"
acls --add --allow-principal "User:orchestrator-producer" \
    --operation Write --operation Describe --topic "${TASK_COMMANDS_REVIEW}"

acls --add --allow-principal "User:orchestrator-consumer" \
    --operation Read --operation Describe --topic "${TASK_OUTCOMES}"
acls --add --allow-principal "User:orchestrator-consumer" \
    --operation Write --operation Describe --topic "${TASK_OUTCOMES_DLQ}"
acls --add --allow-principal "User:orchestrator-consumer" \
    --operation Read --group "${ORCHESTRATOR_OUTCOME_GROUP}"

acls --add --allow-principal "User:agent-producer" \
    --operation Write --operation Describe --topic "${TASK_OUTCOMES}"

acls --add --allow-principal "User:agent-consumer" \
    --operation Read --operation Describe --topic "${TASK_COMMANDS_WORD_COUNT}"
acls --add --allow-principal "User:agent-consumer" \
    --operation Write --operation Describe --topic "${TASK_COMMANDS_WORD_COUNT_DLQ}"
acls --add --allow-principal "User:agent-consumer" \
    --operation Read --group "${AGENT_COMMAND_GROUP}"

acls --add --allow-principal "User:summarize-agent-producer" \
    --operation Write --operation Describe --topic "${TASK_OUTCOMES}"

acls --add --allow-principal "User:summarize-agent-consumer" \
    --operation Read --operation Describe --topic "${TASK_COMMANDS_SUMMARIZE}"
acls --add --allow-principal "User:summarize-agent-consumer" \
    --operation Write --operation Describe --topic "${TASK_COMMANDS_SUMMARIZE_DLQ}"
acls --add --allow-principal "User:summarize-agent-consumer" \
    --operation Read --group "${SUMMARIZE_AGENT_COMMAND_GROUP}"

acls --add --allow-principal "User:review-agent-producer" \
    --operation Write --operation Describe --topic "${TASK_OUTCOMES}"

acls --add --allow-principal "User:review-agent-consumer" \
    --operation Read --operation Describe --topic "${TASK_COMMANDS_REVIEW}"
acls --add --allow-principal "User:review-agent-consumer" \
    --operation Write --operation Describe --topic "${TASK_COMMANDS_REVIEW_DLQ}"
acls --add --allow-principal "User:review-agent-consumer" \
    --operation Read --group "${REVIEW_AGENT_COMMAND_GROUP}"

echo "Kafka topic and ACL bootstrap complete."
