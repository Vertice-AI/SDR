"""Teste obrigatório de `docs/03-modelo-de-dados.md` §6: com o contexto de um
tenant, nenhuma query enxerga linha de outro tenant — nem pedindo o `id` dele
explicitamente na cláusula `WHERE`. RLS é a segunda linha de defesa
(`CLAUDE.md` §4.1); este teste garante que ela está realmente ligada.
"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.core.db import tenant_session
from app.models import Contact, Tenant


@pytest.fixture
async def duas_tenants_com_contato() -> AsyncGenerator[tuple[uuid.UUID, uuid.UUID], None]:
    settings = get_settings()
    admin_engine = create_async_engine(settings.database_admin_url or settings.database_url)
    admin_session_factory = async_sessionmaker(admin_engine, expire_on_commit=False)

    tenant_a_id = uuid.uuid4()
    tenant_b_id = uuid.uuid4()

    async with admin_session_factory() as session:
        session.add_all(
            [
                Tenant(id=tenant_a_id, slug=f"teste-a-{tenant_a_id.hex[:8]}", name="Tenant A"),
                Tenant(id=tenant_b_id, slug=f"teste-b-{tenant_b_id.hex[:8]}", name="Tenant B"),
            ]
        )
        await session.commit()

        session.add_all(
            [
                Contact(
                    tenant_id=tenant_a_id,
                    phone_e164="+5511900000001",
                    phone_hash="hash-tenant-a",
                    source="desconhecido",
                ),
                Contact(
                    tenant_id=tenant_b_id,
                    phone_e164="+5511900000002",
                    phone_hash="hash-tenant-b",
                    source="desconhecido",
                ),
            ]
        )
        await session.commit()

    try:
        yield tenant_a_id, tenant_b_id
    finally:
        async with admin_session_factory() as session:
            await session.execute(
                delete(Contact).where(Contact.tenant_id.in_([tenant_a_id, tenant_b_id]))
            )
            await session.execute(delete(Tenant).where(Tenant.id.in_([tenant_a_id, tenant_b_id])))
            await session.commit()
        await admin_engine.dispose()


async def test_tenant_a_nao_enxerga_contato_do_tenant_b(
    duas_tenants_com_contato: tuple[uuid.UUID, uuid.UUID],
) -> None:
    tenant_a_id, tenant_b_id = duas_tenants_com_contato

    async with tenant_session(tenant_a_id) as session:
        visiveis = (await session.execute(select(Contact))).scalars().all()
        assert {c.tenant_id for c in visiveis} == {tenant_a_id}

        # Mesmo pedindo o id do tenant B explicitamente no WHERE, RLS bloqueia.
        forcando_tenant_b = (
            (await session.execute(select(Contact).where(Contact.tenant_id == tenant_b_id)))
            .scalars()
            .all()
        )
        assert forcando_tenant_b == []


async def test_tenant_b_so_enxerga_o_proprio_contato(
    duas_tenants_com_contato: tuple[uuid.UUID, uuid.UUID],
) -> None:
    _tenant_a_id, tenant_b_id = duas_tenants_com_contato

    async with tenant_session(tenant_b_id) as session:
        visiveis = (await session.execute(select(Contact))).scalars().all()
        assert {c.tenant_id for c in visiveis} == {tenant_b_id}
