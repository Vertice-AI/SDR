"""Webhook Meta Cloud API — `docs/06-integracao-whatsapp.md` §2.

`GET` verifica o `hub.challenge` na configuração do webhook. `POST` recebe
eventos (mensagens e/ou status de entrega) — persiste o evento cru, valida
a assinatura HMAC do corpo cru e enfileira, sem processar de forma síncrona
(`CLAUDE.md` §4.2).
"""

from typing import Any

import structlog
from fastapi import APIRouter, Request, Response

from app.channels.factory import build_adapter
from app.core.db import tenant_session
from app.core.queue import get_arq_pool
from app.core.tenancy import TenantContext
from app.models import WebhookEvent
from app.repositories.channel import ChannelRepository
from app.repositories.tenant import find_tenant_by_slug
from app.repositories.webhook_event import WebhookEventRepository

logger = structlog.get_logger()

router = APIRouter(prefix="/webhooks/meta", tags=["webhooks"])


def _event_type(payload: dict[str, Any]) -> str:
    tem_mensagem = False
    tem_status = False
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            tem_mensagem = tem_mensagem or bool(value.get("messages"))
            tem_status = tem_status or bool(value.get("statuses"))
    if tem_mensagem:
        return "messages"
    if tem_status:
        return "statuses"
    return "other"


@router.get("/{tenant_slug}")
async def verify_meta_webhook(tenant_slug: str, request: Request) -> Response:
    tenant = await find_tenant_by_slug(tenant_slug)
    if tenant is None:
        return Response(status_code=404)

    token = TenantContext.set(tenant.id)
    try:
        async with tenant_session(tenant.id) as session:
            channel = await ChannelRepository(session).get_by_provider("meta_cloud")
            if channel is None:
                return Response(status_code=404)
            adapter = build_adapter(channel)
            valido = await adapter.verify_webhook(dict(request.query_params), {}, b"")
    finally:
        TenantContext.reset(token)

    if not valido:
        logger.warning(
            "webhook_verificacao_invalida", tenant_id=str(tenant.id), provider="meta_cloud"
        )
        return Response(status_code=403)

    challenge = request.query_params.get("hub.challenge", "")
    return Response(content=challenge, media_type="text/plain")


@router.post("/{tenant_slug}")
async def receive_meta_webhook(tenant_slug: str, request: Request) -> Response:
    tenant = await find_tenant_by_slug(tenant_slug)
    if tenant is None:
        logger.warning(
            "webhook_tenant_nao_encontrado", tenant_slug=tenant_slug, provider="meta_cloud"
        )
        return Response(status_code=404)

    corpo_cru = await request.body()
    payload: dict[str, Any] = await request.json()

    token = TenantContext.set(tenant.id)
    try:
        async with tenant_session(tenant.id) as session:
            channel = await ChannelRepository(session).get_by_provider("meta_cloud")
            if channel is None:
                logger.warning(
                    "webhook_canal_nao_configurado",
                    tenant_id=str(tenant.id),
                    provider="meta_cloud",
                )
                return Response(status_code=404)

            adapter = build_adapter(channel)
            assinatura_valida = await adapter.verify_webhook(
                dict(request.query_params), dict(request.headers), corpo_cru
            )

            evento = WebhookEvent(
                provider="meta_cloud",
                event_type=_event_type(payload),
                payload=payload,
                signature_valid=assinatura_valida,
            )
            await WebhookEventRepository(session).add(evento)

            if not assinatura_valida:
                logger.warning(
                    "webhook_assinatura_invalida", tenant_id=str(tenant.id), provider="meta_cloud"
                )
                return Response(status_code=403)

            pool = await get_arq_pool()
            await pool.enqueue_job("process_webhook_event", str(tenant.id), str(evento.id))
    finally:
        TenantContext.reset(token)

    return Response(status_code=200)
