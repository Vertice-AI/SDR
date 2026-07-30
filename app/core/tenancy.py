"""Contexto do tenant corrente, propagado via `contextvar`.

Toda query de negócio precisa saber de qual tenant ela é. Em vez de passar
`tenant_id` manualmente por cada camada, um contextvar é setado uma vez por
request (dependência FastAPI) ou por job (worker ARQ) e lido pelo repositório
base e pela sessão de banco (`app/core/db.py`).
"""

import uuid
from contextvars import ContextVar, Token

from app.core.errors import TenantContextMissingError

_current_tenant_id: ContextVar[uuid.UUID | None] = ContextVar("current_tenant_id", default=None)


class TenantContext:
    @staticmethod
    def get() -> uuid.UUID:
        tenant_id = _current_tenant_id.get()
        if tenant_id is None:
            raise TenantContextMissingError("Nenhum tenant ativo no contexto atual.")
        return tenant_id

    @staticmethod
    def get_optional() -> uuid.UUID | None:
        return _current_tenant_id.get()

    @staticmethod
    def set(tenant_id: uuid.UUID) -> Token[uuid.UUID | None]:
        return _current_tenant_id.set(tenant_id)

    @staticmethod
    def reset(token: Token[uuid.UUID | None]) -> None:
        _current_tenant_id.reset(token)
