"""Criptografia de campos sensíveis (AES-256-GCM).

Segredos por tenant (token da Meta, refresh token do Google) nunca ficam em
texto puro na coluna (`CLAUDE.md` §4.1). Cada valor cifrado carrega seu
próprio nonce de 12 bytes prefixado ao ciphertext, então o mesmo texto claro
nunca produz o mesmo blob duas vezes. A chave vem de `APP_ENCRYPTION_KEY`
(32 bytes em base64) — uma chave só para a aplicação inteira; rotação de
chave é operação, não é modelada por tenant.
"""

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.errors import EncryptionError

_NONCE_SIZE = 12
_KEY_SIZE = 32


def _load_key(key_b64: str) -> bytes:
    try:
        key = base64.b64decode(key_b64, validate=True)
    except Exception as exc:
        raise EncryptionError("APP_ENCRYPTION_KEY inválida: não é base64 válido.") from exc
    if len(key) != _KEY_SIZE:
        raise EncryptionError(
            f"APP_ENCRYPTION_KEY inválida: esperado {_KEY_SIZE} bytes, "
            f"obtido {len(key)} após decodificar."
        )
    return key


def encrypt(plaintext: str, *, key_b64: str) -> bytes:
    """Cifra `plaintext` e retorna `nonce || ciphertext` pronto para uma coluna bytea."""
    aesgcm = AESGCM(_load_key(key_b64))
    nonce = os.urandom(_NONCE_SIZE)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return nonce + ciphertext


def decrypt(token: bytes, *, key_b64: str) -> str:
    """Decifra um blob produzido por `encrypt`. Levanta `EncryptionError` se a chave
    estiver errada ou o dado estiver corrompido/adulterado."""
    aesgcm = AESGCM(_load_key(key_b64))
    nonce, ciphertext = token[:_NONCE_SIZE], token[_NONCE_SIZE:]
    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    except InvalidTag as exc:
        raise EncryptionError(
            "Falha ao decifrar valor — chave incorreta ou dado corrompido."
        ) from exc
    return plaintext.decode("utf-8")
