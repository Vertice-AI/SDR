"""Configuração do worker ARQ.

`process_turn` ainda é um stub (drena o buffer e loga) — o loop de tool
calling de verdade é a tarefa 3.4 (`docs/11-roadmap-e-backlog.md`).
"""

from typing import ClassVar

from arq.connections import RedisSettings

from app.config import get_settings
from app.workers.inbound import process_turn, process_webhook_event


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


class WorkerSettings:
    functions: ClassVar[list[object]] = [process_webhook_event, process_turn]
    redis_settings = _redis_settings()
