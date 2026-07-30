"""Rate limiter simples por canal, via Redis — `docs/06-integracao-whatsapp.md`
§2 (limites por tier da Meta) e §4 item 4.

Contador por segundo corrido: não é um token bucket exato, mas evita
rajadas óbvias sem depender só do 429 de volta da API. É complementar ao
retry em 429 (`app/channels/http_errors.py`), não o substitui.
"""

import asyncio
import time

from arq import ArqRedis

_TENTATIVAS = 3
_ESPERA_SEGUNDOS = 1.0


async def allow_send(pool: ArqRedis, *, channel_id: str, max_per_second: int = 10) -> None:
    """Bloqueia (com poucas tentativas curtas) até o canal ter fôlego no rate
    limit local. Depois de `_TENTATIVAS`, deixa passar mesmo assim — a API
    do provedor é a autoridade final, isto é só uma cortesia."""
    for tentativa in range(_TENTATIVAS):
        janela = int(time.time())
        chave = f"ratelimit:{channel_id}:{janela}"
        contador = await pool.incr(chave)
        if contador == 1:
            await pool.expire(chave, 2)
        if contador <= max_per_second:
            return
        if tentativa < _TENTATIVAS - 1:
            await asyncio.sleep(_ESPERA_SEGUNDOS)
