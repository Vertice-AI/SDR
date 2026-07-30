"""Resolução de tenant por slug — usada no bootstrap do webhook, antes de
existir qualquer `TenantContext` (`docs/03` §1: slug é usado na URL do
webhook). `tenants` não tem `tenant_id`/RLS, então essa consulta não
depende de contexto de tenant."""

from sqlalchemy import select

from app.core.db import async_session_factory
from app.models import Tenant


async def find_tenant_by_slug(slug: str) -> Tenant | None:
    async with async_session_factory() as session:
        result = await session.execute(select(Tenant).where(Tenant.slug == slug))
        return result.scalar_one_or_none()
