"""Configuração do worker ARQ.

As tasks (`inbound_message`, `process_turn`, `send_followup`, ...) entram nas
Fases 2 e 3 (`docs/11-roadmap-e-backlog.md`). Por ora só a infraestrutura de
conexão ao Redis, para o worker subir e ficar pronto para receber jobs.
"""

from typing import ClassVar

from arq.connections import RedisSettings

from app.config import get_settings


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


class WorkerSettings:
    functions: ClassVar[list[object]] = []
    redis_settings = _redis_settings()
