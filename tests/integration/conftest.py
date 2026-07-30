"""Sobe o banco `sdr_test` real (extensões, schema, RLS, role `sdr_app`) uma
vez por sessão de teste, rodando as migrações do Alembic de verdade — testes
de integração validam o schema e a RLS que rodam em produção, não um mock.
"""

import asyncio
from pathlib import Path

import asyncpg
import pytest
from alembic import command
from alembic.config import Config

_REPO_ROOT = Path(__file__).resolve().parents[2]


async def _ensure_database() -> None:
    conn = await asyncpg.connect(
        user="sdr", password="sdr", host="localhost", port=5432, database="postgres"
    )
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = 'sdr_test'")
        if not exists:
            await conn.execute("CREATE DATABASE sdr_test")
    finally:
        await conn.close()


def _migrate() -> None:
    config = Config(str(_REPO_ROOT / "alembic.ini"))
    command.upgrade(config, "head")


@pytest.fixture(scope="session", autouse=True)
def sdr_test_schema() -> None:
    asyncio.run(_ensure_database())
    _migrate()
