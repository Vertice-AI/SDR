"""Lock distribuído por conversa, via Redis — `docs/04-motor-de-conversa.md`
§2 (`CLAUDE.md` §4.4).

Sem lock, dois turnos concorrentes geram duas respostas simultâneas e o
histórico fica incoerente. O lock guarda um token aleatório para nunca
liberar o lock de outro processo — se o TTL expirou e outro worker já
adquiriu o lock antes da gente terminar, nosso `finally` não pode apagá-lo.
"""

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from redis.asyncio import Redis

# Só apaga a chave se o valor ainda for o nosso token — atômico, via Lua,
# pra não virar um "get depois delete" com corrida no meio.
_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


def _lock_key(conversation_id: str) -> str:
    return f"lock:conv:{conversation_id}"


@asynccontextmanager
async def conversation_lock(
    redis: Redis, conversation_id: str, *, ttl: int = 120
) -> AsyncIterator[bool]:
    """Tenta adquirir o lock da conversa. Produz `True`/`False` conforme
    conseguiu — quem chama decide o que fazer se não conseguiu (reagendar o
    turno, nunca processar sem o lock)."""
    token = secrets.token_hex(16)
    key = _lock_key(conversation_id)
    adquirido = bool(await redis.set(key, token, nx=True, ex=ttl))
    try:
        yield adquirido
    finally:
        if adquirido:
            await redis.eval(_RELEASE_SCRIPT, 1, key, token)  # type: ignore[misc]
