"""Dependências FastAPI compartilhadas (db, tenant, auth).

Nesta fase (0 — Fundação) só existe a dependência de configuração. `TenantContext`,
sessão de banco por request e autenticação entram na Fase 1 e na Fase 7
(`docs/11-roadmap-e-backlog.md`).
"""

from typing import Annotated

from fastapi import Depends

from app.config import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(get_settings)]
