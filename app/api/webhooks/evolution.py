"""Webhook Evolution API — `docs/06-integracao-whatsapp.md` §3.

Responde 200 rápido: valida assinatura, persiste o evento cru, enfileira o
processamento e retorna — nenhum processamento síncrono aqui (`CLAUDE.md`
§4.2). A idempotência de verdade (não mandar mensagem duplicada) é a
`UNIQUE(tenant_id, provider_message_id)` de `messages`, aplicada no worker
(tarefa 2.5) — aqui todo POST vira uma linha em `webhook_events`, mesmo
reenviado, porque isso é o registro de auditoria.
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

router = APIRouter(prefix="/webhooks/evolution", tags=["webhooks"])


@router.post("/{tenant_slug}")
async def receive_evolution_webhook(tenant_slug: str, request: Request) -> Response:
    tenant = await find_tenant_by_slug(tenant_slug)
    if tenant is None:
        logger.warning(
            "webhook_tenant_nao_encontrado", tenant_slug=tenant_slug, provider="evolution"
        )
        return Response(status_code=404)

    corpo_cru = await request.body()
    payload: dict[str, Any] = await request.json()

    token = TenantContext.set(tenant.id)
    try:
        async with tenant_session(tenant.id) as session:
            channel = await ChannelRepository(session).get_by_provider("evolution")
            if channel is None:
                logger.warning(
                    "webhook_canal_nao_configurado",
                    tenant_id=str(tenant.id),
                    provider="evolution",
                )
                return Response(status_code=404)

            adapter = build_adapter(channel)
            assinatura_valida = await adapter.verify_webhook(
                dict(request.query_params), dict(request.headers), corpo_cru
            )

            evento = WebhookEvent(
                provider="evolution",
                event_type=payload.get("event", "unknown"),
                payload=payload,
                signature_valid=assinatura_valida,
            )
            await WebhookEventRepository(session).add(evento)

            if not assinatura_valida:
                logger.warning(
                    "webhook_assinatura_invalida", tenant_id=str(tenant.id), provider="evolution"
                )
                return Response(status_code=403)

            pool = await get_arq_pool()
            await pool.enqueue_job("process_webhook_event", str(tenant.id), str(evento.id))
    finally:
        TenantContext.reset(token)

    return Response(status_code=200)
