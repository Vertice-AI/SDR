"""Split e formatação de resposta — `docs/04-motor-de-conversa.md` §6."""

from app.channels.formatting import split_message, strip_unsupported_markdown, typing_delay_ms


def test_strip_bold_markdown_vira_negrito_whatsapp() -> None:
    assert strip_unsupported_markdown("isso é **importante**") == "isso é *importante*"


def test_strip_headers() -> None:
    assert strip_unsupported_markdown("## Título\ntexto") == "Título\ntexto"


def test_strip_lista_vira_bullet() -> None:
    resultado = strip_unsupported_markdown("- item um\n- item dois")
    assert resultado == "• item um\n• item dois"


def test_split_message_texto_curto_fica_em_uma_parte() -> None:
    assert split_message("oi, tudo bem?") == ["oi, tudo bem?"]


def test_split_message_string_vazia() -> None:
    assert split_message("") == []
    assert split_message("   ") == []


def test_split_message_por_paragrafo() -> None:
    texto = "Primeiro parágrafo curto.\n\nSegundo parágrafo também curto."
    partes = split_message(texto, max_chars=40)
    assert len(partes) == 2
    assert partes[0] == "Primeiro parágrafo curto."
    assert partes[1] == "Segundo parágrafo também curto."


def test_split_message_nunca_passa_de_max_parts() -> None:
    texto = "\n\n".join(f"Parágrafo número {i} com algum texto." for i in range(6))
    partes = split_message(texto, max_parts=3, max_chars=40)
    assert len(partes) <= 3


def test_split_message_corta_paragrafo_longo_por_frase() -> None:
    # "salvo bloco indivisível" (docs/04 §6): uma frase sozinha maior que
    # max_chars vira sua própria parte, sem cortar no meio da frase.
    texto = "Primeira frase aqui. Segunda frase também. Terceira frase mais longa ainda."
    partes = split_message(texto, max_chars=30)
    assert partes == [
        "Primeira frase aqui.",
        "Segunda frase também.",
        "Terceira frase mais longa ainda.",
    ]
    assert len(partes) > 1


def test_typing_delay_respeita_piso_e_teto() -> None:
    assert typing_delay_ms("") == 250
    assert typing_delay_ms("a" * 10) == 250 + 25 * 10
    assert typing_delay_ms("a" * 1000) == 6000
