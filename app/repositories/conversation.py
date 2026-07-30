"""Repositório de conversas — `docs/03-modelo-de-dados.md` §2."""

import uuid

from app.models import Conversation
from app.repositories.base import BaseRepository

# Estados em que a conversa ainda é "a mesma" para fins de nova mensagem
# chegando — desqualificado/encerrado/opt_out abrem uma conversa nova.
_ESTADOS_ABERTOS = ("active", "awaiting_lead", "human_handoff", "scheduled")


class ConversationRepository(BaseRepository[Conversation]):
    model = Conversation

    async def get_open_by_contact_and_channel(
        self, contact_id: uuid.UUID, channel_id: uuid.UUID
    ) -> Conversation | None:
        stmt = self.query().where(
            Conversation.contact_id == contact_id,
            Conversation.channel_id == channel_id,
            Conversation.status.in_(_ESTADOS_ABERTOS),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
