"""Resolução de contato e conversa a partir de uma mensagem recebida —
`docs/04-motor-de-conversa.md`, roadmap 2.5."""

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.logging import hash_phone
from app.models import Contact, Conversation
from app.repositories.contact import ContactRepository
from app.repositories.conversation import ConversationRepository


async def get_or_create_contact(
    session: AsyncSession, *, phone_e164: str, profile_name: str | None, now: datetime
) -> Contact:
    repo = ContactRepository(session)
    contact = await repo.get_by_phone(phone_e164)
    if contact is not None:
        contact.last_contact_at = now
        if profile_name and not contact.name:
            contact.name = profile_name
        return contact

    settings = get_settings()
    contact = Contact(
        phone_e164=phone_e164,
        phone_hash=hash_phone(phone_e164, pepper=settings.phone_hash_pepper),
        name=profile_name,
        source="desconhecido",
        first_contact_at=now,
        last_contact_at=now,
    )
    return await repo.add(contact)


async def get_or_create_conversation(
    session: AsyncSession, *, contact_id: uuid.UUID, channel_id: uuid.UUID
) -> Conversation:
    repo = ConversationRepository(session)
    conversation = await repo.get_open_by_contact_and_channel(contact_id, channel_id)
    if conversation is not None:
        return conversation

    conversation = Conversation(
        contact_id=contact_id,
        channel_id=channel_id,
        status="active",
        state="novo",
    )
    return await repo.add(conversation)
