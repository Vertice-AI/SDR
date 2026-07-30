"""Tipos SQLAlchemy customizados compartilhados entre models."""

from typing import Any

from sqlalchemy import LargeBinary
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from app.config import get_settings
from app.core.crypto import decrypt, encrypt


class EncryptedString(TypeDecorator[str]):
    """Coluna `bytea` que cifra/decifra transparentemente com AES-GCM.

    Usada em toda coluna com sufixo `_encrypted` (`docs/03` — convenções).
    A cifragem roda na aplicação, nunca no banco — o Postgres só guarda bytes opacos.
    """

    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> bytes | None:
        if value is None:
            return None
        return encrypt(value, key_b64=get_settings().app_encryption_key)

    def process_result_value(self, value: Any, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return decrypt(value, key_b64=get_settings().app_encryption_key)
