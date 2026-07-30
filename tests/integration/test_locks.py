"""Lock distribuído por conversa — `docs/04-motor-de-conversa.md` §2,
`CLAUDE.md` §4.4. Redis real (já roda local via docker-compose); é
comportamento de concorrência, não faz sentido mockar."""

import uuid

from redis.asyncio import Redis

from app.config import get_settings
from app.core.locks import conversation_lock


def _redis_de_teste() -> Redis:
    return Redis.from_url(get_settings().redis_url)


async def test_adquire_lock_quando_livre() -> None:
    redis = _redis_de_teste()
    conversation_id = str(uuid.uuid4())
    async with conversation_lock(redis, conversation_id, ttl=5) as adquirido:
        assert adquirido is True
    await redis.aclose()


async def test_segunda_tentativa_falha_enquanto_lock_esta_preso() -> None:
    redis = _redis_de_teste()
    conversation_id = str(uuid.uuid4())

    async with conversation_lock(redis, conversation_id, ttl=5) as adquirido_1:
        assert adquirido_1 is True
        async with conversation_lock(redis, conversation_id, ttl=5) as adquirido_2:
            assert adquirido_2 is False

    await redis.aclose()


async def test_lock_liberado_pode_ser_readquirido() -> None:
    redis = _redis_de_teste()
    conversation_id = str(uuid.uuid4())

    async with conversation_lock(redis, conversation_id, ttl=5):
        pass

    async with conversation_lock(redis, conversation_id, ttl=5) as adquirido:
        assert adquirido is True

    await redis.aclose()


async def test_release_nunca_apaga_lock_de_outro_dono() -> None:
    """Simula o TTL expirar e outro worker adquirir o lock antes da gente
    terminar — nosso `finally` não pode apagar o lock do outro."""
    redis = _redis_de_teste()
    conversation_id = str(uuid.uuid4())
    key = f"lock:conv:{conversation_id}"

    async with conversation_lock(redis, conversation_id, ttl=5):
        # troca o valor da chave "por baixo", como se o TTL tivesse expirado
        # e outro processo tivesse adquirido o lock com um token diferente.
        await redis.set(key, "token-de-outro-worker", ex=30)

    valor_atual = await redis.get(key)
    assert valor_atual == b"token-de-outro-worker"

    await redis.delete(key)
    await redis.aclose()
