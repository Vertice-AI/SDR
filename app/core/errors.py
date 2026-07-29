"""Hierarquia de erros de domínio.

Nunca usar `except Exception: pass`. Erros que representam falhas de regra de
negócio herdam de `DomainError` e carregam um `code` estável para logging e
resposta HTTP consistente — o handler global em `app.main` traduz isso.
"""

from typing import Any


class DomainError(Exception):
    """Base de todo erro de domínio conhecido e esperado."""

    code: str = "domain_error"
    status_code: int = 400

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class TenantNotFoundError(DomainError):
    code = "tenant_not_found"
    status_code = 404


class TenantInactiveError(DomainError):
    code = "tenant_inactive"
    status_code = 403


class TenantContextMissingError(DomainError):
    """Uma query rodou sem `TenantContext` definido — bug de isolamento."""

    code = "tenant_context_missing"
    status_code = 500


class InvalidWebhookSignatureError(DomainError):
    code = "invalid_webhook_signature"
    status_code = 403


class ConversationLockedError(DomainError):
    code = "conversation_locked"
    status_code = 409


class InvalidStateTransitionError(DomainError):
    code = "invalid_state_transition"
    status_code = 409


class SlotUnavailableError(DomainError):
    code = "slot_unavailable"
    status_code = 409


class KnowledgeNotConfiguredError(DomainError):
    code = "knowledge_not_configured"
    status_code = 422


class EncryptionError(DomainError):
    code = "encryption_error"
    status_code = 500


class ExternalServiceError(DomainError):
    """Falha de integração externa (WhatsApp, Google, LLM, CRM) após retries."""

    code = "external_service_error"
    status_code = 502
