#!/usr/bin/env bash
# One-shot topic and least-privilege ACL bootstrap for the local Kafka broker.
#
# Runs as the "admin" SCRAM principal, which is listed in super.users and so
# bypasses ACL checks for this administrative work. Every other principal
# created by kafka/entrypoint.sh (orchestrator-producer, orchestrator-consumer,
# agent-producer, agent-consumer, summarize-agent-producer,
# summarize-agent-consumer, review-agent-producer, review-agent-consumer,
# ui-review-agent-producer, ui-review-agent-consumer,
# architecture-review-agent-producer, architecture-review-agent-consumer,
# data-analysis-agent-producer, data-analysis-agent-consumer,
# technical-review-agent-producer, technical-review-agent-consumer,
# security-review-agent-producer, security-review-agent-consumer,
# scrum-status-agent-producer, scrum-status-agent-consumer,
# assignment-route-agent-producer, assignment-route-agent-consumer)
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
TASK_COMMANDS_UI_REVIEW="${PREFIX}.task-commands.ui-review.v1"
TASK_COMMANDS_UI_REVIEW_DLQ="${TASK_COMMANDS_UI_REVIEW}.quarantine"
TASK_COMMANDS_ARCHITECTURE_REVIEW="${PREFIX}.task-commands.architecture-review.v1"
TASK_COMMANDS_ARCHITECTURE_REVIEW_DLQ="${TASK_COMMANDS_ARCHITECTURE_REVIEW}.quarantine"
TASK_COMMANDS_DATA_ANALYSIS="${PREFIX}.task-commands.data-analysis.v1"
TASK_COMMANDS_DATA_ANALYSIS_DLQ="${TASK_COMMANDS_DATA_ANALYSIS}.quarantine"
TASK_COMMANDS_TECHNICAL_REVIEW="${PREFIX}.task-commands.technical-review.v1"
TASK_COMMANDS_TECHNICAL_REVIEW_DLQ="${TASK_COMMANDS_TECHNICAL_REVIEW}.quarantine"
TASK_COMMANDS_SECURITY_REVIEW="${PREFIX}.task-commands.security-review.v1"
TASK_COMMANDS_SECURITY_REVIEW_DLQ="${TASK_COMMANDS_SECURITY_REVIEW}.quarantine"
TASK_COMMANDS_SCRUM_STATUS="${PREFIX}.task-commands.scrum-status.v1"
TASK_COMMANDS_SCRUM_STATUS_DLQ="${TASK_COMMANDS_SCRUM_STATUS}.quarantine"
TASK_COMMANDS_ASSIGNMENT_ROUTE="${PREFIX}.task-commands.assignment-route.v1"
TASK_COMMANDS_ASSIGNMENT_ROUTE_DLQ="${TASK_COMMANDS_ASSIGNMENT_ROUTE}.quarantine"
TASK_OUTCOMES="${PREFIX}.task-outcomes.v1"
TASK_OUTCOMES_DLQ="${TASK_OUTCOMES}.quarantine"

ORCHESTRATOR_OUTCOME_GROUP="ai-platform-orchestrator-outcomes"
AGENT_COMMAND_GROUP="ai-platform-agent-commands"
SUMMARIZE_AGENT_COMMAND_GROUP="ai-platform-summarize-agent-commands"
REVIEW_AGENT_COMMAND_GROUP="ai-platform-review-agent-commands"
UI_REVIEW_AGENT_COMMAND_GROUP="ai-platform-ui-review-agent-commands"
ARCHITECTURE_REVIEW_AGENT_COMMAND_GROUP="ai-platform-architecture-review-agent-commands"
DATA_ANALYSIS_AGENT_COMMAND_GROUP="ai-platform-data-analysis-agent-commands"
TECHNICAL_REVIEW_AGENT_COMMAND_GROUP="ai-platform-technical-review-agent-commands"
SECURITY_REVIEW_AGENT_COMMAND_GROUP="ai-platform-security-review-agent-commands"
SCRUM_STATUS_AGENT_COMMAND_GROUP="ai-platform-scrum-status-agent-commands"
ASSIGNMENT_ROUTE_AGENT_COMMAND_GROUP="ai-platform-assignment-route-agent-commands"

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
    "${TASK_COMMANDS_UI_REVIEW}" "${TASK_COMMANDS_UI_REVIEW_DLQ}" \
    "${TASK_COMMANDS_ARCHITECTURE_REVIEW}" "${TASK_COMMANDS_ARCHITECTURE_REVIEW_DLQ}" \
    "${TASK_COMMANDS_DATA_ANALYSIS}" "${TASK_COMMANDS_DATA_ANALYSIS_DLQ}" \
    "${TASK_COMMANDS_TECHNICAL_REVIEW}" "${TASK_COMMANDS_TECHNICAL_REVIEW_DLQ}" \
    "${TASK_COMMANDS_SECURITY_REVIEW}" "${TASK_COMMANDS_SECURITY_REVIEW_DLQ}" \
    "${TASK_COMMANDS_SCRUM_STATUS}" "${TASK_COMMANDS_SCRUM_STATUS_DLQ}" \
    "${TASK_COMMANDS_ASSIGNMENT_ROUTE}" "${TASK_COMMANDS_ASSIGNMENT_ROUTE_DLQ}" \
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
acls --add --allow-principal "User:orchestrator-producer" \
    --operation Write --operation Describe --topic "${TASK_COMMANDS_UI_REVIEW}"
acls --add --allow-principal "User:orchestrator-producer" \
    --operation Write --operation Describe --topic "${TASK_COMMANDS_ARCHITECTURE_REVIEW}"
