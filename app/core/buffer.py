"""Buffer de mensagens com debounce — `docs/04-motor-de-conversa.md` §1.

Pessoas escrevem no WhatsApp em rajada; sem isso o agente responde a cada
fragmento — "o erro nº 1 de agentes de WhatsApp" (`CLAUDE.md` §4.3). Chaves
com TTL de segurança para nunca vazar memória do Redis se um job falhar no
meio do caminho.
"""

import json
from typing import Any

from arq import ArqRedis
from arq.jobs import Job

_HARD_CAP_SECONDS = 30


def _buf_key(conversation_id: str) -> str:
    return f"buf:{conversation_id}"


def _timer_key(conversation_id: str) -> str:
    return f"buftimer:{conversation_id}"


def _first_key(conversation_id: str) -> str:
    return f"buffirst:{conversation_id}"


async def enqueue_message(
    pool: ArqRedis,
    *,
    conversation_id: str,
    tenant_id: str,
    message: dict[str, Any],
    debounce_seconds: int,
) -> None:
    """Empilha `message` no buffer da conversa e (re)agenda `process_turn`,
    respeitando o debounce e o teto rígido de 30 s desde a primeira mensagem
    do turno."""
    buf_key = _buf_key(conversation_id)
    timer_key = _timer_key(conversation_id)
    first_key = _first_key(conversation_id)

    # Os stubs do redis-py tipam os métodos como `Awaitable[int] | int` (o
    # mesmo overload serve pipeline sync e cliente async) — inofensivo aqui.
    await pool.rpush(buf_key, json.dumps(message))  # type: ignore[misc]

    job_id_anterior = await pool.get(timer_key)

    ttl_restante = await pool.ttl(first_key)
    if ttl_restante is None or ttl_restante < 0:
        await pool.set(first_key, "1", ex=_HARD_CAP_SECONDS)
        segundos_desde_primeira = 0
    else:
        segundos_desde_primeira = _HARD_CAP_SECONDS - ttl_restante

    atraso = max(0, min(debounce_seconds, _HARD_CAP_SECONDS - segundos_desde_primeira))

    if job_id_anterior:
        job_id_str = (
            job_id_anterior.decode() if isinstance(job_id_anterior, bytes) else job_id_anterior
        )
        await Job(job_id_str, pool).abort()

    job = await pool.enqueue_job("process_turn", tenant_id, conversation_id, _defer_by=atraso)
    if job is not None:
        await pool.set(timer_key, job.job_id)


async def drain_buffer(pool: ArqRedis, *, conversation_id: str) -> list[dict[str, Any]]:
    """Lê e limpa o buffer de forma atômica — usado por `process_turn`
    (Fase 3) ao processar o turno como uma unidade só."""
    buf_key = _buf_key(conversation_id)
    async with pool.pipeline(transaction=True) as pipe:
        pipe.lrange(buf_key, 0, -1)
        pipe.delete(buf_key)
        itens, _ = await pipe.execute()
    return [json.loads(item) for item in itens]
