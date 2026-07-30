"""extensoes postgres

Revision ID: 1869cd8ecc08
Revises:
Create Date: 2026-07-30 09:40:19.005779

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1869cd8ecc08"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # `unaccent()` é STABLE, não IMMUTABLE — Postgres recusa usá-la direto numa
    # coluna gerada (`knowledge_chunks.content_tsv`). Este wrapper declara a
    # função imutável, o que é seguro aqui: o dicionário de unaccent do tenant
    # não muda em runtime.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION immutable_unaccent(text)
        RETURNS text AS $$
            SELECT unaccent('unaccent', $1)
        $$ LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
        """
    )


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS immutable_unaccent(text)")
    op.execute("DROP EXTENSION IF EXISTS vector")
    op.execute("DROP EXTENSION IF EXISTS unaccent")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
