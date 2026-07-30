-- Role de runtime da aplicação (`CLAUDE.md` §4.1, `docs/03` §6): sem
-- BYPASSRLS, para que a política de isolamento por tenant seja a única forma
-- de acessar dados de negócio. `sdr` (POSTGRES_USER, superuser) continua
-- sendo usado só pelas migrações (Alembic).
-- Credenciais de dev/local — nunca reaproveitar em produção.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sdr_app') THEN
        CREATE ROLE sdr_app LOGIN PASSWORD 'sdr_app' NOBYPASSRLS;
    END IF;
END
$$;

GRANT CONNECT ON DATABASE sdr TO sdr_app;
GRANT USAGE ON SCHEMA public TO sdr_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sdr_app;
