"""Dependências FastAPI compartilhadas (db, tenant, auth).

Autenticação e resolução de tenant por JWT entram na Fase 7
(`docs/11-roadmap-e-backlog.md`). Até lá, cada rota que precisar de sessão de
banco chama `TenantContext.set(...)` (por slug, por exemplo) antes de
depender de `DbSessionDep`.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.db import get_db_session

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSessionDep = Annotated[AsyncSession, Depends(get_db_session)]
