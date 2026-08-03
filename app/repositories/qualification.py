"""Repositório de qualificações — `docs/03-modelo-de-dados.md` §3."""

import uuid

from app.models import Qualification
from app.repositories.base import BaseRepository


class QualificationRepository(BaseRepository[Qualification]):
    model = Qualification

    async def get_by_conversation_id(self, conversation_id: uuid.UUID) -> Qualification | None:
        stmt = self.query().where(Qualification.conversation_id == conversation_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
