"""Tradução de erro HTTP (httpx) para `ExternalServiceError` com o veredito
de retry certo — 5xx/429 vale tentar de novo, 4xx é definitivo
(`docs/06-integracao-whatsapp.md` §4 item 7). Compartilhado pelos dois
adapters para não divergir o critério."""

from typing import NoReturn

import httpx

from app.core.errors import ExternalServiceError


def raise_external_service_error(message: str, exc: httpx.HTTPError) -> NoReturn:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        retryable = status >= 500 or status == 429
    else:
        retryable = True  # erro de transporte/timeout — vale tentar de novo
    raise ExternalServiceError(message, retryable=retryable) from exc
