"""Pool de conexão Redis do ARQ — compartilhado entre a API (enfileira jobs)
e o worker (consome). Singleton por processo, criado sob demanda."""

from arq import ArqRedis, create_pool
from arq.connections import RedisSettings

from app.config import get_settings

_pool: ArqRedis | None = None


async def get_arq_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    return _pool


async def close_arq_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
