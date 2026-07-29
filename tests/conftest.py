"""Configuração compartilhada de testes.

Define variáveis de ambiente obrigatórias ANTES de qualquer import de
`app.config`, para que `Settings()` nunca falhe em CI/local por falta de
segredo — sem depender de um `.env` versionado com dados sensíveis.
"""

import os

os.environ.setdefault("APP_SECRET_KEY", "test-secret-key")
os.environ.setdefault("APP_ENCRYPTION_KEY", "dGVzdC1lbmNyeXB0aW9uLWtleS0zMi1ieXRlcyEh")
os.environ.setdefault("PHONE_HASH_PEPPER", "test-pepper")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://sdr:sdr@localhost:5432/sdr_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
