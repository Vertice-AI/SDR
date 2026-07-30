"""Webhook Meta Cloud API ponta a ponta contra o schema real — sem número
oficial registrado (`docs/06` §2, roadmap 2.4). Ver nota sobre
`httpx.ASGITransport` em `test_webhooks_evolution.py`."""

import hashlib
import hmac
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

_VERIFY_TOKEN = "verify-token-meta-teste"
_APP_SECRET = "app-secret-meta-teste"


@pytest.fixture
async def tenant_meta() -> AsyncGenerator[tuple[str, uuid.UUID], None]:
    settings = get_settings()
    admin_engine = create_async_engine(settings.database_admin_url or settings.database_url)
    admin_session_factory = async_sessionmaker(admin_engine, expire_on_commit=False)

    tenant_id = uuid.uuid4()
    slug = f"meta-{tenant_id.hex[:8]}"

    async with admin_session_factory() as session:
        session.add(Tenant(id=tenant_id, slug=slug, name="Tenant Meta Teste"))
        await session.commit()

        session.add(
            Channel(
                tenant_id=tenant_id,
                provider="meta_cloud",
                phone_number=f"+55119{tenant_id.int % 100000000:08d}",
                status="active",
                credentials_encrypted=json.dumps(
                    {
                        "access_token": "token-permanente",
                        "phone_number_id": "1234567890",
                        "app_secret": _APP_SECRET,
                    }
                ),
                webhook_verify_token_encrypted=_VERIFY_TOKEN,
                capabilities={"templates": True},
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


async def test_get_verificacao_aceita_token_correto_e_ecoa_challenge(
    tenant_meta: tuple[str, uuid.UUID],
) -> None:
    slug, _tenant_id = tenant_meta
    app = create_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/webhooks/meta/{slug}",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": _VERIFY_TOKEN,
                "hub.challenge": "desafio123",
            },
        )

    assert response.status_code == 200
    assert response.text == "desafio123"


async def test_get_verificacao_rejeita_token_errado(tenant_meta: tuple[str, uuid.UUID]) -> None:
    slug, _tenant_id = tenant_meta
    app = create_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/webhooks/meta/{slug}",
            params={"hub.mode": "subscribe", "hub.verify_token": "errado", "hub.challenge": "x"},
        )

    assert response.status_code == 403


async def test_post_com_assinatura_valida_persiste_evento_e_retorna_200(
    tenant_meta: tuple[str, uuid.UUID],
) -> None:
    slug, tenant_id = tenant_meta
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"display_phone_number": "15550001111"},
                            "contacts": [{"profile": {"name": "Maria"}, "wa_id": "5511988887777"}],
                            "messages": [
                                {
                                    "from": "5511988887777",
                                    "id": "wamid.TESTE1",
                                    "timestamp": "1735689600",
                                    "type": "text",
                                    "text": {"body": "oi, quanto custa?"},
                                }
                            ],
                        }
                    }
                ]
            }
        ],
    }
    corpo = json.dumps(payload).encode()
    assinatura = hmac.new(_APP_SECRET.encode(), corpo, hashlib.sha256).hexdigest()

    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/webhooks/meta/{slug}",
            content=corpo,
            headers={
                "content-type": "application/json",
                "x-hub-signature-256": f"sha256={assinatura}",
            },
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
    assert eventos[0].event_type == "messages"


async def test_post_com_assinatura_invalida_retorna_403(
    tenant_meta: tuple[str, uuid.UUID],
) -> None:
    slug, tenant_id = tenant_meta
    corpo = json.dumps({"entry": []}).encode()

    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/webhooks/meta/{slug}",
            content=corpo,
            headers={
                "content-type": "application/json",
                "x-hub-signature-256": "sha256=assinatura_errada",
            },
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
