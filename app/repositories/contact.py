"""Repositório de contatos (leads) — `docs/03-modelo-de-dados.md` §2."""

from app.models import Contact
from app.repositories.base import BaseRepository


class ContactRepository(BaseRepository[Contact]):
    model = Contact

    async def get_by_phone(self, phone_e164: str) -> Contact | None:
        stmt = self.query().where(Contact.phone_e164 == phone_e164)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
