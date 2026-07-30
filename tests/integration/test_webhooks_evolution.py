"""Webhook Evolution ponta a ponta contra o schema real — sem instância de
verdade (`docs/06` §3, roadmap 2.4). Usa `httpx.ASGITransport` (não
`TestClient`) para rodar o app no mesmo event loop da sessão de teste — a
engine async do SQLAlchemy é um singleton de módulo e não sobrevive a troca
de loop (mesma lição da Fase 1)."""

import json
import uuid
from collections.abc import AsyncGenerator

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.core.db import tenant_session
from app.main import create_app
from app.models import Channel, Tenant, WebhookEvent

_WEBHOOK_TOKEN = "webhook-secret-evolution"


@pytest.fixture
async def tenant_evolution() -> AsyncGenerator[tuple[str, uuid.UUID], None]:
    settings = get_settings()
    admin_engine = create_async_engine(settings.database_admin_url or settings.database_url)
    admin_session_factory = async_sessionmaker(admin_engine, expire_on_commit=False)

    tenant_id = uuid.uuid4()
    slug = f"evo-{tenant_id.hex[:8]}"

    async with admin_session_factory() as session:
        session.add(Tenant(id=tenant_id, slug=slug, name="Tenant Evolution Teste"))
        await session.commit()

        session.add(
            Channel(
                tenant_id=tenant_id,
                provider="evolution",
                phone_number=f"+55119{tenant_id.int % 100000000:08d}",
                status="active",
                credentials_encrypted=json.dumps(
                    {
                        "base_url": "http://localhost:8080",
                        "api_key": "instance-key",
                        "instance_name": "tenant-demo",
                    }
                ),
                webhook_verify_token_encrypted=_WEBHOOK_TOKEN,
                capabilities={"typing": True},
            )
        )
        await session.commit()

    try:
        yield slug, tenant_id
    finally:
        async with admin_session_factory() as session:
            await session.execute(delete(Channel).where(Channel.tenant_id == tenant_id))
            await session.execute(delete(Tenant).where(Tenant.id == tenant_id))
            await session.commit()
        await admin_engine.dispose()


async def test_webhook_tenant_inexistente_retorna_404() -> None:
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/webhooks/evolution/slug-que-nao-existe", json={"event": "messages.upsert", "data": {}}
        )

    assert response.status_code == 404


async def test_webhook_apikey_correta_persiste_evento_e_retorna_200(
    tenant_evolution: tuple[str, uuid.UUID],
) -> None:
    slug, tenant_id = tenant_evolution
    payload = {
        "event": "messages.upsert",
        "instance": "tenant-demo",
        "data": {
            "key": {
                "remoteJid": "5511988887777@s.whatsapp.net",
                "fromMe": False,
                "id": "ID_TESTE_1",
            },
            "pushName": "Maria",
            "message": {"conversation": "oi, vi o anúncio"},
            "messageTimestamp": 1735689600,
        },
    }
    app = create_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/webhooks/evolution/{slug}", json=payload, headers={"apikey": _WEBHOOK_TOKEN}
        )

    assert response.status_code == 200

    async with tenant_session(tenant_id) as session:
        eventos = (
            (await session.execute(select(WebhookEvent).where(WebhookEvent.tenant_id == tenant_id)))
            .scalars()
            .all()
        )
    assert len(eventos) == 1
    assert eventos[0].signature_valid is True
    assert eventos[0].event_type == "messages.upsert"


async def test_webhook_apikey_errada_retorna_403_mas_persiste_evento(
    tenant_evolution: tuple[str, uuid.UUID],
) -> None:
    slug, tenant_id = tenant_evolution
    app = create_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/webhooks/evolution/{slug}",
            json={"event": "messages.upsert", "data": {}},
            headers={"apikey": "chave-errada"},
        )

    assert response.status_code == 403

    async with tenant_session(tenant_id) as session:
        eventos = (
            (await session.execute(select(WebhookEvent).where(WebhookEvent.tenant_id == tenant_id)))
            .scalars()
            .all()
        )
    assert len(eventos) == 1
    assert eventos[0].signature_valid is False
