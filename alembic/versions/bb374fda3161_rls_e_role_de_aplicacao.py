"""rls e role de aplicacao

Revision ID: bb374fda3161
Revises: 05548fd5a994
Create Date: 2026-07-30 09:44:17.641919

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bb374fda3161"
down_revision: str | Sequence[str] | None = "05548fd5a994"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Toda tabela com `tenant_id` (gerado a partir de `Base.metadata` — ver
# comando usado para produzir esta lista no commit desta migração). `tenants`
# fica de fora: não tem `tenant_id`, é a própria raiz do isolamento.
_TENANT_TABLES = (
    "channels",
    "contacts",
    "faq_entries",
    "knowledge_documents",
    "users",
    "webhook_events",
    "audit_logs",
    "consents",
    "knowledge_chunks",
    "message_templates",
    "sellers",
    "tenant_configs",
    "conversations",
    "agent_runs",
    "appointments",
    "crm_sync_log",
    "messages",
    "qualifications",
    "followups",
    "handoffs",
)


def upgrade() -> None:
    # Role de runtime sem BYPASSRLS (`CLAUDE.md` §4.1). Idempotente: já pode
    # ter sido criada por `docker/postgres-init/02-app-role.sql` num volume
    # novo — aqui é a garantia que vale em qualquer ambiente, novo ou existente.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sdr_app') THEN
                CREATE ROLE sdr_app LOGIN PASSWORD 'sdr_app' NOBYPASSRLS;
            END IF;
        END
        $$
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO sdr_app")
    # `tenants` não tem `tenant_id` (é a raiz do isolamento, não há o que
    # filtrar por RLS), mas a aplicação ainda lê/escreve essa tabela.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON tenants TO sdr_app")

    for table in _TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = current_setting('app.tenant_id', true)::uuid)"
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO sdr_app")


def downgrade() -> None:
    for table in _TENANT_TABLES:
        op.execute(f"REVOKE SELECT, INSERT, UPDATE, DELETE ON {table} FROM sdr_app")
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.execute("REVOKE SELECT, INSERT, UPDATE, DELETE ON tenants FROM sdr_app")
    op.execute("REVOKE USAGE ON SCHEMA public FROM sdr_app")
