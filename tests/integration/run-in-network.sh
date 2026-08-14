#!/usr/bin/env bash
# Run the external-service pytest suite from inside a throwaway container
# attached to the compose network, talking to PostgreSQL/Kafka by internal
# service name instead of through host-published ports.
#
# The topology runs on a dedicated Docker host (see infrastructure/README.md
# Section 1); this script must therefore also run there (over SSH), not on a
# developer's own machine -- Docker's `-v` bind mount below resolves against
# whichever machine's daemon runs it, and a remote daemon can't see a local
# path. Historically (through the Windows/Podman/WSL2 host, retired
# 2026-08-12) this script existed to sidestep an unreliable host->container
# port-forwarding path; on the current Docker-for-Mac host the published
# ports are directly reachable, so this is mainly useful now for CI-like
# isolated runs rather than working around host-forwarding flakiness.
#
# Requires: the infrastructure/compose/ topology already running
# (`docker compose up -d postgres kafka`), and infrastructure/compose/secrets/
# already generated.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

docker run --rm --network ai-platform-local_default \
    -v "${REPO_ROOT}:/workspace" -w /workspace \
    -e UV_PROJECT_ENVIRONMENT=/tmp/venv \
    -e AI_PLATFORM_TEST_POSTGRES_HOST=postgres \
    -e AI_PLATFORM_TEST_POSTGRES_PORT=5432 \
    -e AI_PLATFORM_TEST_KAFKA_BOOTSTRAP_SERVERS=kafka:9092 \
    -e AI_PLATFORM_TEST_SKIP_COMPOSE_UP=1 \
    ghcr.io/astral-sh/uv:0.11.8-python3.14-trixie-slim \
    bash -c 'uv sync --locked && uv run pytest -m external_service tests/integration/ -v "$@"' bash "$@"
