"""Configuração compartilhada de testes.

Define variáveis de ambiente obrigatórias ANTES de qualquer import de
`app.config`, para que `Settings()` nunca falhe em CI/local por falta de
segredo — sem depender de um `.env` versionado com dados sensíveis.
"""

import os

os.environ.setdefault("APP_SECRET_KEY", "test-secret-key")
# 32 bytes reais após base64-decode — `EncryptionError` se não for exatamente
# isso (`app/core/crypto.py`). A string anterior parecia certa mas decodifica
# para 30 bytes; só apareceu quando um teste passou a gravar coluna `_encrypted`.
os.environ.setdefault("APP_ENCRYPTION_KEY", "eUY8DUiJYhMv6C6UQehb1mPeHVLzzlmYOZan+UhsqMc=")
os.environ.setdefault("PHONE_HASH_PEPPER", "test-pepper")
# Role de runtime (sem BYPASSRLS) — testes de integração exercitam a mesma
# política de RLS que roda em produção (`docs/03` §6), não uma role superuser
# que a ignoraria silenciosamente.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://sdr_app:sdr_app@localhost:5432/sdr_test"
)
os.environ.setdefault("DATABASE_ADMIN_URL", "postgresql+asyncpg://sdr:sdr@localhost:5432/sdr_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
