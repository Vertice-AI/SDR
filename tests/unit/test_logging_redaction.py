"""Teste crítico de LGPD: nenhum log pode conter telefone completo ou
conteúdo de mensagem (`docs/09-seguranca-lgpd-guardrails.md` §6).
"""

import io
import json

import structlog

from app.core.logging import _redact_processor, hash_phone, mask_email, mask_phone

PEPPER = "test-pepper"
TELEFONE_COMPLETO = "5511987654321"
CONTEUDO_MENSAGEM = "Meu CPF é 123.456.789-00, me liga no 5511987654321"


def _capturar_log(**event_kwargs: object) -> dict[str, object]:
    buffer = io.StringIO()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            _redact_processor(PEPPER),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=buffer),
        cache_logger_on_first_use=False,
    )

    logger = structlog.get_logger()
    logger.info("evento_de_teste", **event_kwargs)

    linha = buffer.getvalue().strip().splitlines()[-1]
    return json.loads(linha)  # type: ignore[no-any-return]


def test_telefone_completo_nunca_aparece_no_log() -> None:
    log = _capturar_log(telefone=TELEFONE_COMPLETO)
    serialized = json.dumps(log)

    assert TELEFONE_COMPLETO not in serialized
    assert log["telefone"] == mask_phone(TELEFONE_COMPLETO, pepper=PEPPER)
    assert log["telefone_hash"] == hash_phone(TELEFONE_COMPLETO, pepper=PEPPER)


def test_conteudo_de_mensagem_nunca_aparece_no_log() -> None:
    log = _capturar_log(mensagem=CONTEUDO_MENSAGEM)
    serialized = json.dumps(log)

    assert CONTEUDO_MENSAGEM not in serialized
    assert log["mensagem"] == "***redacted***"


def test_email_e_mascarado() -> None:
    log = _capturar_log(email="joao.silva@empresa.com")

    assert log["email"] == mask_email("joao.silva@empresa.com")
    assert "joao.silva@empresa.com" not in json.dumps(log)


def test_token_nunca_aparece_no_log() -> None:
    log = _capturar_log(access_token="segredo-super-secreto")

    assert "segredo-super-secreto" not in json.dumps(log)
    assert log["access_token"] == "***redacted***"