acls --add --allow-principal "User:orchestrator-producer" \
    --operation Write --operation Describe --topic "${TASK_COMMANDS_DATA_ANALYSIS}"
acls --add --allow-principal "User:orchestrator-producer" \
    --operation Write --operation Describe --topic "${TASK_COMMANDS_TECHNICAL_REVIEW}"
acls --add --allow-principal "User:orchestrator-producer" \
    --operation Write --operation Describe --topic "${TASK_COMMANDS_SECURITY_REVIEW}"
acls --add --allow-principal "User:orchestrator-producer" \
    --operation Write --operation Describe --topic "${TASK_COMMANDS_SCRUM_STATUS}"
acls --add --allow-principal "User:orchestrator-producer" \
    --operation Write --operation Describe --topic "${TASK_COMMANDS_ASSIGNMENT_ROUTE}"

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

acls --add --allow-principal "User:ui-review-agent-producer" \
    --operation Write --operation Describe --topic "${TASK_OUTCOMES}"

acls --add --allow-principal "User:ui-review-agent-consumer" \
    --operation Read --operation Describe --topic "${TASK_COMMANDS_UI_REVIEW}"
acls --add --allow-principal "User:ui-review-agent-consumer" \
    --operation Write --operation Describe --topic "${TASK_COMMANDS_UI_REVIEW_DLQ}"
acls --add --allow-principal "User:ui-review-agent-consumer" \
    --operation Read --group "${UI_REVIEW_AGENT_COMMAND_GROUP}"

acls --add --allow-principal "User:architecture-review-agent-producer" \
    --operation Write --operation Describe --topic "${TASK_OUTCOMES}"

acls --add --allow-principal "User:architecture-review-agent-consumer" \
    --operation Read --operation Describe --topic "${TASK_COMMANDS_ARCHITECTURE_REVIEW}"
acls --add --allow-principal "User:architecture-review-agent-consumer" \
    --operation Write --operation Describe --topic "${TASK_COMMANDS_ARCHITECTURE_REVIEW_DLQ}"
acls --add --allow-principal "User:architecture-review-agent-consumer" \
    --operation Read --group "${ARCHITECTURE_REVIEW_AGENT_COMMAND_GROUP}"

acls --add --allow-principal "User:data-analysis-agent-producer" \
    --operation Write --operation Describe --topic "${TASK_OUTCOMES}"

acls --add --allow-principal "User:data-analysis-agent-consumer" \
    --operation Read --operation Describe --topic "${TASK_COMMANDS_DATA_ANALYSIS}"
acls --add --allow-principal "User:data-analysis-agent-consumer" \
    --operation Write --operation Describe --topic "${TASK_COMMANDS_DATA_ANALYSIS_DLQ}"
acls --add --allow-principal "User:data-analysis-agent-consumer" \
    --operation Read --group "${DATA_ANALYSIS_AGENT_COMMAND_GROUP}"

acls --add --allow-principal "User:technical-review-agent-producer" \
    --operation Write --operation Describe --topic "${TASK_OUTCOMES}"

acls --add --allow-principal "User:technical-review-agent-consumer" \
    --operation Read --operation Describe --topic "${TASK_COMMANDS_TECHNICAL_REVIEW}"
acls --add --allow-principal "User:technical-review-agent-consumer" \
    --operation Write --operation Describe --topic "${TASK_COMMANDS_TECHNICAL_REVIEW_DLQ}"
acls --add --allow-principal "User:technical-review-agent-consumer" \
    --operation Read --group "${TECHNICAL_REVIEW_AGENT_COMMAND_GROUP}"

acls --add --allow-principal "User:security-review-agent-producer" \
    --operation Write --operation Describe --topic "${TASK_OUTCOMES}"

acls --add --allow-principal "User:security-review-agent-consumer" \
    --operation Read --operation Describe --topic "${TASK_COMMANDS_SECURITY_REVIEW}"
acls --add --allow-principal "User:security-review-agent-consumer" \
    --operation Write --operation Describe --topic "${TASK_COMMANDS_SECURITY_REVIEW_DLQ}"
acls --add --allow-principal "User:security-review-agent-consumer" \
    --operation Read --group "${SECURITY_REVIEW_AGENT_COMMAND_GROUP}"

acls --add --allow-principal "User:scrum-status-agent-producer" \
    --operation Write --operation Describe --topic "${TASK_OUTCOMES}"

acls --add --allow-principal "User:scrum-status-agent-consumer" \
    --operation Read --operation Describe --topic "${TASK_COMMANDS_SCRUM_STATUS}"
acls --add --allow-principal "User:scrum-status-agent-consumer" \
    --operation Write --operation Describe --topic "${TASK_COMMANDS_SCRUM_STATUS_DLQ}"
acls --add --allow-principal "User:scrum-status-agent-consumer" \
    --operation Read --group "${SCRUM_STATUS_AGENT_COMMAND_GROUP}"

acls --add --allow-principal "User:assignment-route-agent-producer" \
    --operation Write --operation Describe --topic "${TASK_OUTCOMES}"

acls --add --allow-principal "User:assignment-route-agent-consumer" \
    --operation Read --operation Describe --topic "${TASK_COMMANDS_ASSIGNMENT_ROUTE}"
acls --add --allow-principal "User:assignment-route-agent-consumer" \
    --operation Write --operation Describe --topic "${TASK_COMMANDS_ASSIGNMENT_ROUTE_DLQ}"
acls --add --allow-principal "User:assignment-route-agent-consumer" \
    --operation Read --group "${ASSIGNMENT_ROUTE_AGENT_COMMAND_GROUP}"

echo "Kafka topic and ACL bootstrap complete."
