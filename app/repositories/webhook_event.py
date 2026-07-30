"""Repositório de eventos crus de webhook — `docs/03-modelo-de-dados.md` §2."""

from app.models import WebhookEvent
from app.repositories.base import BaseRepository


class WebhookEventRepository(BaseRepository[WebhookEvent]):
    model = WebhookEvent
