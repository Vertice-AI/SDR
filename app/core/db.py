"""Engine, sessão e escopo de tenant do banco de dados.

Toda transação de negócio roda com `app.tenant_id` setado via
`set_config(..., true)` — a política de RLS (`docs/03-modelo-de-dados.md`
§6) usa esse valor para filtrar linhas. O terceiro argumento `true` escopa o
valor à transação corrente (equivalente a `SET LOCAL`), liberado sozinho no
commit/rollback — por isso a sessão precisa abrir a transação antes de setar.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.core.tenancy import TenantContext

_settings = get_settings()

engine = create_async_engine(_settings.database_url, pool_pre_ping=True)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def tenant_session(tenant_id: uuid.UUID | None = None) -> AsyncIterator[AsyncSession]:
    """Abre uma sessão com transação escopada ao tenant corrente.

    Se `tenant_id` não for passado, usa o valor já setado no `TenantContext`
    — quem resolveu o tenant (slug do webhook, JWT do painel, job do worker)
    já chamou `TenantContext.set(...)` antes de chegar aqui.
    """
    resolved_tenant_id = tenant_id if tenant_id is not None else TenantContext.get()
    async with async_session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(resolved_tenant_id)},
        )
        yield session


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Dependência FastAPI: sessão de banco escopada ao tenant do `TenantContext`.

    Requer que uma dependência anterior já tenha resolvido o tenant e chamado
    `TenantContext.set(...)` (por slug no webhook, por JWT no painel — Fases 2 e 7).
    """
    async with tenant_session() as session:
        yield session
