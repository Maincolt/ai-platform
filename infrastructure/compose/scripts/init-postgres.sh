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

declare -A SCHEMA_NAME=(
    [orchestrator]=orchestrator
    [agent]=agent
)

# Component migrations are not all internally idempotent (some do a plain
# ALTER TABLE ... RENAME/TYPE-change with no IF EXISTS guard, unlike the
# CREATE-style 0001/0002). This step re-runs on every `docker compose up`
# that has platform/test-agent/summarize-agent as a dependency, not just on
# a genuinely fresh database, so each migration is skipped once its
# component's schema_version already meets or exceeds its target -- found
# during Sprint 10's topology re-validation, where a second, dependency-
# triggered run of this script against an already-migrated database failed
# on 0003's non-idempotent RENAME COLUMN.
apply_migration() {
    local component="$1" target_version="$2" file="$3" description="$4"
    local schema="${SCHEMA_NAME[$component]}"
    local migrator_login="${MIGRATOR_LOGIN[$component]}"
    local migration_role="${MIGRATION_ROLE[$component]}"
    local current
    # Before the first migration ever runs, `${schema}.schema_version` does
    # not exist yet -- psql_admin's ON_ERROR_STOP=1 makes that probe query
    # itself fail, which `set -e`/`pipefail` would otherwise treat as this
    # function failing. That failure is expected and means "not yet
    # migrated" (current=0), not a real error, so it is deliberately
    # swallowed here rather than propagated.
    current="$(psql_admin -tAc \
        "SELECT version FROM ${schema}.schema_version WHERE component = '${component}'" \
        2>/dev/null | tr -d '[:space:]')" || current=""
    if [ -z "${current}" ]; then
        current=0
    fi
    if [ "${current}" -ge "${target_version}" ]; then
        echo "Skipping ${description} (schema already at version ${current} >= ${target_version})"
        return 0
    fi
    echo "Applying ${description} as ${migrator_login}..."
    PGPASSWORD="$(cat "${MIGRATOR_SECRET[$component]}")" psql -v ON_ERROR_STOP=1 \
        -h "${PGHOST}" -p "${PGPORT}" -U "${migrator_login}" -d "${PGDATABASE}" \
        -c "SET ROLE ${migration_role};" \
        -f "${file}"
}

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

apply_migration orchestrator 1 /sql/migrations/0001_orchestrator_schema.sql \
    "orchestrator migration 0001"
apply_migration agent 1 /sql/migrations/0002_agent_schema.sql \
    "agent migration 0002"
apply_migration orchestrator 2 /sql/migrations/0003_orchestrator_generalize_result.sql \
    "orchestrator migration 0003"
apply_migration agent 2 /sql/migrations/0004_agent_generalize_result.sql \
    "agent migration 0004"
apply_migration orchestrator 3 /sql/migrations/0005_orchestrator_command_capability_routing.sql \
    "orchestrator migration 0005"
apply_migration agent 3 /sql/migrations/0006_agent_command_capability_routing.sql \
    "agent migration 0006"
apply_migration agent 4 /sql/migrations/0007_agent_provider_call_claims.sql \
    "agent migration 0007"

echo "PostgreSQL bootstrap complete."
