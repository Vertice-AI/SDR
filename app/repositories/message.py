"""Repositório de mensagens — `docs/03-modelo-de-dados.md` §2."""

from app.models import Message
from app.repositories.base import BaseRepository


class MessageRepository(BaseRepository[Message]):
    model = Message
