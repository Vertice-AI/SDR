"""Repositório de canais — `docs/03-modelo-de-dados.md` §1."""

from app.models import Channel
from app.repositories.base import BaseRepository


class ChannelRepository(BaseRepository[Channel]):
    model = Channel

    async def get_by_provider(self, provider: str) -> Channel | None:
        stmt = self.query().where(Channel.provider == provider, Channel.status == "active")
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
