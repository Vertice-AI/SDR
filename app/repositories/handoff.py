"""Repositório de handoffs — `docs/03-modelo-de-dados.md` §5."""

from app.models import Handoff
from app.repositories.base import BaseRepository


class HandoffRepository(BaseRepository[Handoff]):
    model = Handoff
