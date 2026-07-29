"""Logging estruturado em JSON com redação de dados pessoais.

Regra de `docs/09-seguranca-lgpd-guardrails.md` §6: telefone completo e
conteúdo de mensagem NUNCA podem aparecer em log de aplicação. Esse módulo é
a última linha de defesa — mesmo que um chamador passe esses campos por
engano, o processor de redação os limpa antes da saída.
"""

import hashlib
import hmac
import logging
import re
from typing import Any

import structlog
from structlog.types import EventDict, Processor

# Chaves cujo valor NUNCA deve ser logado em texto puro — são substituídas
# por um placeholder, independentemente do que o chamador tentou registrar.
_CHAVES_PROIBIDAS = {
    "message",
    "message_content",
    "content",
    "text",
    "body",
    "texto",
    "mensagem",
    "conteudo",
}

# Chaves de telefone: mantemos só os 4 últimos dígitos + hash.
_CHAVES_TELEFONE = {"phone", "telefone", "phone_number", "from", "to", "wa_id"}

# Chaves de e-mail: mascaramos usuário, mantemos domínio.
_CHAVES_EMAIL = {"email", "e_mail"}

# Chaves de segredo: nunca aparecem, nem parcialmente.
_CHAVES_SEGREDO = {
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "authorization",
    "password",
    "senha",
    "secret",
    "app_secret_key",
    "app_encryption_key",
}

_EMAIL_RE = re.compile(r"^([^@]{1,3})[^@]*(@.+)$")


def mask_phone(phone: str, *, pepper: str) -> str:
    """Retorna `***1234` — os 4 últimos dígitos do telefone, sem mais nada."""
    digits = re.sub(r"\D", "", phone)
    last4 = digits[-4:] if len(digits) >= 4 else digits
    return f"***{last4}"


def hash_phone(phone: str, *, pepper: str) -> str:
    """Hash determinístico do telefone completo, para correlação sem exposição."""
    digits = re.sub(r"\D", "", phone)
    return hmac.new(pepper.encode(), digits.encode(), hashlib.sha256).hexdigest()[:16]


def mask_email(email: str) -> str:
    match = _EMAIL_RE.match(email)
    if not match:
        return "***"
    return f"{match.group(1)}***{match.group(2)}"


def _redact_processor(pepper: str) -> Processor:
    def processor(_logger: Any, _method_name: str, event_dict: EventDict) -> EventDict:
        for key in list(event_dict.keys()):
            lower_key = key.lower()
            value = event_dict[key]

            if not isinstance(value, str):
                continue

            if lower_key in _CHAVES_SEGREDO or lower_key in _CHAVES_PROIBIDAS:
                event_dict[key] = "***redacted***"
            elif lower_key in _CHAVES_TELEFONE:
                event_dict[key] = mask_phone(value, pepper=pepper)
                event_dict[f"{key}_hash"] = hash_phone(value, pepper=pepper)
            elif lower_key in _CHAVES_EMAIL:
                event_dict[key] = mask_email(value)

        return event_dict

    return processor


def configure_logging(*, log_level: str, phone_hash_pepper: str) -> None:
    """Configura structlog para saída JSON com redação. Chamar uma vez no startup."""
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level.upper(), logging.INFO),
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _redact_processor(phone_hash_pepper),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(**initial_values: Any) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(**initial_values)  # type: ignore[no-any-return]
