#!/usr/bin/env bash
# Generate application-facing secrets that compose from other already-
# generated secrets: full PostgreSQL DSNs (SecretFileReference reads one
# opaque string, so the DSN itself must be the file content) and the shared
# bearer credential the platform uses to call the Test Agent's readiness
# endpoint. Run scripts/generate-secrets.sh first.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SECRETS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)/secrets"

require() {
    if [ ! -f "${SECRETS_DIR}/$1" ]; then
        echo "missing ${SECRETS_DIR}/$1 -- run generate-secrets.sh first" >&2
        exit 1
    fi
}

require postgres_orchestrator_app_password.txt
require postgres_agent_app_password.txt

orchestrator_pw="$(cat "${SECRETS_DIR}/postgres_orchestrator_app_password.txt")"
agent_pw="$(cat "${SECRETS_DIR}/postgres_agent_app_password.txt")"

printf 'postgresql://ai_platform_orchestrator_app:%s@postgres:5432/ai_platform' "${orchestrator_pw}" \
    > "${SECRETS_DIR}/dsn_orchestrator.txt"
printf 'postgresql://ai_platform_agent_app:%s@postgres:5432/ai_platform' "${agent_pw}" \
    > "${SECRETS_DIR}/dsn_agent.txt"

if [ ! -f "${SECRETS_DIR}/readiness_credential.txt" ]; then
    openssl rand -base64 32 | tr -d '\n=+/' | cut -c1-32 > "${SECRETS_DIR}/readiness_credential.txt"
    echo "generated: readiness_credential.txt"
else
    echo "exists: readiness_credential.txt"
fi

echo "generated: dsn_orchestrator.txt"
echo "generated: dsn_agent.txt"
