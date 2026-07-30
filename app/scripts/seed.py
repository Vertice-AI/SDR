"""Seed de tenant de demonstração (`make seed`).

Cria um tenant fictício com configuração, canal e vendedor, só para
desenvolvimento e testes manuais. Idempotente: se o tenant demo já existe,
não faz nada.
"""

import asyncio
import uuid

from app.core.db import tenant_session
from app.core.logging import get_logger
from app.models import Channel, Seller, Tenant, TenantConfig

logger = get_logger()

DEMO_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

_QUALIFICATION_FIELDS = [
    {
        "key": "dor_principal",
        "label": "Principal dor",
        "type": "text",
        "required": True,
        "weight": 30,
        "question_hint": "Descobrir o problema concreto que motivou o contato",
        "scoring": {"has_value": 30},
    },
    {
        "key": "faturamento_mensal",
        "label": "Faturamento mensal",
        "type": "enum",
        "options": ["ate_50k", "50k_200k", "200k_1m", "acima_1m"],
        "required": True,
        "weight": 30,
        "scoring": {"ate_50k": 0, "50k_200k": 15, "200k_1m": 30, "acima_1m": 30},
    },
    {
        "key": "decisor",
        "label": "É o decisor",
        "type": "enum",
        "options": ["sim", "influencia", "nao"],
        "required": True,
        "weight": 20,
        "scoring": {"sim": 20, "influencia": 12, "nao": 3},
    },
    {
        "key": "urgencia",
        "label": "Urgência",
        "type": "enum",
        "options": ["imediata", "3_meses", "sem_prazo"],
        "required": False,
        "weight": 20,
        "scoring": {"imediata": 20, "3_meses": 12, "sem_prazo": 4},
    },
]

_BUSINESS_HOURS = {
    dia: ["09:00", "18:00"] for dia in ("segunda", "terca", "quarta", "quinta", "sexta")
}


async def seed() -> None:
    async with tenant_session(DEMO_TENANT_ID) as session:
        if await session.get(Tenant, DEMO_TENANT_ID) is not None:
            logger.info("seed_ja_existe", tenant_id=str(DEMO_TENANT_ID))
            return

        tenant = Tenant(
            id=DEMO_TENANT_ID,
            slug="demo",
            name="Empresa Demo Ltda",
            status="active",
            timezone="America/Sao_Paulo",
            plan="demo",
            monthly_conversation_limit=0,
        )
        session.add(tenant)
        # Flush isolado: sem `relationship()` entre os models, o unit of work
        # não sabe que `channels`/`sellers`/`tenant_configs` dependem de
        # `tenants` e pode tentar inseri-los fora de ordem.
        await session.flush()

        session.add(
            TenantConfig(
                tenant_id=DEMO_TENANT_ID,
                version=1,
                is_active=True,
                agent_name="Ana",
                company_description=(
                    "A Empresa Demo ajuda pequenos negócios a organizarem as finanças."
                ),
                offer_description="Software de gestão financeira com suporte humano incluso.",
                icp_description=(
                    "Donos de pequenos negócios com faturamento entre R$ 50 mil e "
                    "R$ 1 milhão por mês."
                ),
                tone="consultivo",
                language="pt-BR",
                qualification_fields=_QUALIFICATION_FIELDS,
                forbidden_topics=["concorrentes", "política"],
                disqualification_rules=[],
                handoff_rules=[{"gatilho": "lead_pediu", "destino": "vendedor_responsavel"}],
                followup_cadence=[60, 1440, 4320],
                business_hours=_BUSINESS_HOURS,
            )
        )

        session.add(
            Channel(
                tenant_id=DEMO_TENANT_ID,
                provider="evolution",
                phone_number="+5511999990000",
                display_name="Demo WhatsApp",
                status="active",
                capabilities={"templates": False, "buttons": True, "audio": True},
            )
        )

        session.add(
            Seller(
                tenant_id=DEMO_TENANT_ID,
                name="Vendedor Demo",
                email="vendedor@demo.local",
                calendar_provider="none",
                calendar_id="primary",
                timezone="America/Sao_Paulo",
                availability_rules={},
            )
        )

        await session.flush()
        logger.info("seed_criado", tenant_id=str(DEMO_TENANT_ID), slug=tenant.slug)


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
