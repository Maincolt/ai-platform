#!/usr/bin/env bash
# Generate local-only credential files for the Sprint 6 Compose topology.
#
# Every file is a random value with no default, so the stack cannot start
# with a guessable or shared credential. Files already present are left
# untouched, so re-running this script does not rotate existing secrets.
# The secrets/ directory is excluded from version control by .gitignore.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)/secrets"
mkdir -p "${SECRETS_DIR}"

random_value() {
    openssl rand -base64 32 | tr -d '\n=+/' | cut -c1-32
}

write_if_absent() {
    local name="$1"
    local path="${SECRETS_DIR}/${name}"
    if [ -f "${path}" ]; then
        echo "exists: ${name}"
        return
    fi
    random_value > "${path}"
    chmod 600 "${path}" 2>/dev/null || true
    echo "generated: ${name}"
}

write_if_absent "postgres_admin_password.txt"
write_if_absent "postgres_orchestrator_migrator_password.txt"
write_if_absent "postgres_orchestrator_app_password.txt"
write_if_absent "postgres_agent_migrator_password.txt"
write_if_absent "postgres_agent_app_password.txt"

write_if_absent "kafka_admin_password.txt"
write_if_absent "kafka_orchestrator_producer_password.txt"
write_if_absent "kafka_orchestrator_consumer_password.txt"
write_if_absent "kafka_agent_producer_password.txt"
write_if_absent "kafka_agent_consumer_password.txt"
write_if_absent "kafka_summarize_agent_producer_password.txt"
write_if_absent "kafka_summarize_agent_consumer_password.txt"
write_if_absent "kafka_review_agent_producer_password.txt"
write_if_absent "kafka_review_agent_consumer_password.txt"
write_if_absent "kafka_ui_review_agent_producer_password.txt"
write_if_absent "kafka_ui_review_agent_consumer_password.txt"
write_if_absent "kafka_architecture_review_agent_producer_password.txt"
write_if_absent "kafka_architecture_review_agent_consumer_password.txt"
write_if_absent "kafka_data_analysis_agent_producer_password.txt"
write_if_absent "kafka_data_analysis_agent_consumer_password.txt"

echo "Secrets are in ${SECRETS_DIR} (git-ignored)."
echo "Note: ai_router_anthropic_api_key.txt / ai_router_openai_api_key.txt are"
echo "checked-in, obviously-fake Sprint 9 placeholders (see infrastructure/README.md);"
echo "this script never generates or rotates them."
