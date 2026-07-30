"""Repositório base — todo acesso a tabela de negócio passa por aqui.

Nunca faça `select(Model)` solto num handler ou serviço (`CLAUDE.md` §4.1).
O filtro de tenant é injetado automaticamente aqui a partir do
`TenantContext`; a política de RLS no Postgres (`docs/03` §6) é a segunda
linha de defesa, para o caso deste filtro ser esquecido em alguma query
manual.
"""

import uuid

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import TenantContext
from app.models.base import Base


class BaseRepository[ModelT: Base]:
    """Subclasse e defina `model = MeuModel`. Só funciona com models que têm
    `tenant_id` (`app.models.base.TenantMixin`)."""

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _tenant_id(self) -> uuid.UUID:
        return TenantContext.get()

    def query(self) -> Select[tuple[ModelT]]:
        return select(self.model).where(self.model.tenant_id == self._tenant_id())  # type: ignore[attr-defined]

    async def get(self, id_: uuid.UUID) -> ModelT | None:
        stmt = self.query().where(self.model.id == id_)  # type: ignore[attr-defined]
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(self) -> list[ModelT]:
        result = await self._session.execute(self.query())
        return list(result.scalars().all())

    async def add(self, instance: ModelT) -> ModelT:
        instance.tenant_id = self._tenant_id()  # type: ignore[attr-defined]
        self._session.add(instance)
        await self._session.flush()
        return instance

    async def delete(self, instance: ModelT) -> None:
        await self._session.delete(instance)
