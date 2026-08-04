#!/usr/bin/env bash
# Run the external-service pytest suite from inside a throwaway container
# attached to the compose network, talking to PostgreSQL/Kafka by internal
# service name instead of through host-published ports.
#
# On some Windows/WSL2 hosts, the host->container port-forwarding path (be it
# WSL2's automatic localhost forwarding, netsh portproxy, or their
# combination) can accept a bare TCP connection while still failing to
# reliably relay actual protocol traffic -- see infrastructure/README.md.
# Running the test process on the same Podman network as the services
# sidesteps that path entirely and is also closer to how these tests would
# run in a real isolated CI environment.
#
# Requires: the infrastructure/compose/ topology already running
# (`podman compose up -d postgres kafka`), and infrastructure/compose/secrets/
# already generated.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

podman run --rm --network ai-platform-local_default \
    -v "${REPO_ROOT}:/workspace" -w /workspace \
    -e UV_PROJECT_ENVIRONMENT=/tmp/venv \
    -e AI_PLATFORM_TEST_POSTGRES_HOST=postgres \
    -e AI_PLATFORM_TEST_POSTGRES_PORT=5432 \
    -e AI_PLATFORM_TEST_KAFKA_BOOTSTRAP_SERVERS=kafka:9092 \
    -e AI_PLATFORM_TEST_SKIP_COMPOSE_UP=1 \
    ghcr.io/astral-sh/uv:0.11.8-python3.14-trixie-slim \
    bash -c "uv sync --locked && uv run pytest -m external_service tests/integration/ -v ${*:+"$@"}"
