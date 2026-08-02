-- PostgreSQL permission-role bootstrap for Vertical Slice 01.
-- Run once as a trusted database administrator before component migrations.
-- These roles deliberately cannot log in and therefore carry no credentials.

\set ON_ERROR_STOP on

BEGIN;

DO $bootstrap$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ai_platform_orchestrator_migration') THEN
        CREATE ROLE ai_platform_orchestrator_migration NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ai_platform_orchestrator_runtime') THEN
        CREATE ROLE ai_platform_orchestrator_runtime NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ai_platform_agent_migration') THEN
        CREATE ROLE ai_platform_agent_migration NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ai_platform_agent_runtime') THEN
        CREATE ROLE ai_platform_agent_runtime NOLOGIN;
    END IF;
END
$bootstrap$;

ALTER ROLE ai_platform_orchestrator_migration
    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER ROLE ai_platform_orchestrator_runtime
    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER ROLE ai_platform_agent_migration
    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER ROLE ai_platform_agent_runtime
    NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;

REVOKE ALL ON SCHEMA public FROM PUBLIC;

-- CREATE SCHEMA (even IF NOT EXISTS, against an already-existing schema)
-- requires database-level CREATE privilege, which non-owner roles do not
-- have by default. Grant it only to the two migration roles, matching their
-- narrow purpose of owning component schema evolution.
DO $grant_database_create$
BEGIN
    EXECUTE format(
        'GRANT CREATE ON DATABASE %I TO ai_platform_orchestrator_migration, ai_platform_agent_migration',
        current_database()
    );
END
$grant_database_create$;

CREATE SCHEMA IF NOT EXISTS orchestrator
    AUTHORIZATION ai_platform_orchestrator_migration;
CREATE SCHEMA IF NOT EXISTS agent
    AUTHORIZATION ai_platform_agent_migration;
ALTER SCHEMA orchestrator OWNER TO ai_platform_orchestrator_migration;
ALTER SCHEMA agent OWNER TO ai_platform_agent_migration;

REVOKE ALL ON SCHEMA orchestrator FROM PUBLIC;
REVOKE ALL ON SCHEMA agent FROM PUBLIC;
REVOKE ALL ON SCHEMA agent FROM ai_platform_orchestrator_migration;
REVOKE ALL ON SCHEMA agent FROM ai_platform_orchestrator_runtime;
REVOKE ALL ON SCHEMA orchestrator FROM ai_platform_agent_migration;
REVOKE ALL ON SCHEMA orchestrator FROM ai_platform_agent_runtime;

GRANT USAGE ON SCHEMA orchestrator TO ai_platform_orchestrator_runtime;
REVOKE CREATE ON SCHEMA orchestrator FROM ai_platform_orchestrator_runtime;
GRANT USAGE ON SCHEMA agent TO ai_platform_agent_runtime;
REVOKE CREATE ON SCHEMA agent FROM ai_platform_agent_runtime;

ALTER DEFAULT PRIVILEGES FOR ROLE ai_platform_orchestrator_migration
    IN SCHEMA orchestrator REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE ai_platform_orchestrator_migration
    IN SCHEMA orchestrator REVOKE ALL ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE ai_platform_orchestrator_migration
    IN SCHEMA orchestrator GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES
    TO ai_platform_orchestrator_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE ai_platform_orchestrator_migration
    IN SCHEMA orchestrator GRANT USAGE, SELECT ON SEQUENCES
    TO ai_platform_orchestrator_runtime;

ALTER DEFAULT PRIVILEGES FOR ROLE ai_platform_agent_migration
    IN SCHEMA agent REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE ai_platform_agent_migration
    IN SCHEMA agent REVOKE ALL ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE ai_platform_agent_migration
    IN SCHEMA agent GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES
    TO ai_platform_agent_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE ai_platform_agent_migration
    IN SCHEMA agent GRANT USAGE, SELECT ON SEQUENCES
    TO ai_platform_agent_runtime;

-- Make rerunning the bootstrap safe after objects already exist.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA orchestrator
    TO ai_platform_orchestrator_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA orchestrator
    TO ai_platform_orchestrator_runtime;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA agent
    TO ai_platform_agent_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA agent
    TO ai_platform_agent_runtime;

REVOKE ALL ON ALL TABLES IN SCHEMA agent FROM ai_platform_orchestrator_runtime;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA agent FROM ai_platform_orchestrator_runtime;
REVOKE ALL ON ALL TABLES IN SCHEMA orchestrator FROM ai_platform_agent_runtime;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA orchestrator FROM ai_platform_agent_runtime;

COMMIT;
