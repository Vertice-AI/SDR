"""`process_turn` respeita o lock por conversa — turno concorrente reagenda
em vez de processar o mesmo buffer duas vezes (`docs/04` §2, roadmap 2.7)."""

import uuid

from app.core.locks import conversation_lock
from app.core.queue import get_arq_pool
from app.workers.inbound import process_turn


async def test_process_turn_processa_quando_lock_livre() -> None:
    pool = await get_arq_pool()
    conversation_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())

    await pool.rpush(f"buf:{conversation_id}", '{"text": "oi"}')

    await process_turn({"redis": pool}, tenant_id, conversation_id)

    restante = await pool.lrange(f"buf:{conversation_id}", 0, -1)
    assert restante == []


async def test_process_turn_reagenda_quando_lock_ocupado() -> None:
    pool = await get_arq_pool()
    conversation_id = str(uuid.uuid4())
    tenant_id = str(uuid.uuid4())

    await pool.rpush(f"buf:{conversation_id}", '{"text": "oi"}')

    async with conversation_lock(pool, conversation_id, ttl=30) as adquirido:
        assert adquirido is True
        # outro "worker" tentando processar o mesmo turno enquanto seguramos o lock
        await process_turn({"redis": pool}, tenant_id, conversation_id)

        # não drenou o buffer — só reagendou
        ainda_no_buffer = await pool.lrange(f"buf:{conversation_id}", 0, -1)
        assert ainda_no_buffer == [b'{"text": "oi"}']
