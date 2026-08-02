#!/usr/bin/env bash
# One-shot PostgreSQL bootstrap for the local Sprint 6 Compose topology.
#
# Runs as the database administrator only. It never runs application
# migrations with a runtime login, matching infrastructure/README.md:
#   - creates one LOGIN role per migration/runtime identity;
#   - migration logins receive their matching NOLOGIN permission role with
#     INHERIT FALSE, so a migration login must explicitly SET ROLE before it
#     can use elevated privileges;
#   - runtime logins receive their matching NOLOGIN permission role with the
#     default INHERIT, so the application connects and works without a
#     manual SET ROLE;
#   - infrastructure/postgresql/bootstrap_roles.sql (idempotent) runs before
#     any migration;
#   - each component migration then runs once, in order, through the login
#     that can only SET ROLE to its own migration role.
set -euo pipefail

PGHOST="${PGHOST:-postgres}"
PGPORT="${PGPORT:-5432}"
PGDATABASE="${PGDATABASE:-ai_platform}"
export PGPASSWORD
PGPASSWORD="$(cat /run/secrets/postgres_admin_password)"

psql_admin() {
    psql -v ON_ERROR_STOP=1 -h "${PGHOST}" -p "${PGPORT}" -U postgres -d "${PGDATABASE}" "$@"
}

echo "Waiting for PostgreSQL to accept connections..."
until psql_admin -c 'select 1' >/dev/null 2>&1; do
    sleep 1
done

echo "Ensuring database ${PGDATABASE} exists..."
psql -v ON_ERROR_STOP=1 -h "${PGHOST}" -p "${PGPORT}" -U postgres -d postgres -tc \
    "SELECT 1 FROM pg_database WHERE datname = '${PGDATABASE}'" | grep -q 1 || \
    psql -v ON_ERROR_STOP=1 -h "${PGHOST}" -p "${PGPORT}" -U postgres -d postgres -c \
    "CREATE DATABASE ${PGDATABASE}"

declare -A MIGRATOR_LOGIN=(
    [orchestrator]=ai_platform_orchestrator_migrator
    [agent]=ai_platform_agent_migrator
)
declare -A APP_LOGIN=(
    [orchestrator]=ai_platform_orchestrator_app
    [agent]=ai_platform_agent_app
)
declare -A MIGRATION_ROLE=(
    [orchestrator]=ai_platform_orchestrator_migration
    [agent]=ai_platform_agent_migration
)
declare -A RUNTIME_ROLE=(
    [orchestrator]=ai_platform_orchestrator_runtime
    [agent]=ai_platform_agent_runtime
)
declare -A MIGRATOR_SECRET=(
    [orchestrator]=/run/secrets/postgres_orchestrator_migrator_password
    [agent]=/run/secrets/postgres_agent_migrator_password
)
declare -A APP_SECRET=(
    [orchestrator]=/run/secrets/postgres_orchestrator_app_password
    [agent]=/run/secrets/postgres_agent_app_password
)

echo "Applying permission-role bootstrap (infrastructure/postgresql/bootstrap_roles.sql)..."
psql_admin -f /sql/postgresql/bootstrap_roles.sql

for component in orchestrator agent; do
    migrator_login="${MIGRATOR_LOGIN[$component]}"
    app_login="${APP_LOGIN[$component]}"
    migrator_password="$(cat "${MIGRATOR_SECRET[$component]}")"
    app_password="$(cat "${APP_SECRET[$component]}")"

    echo "Ensuring login roles for ${component}..."
    psql_admin -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${migrator_login}') THEN
        CREATE ROLE ${migrator_login} LOGIN PASSWORD '${migrator_password}';
    ELSE
        ALTER ROLE ${migrator_login} LOGIN PASSWORD '${migrator_password}';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${app_login}') THEN
        CREATE ROLE ${app_login} LOGIN PASSWORD '${app_password}';
    ELSE
        ALTER ROLE ${app_login} LOGIN PASSWORD '${app_password}';
    END IF;
END
\$\$;

GRANT ${MIGRATION_ROLE[$component]} TO ${migrator_login} WITH INHERIT FALSE;
GRANT ${RUNTIME_ROLE[$component]} TO ${app_login} WITH INHERIT TRUE;
SQL
done

echo "Applying orchestrator migration 0001 as ${MIGRATOR_LOGIN[orchestrator]}..."
PGPASSWORD="$(cat "${MIGRATOR_SECRET[orchestrator]}")" psql -v ON_ERROR_STOP=1 \
    -h "${PGHOST}" -p "${PGPORT}" -U "${MIGRATOR_LOGIN[orchestrator]}" -d "${PGDATABASE}" \
    -c "SET ROLE ${MIGRATION_ROLE[orchestrator]};" \
    -f /sql/migrations/0001_orchestrator_schema.sql

echo "Applying agent migration 0002 as ${MIGRATOR_LOGIN[agent]}..."
PGPASSWORD="$(cat "${MIGRATOR_SECRET[agent]}")" psql -v ON_ERROR_STOP=1 \
    -h "${PGHOST}" -p "${PGPORT}" -U "${MIGRATOR_LOGIN[agent]}" -d "${PGDATABASE}" \
    -c "SET ROLE ${MIGRATION_ROLE[agent]};" \
    -f /sql/migrations/0002_agent_schema.sql

echo "PostgreSQL bootstrap complete."
