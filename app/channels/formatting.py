"""Formatação e split de resposta para o WhatsApp — `docs/04-motor-de-conversa.md` §6.

Nunca mandar parágrafo de 10 linhas (`CLAUDE.md` §4.5): quebra em até 3
mensagens curtas, sem markdown que o WhatsApp não renderiza (`**negrito**`
não funciona lá — só `*negrito*` do próprio app).
"""

import re

_MAX_PARTS = 3
_MAX_CHARS_PER_PART = 350
_TYPING_DELAY_FLOOR_MS = 250
_TYPING_DELAY_PER_CHAR_MS = 25
_TYPING_DELAY_CEIL_MS = 6000


def strip_unsupported_markdown(text: str) -> str:
    texto = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    texto = re.sub(r"^#{1,6}\s*", "", texto, flags=re.MULTILINE)
    texto = re.sub(r"^[-*]\s+", "• ", texto, flags=re.MULTILINE)
    return texto


def _split_by_sentence(text: str, max_chars: int) -> list[str]:
    frases = re.split(r"(?<=[.!?])\s+", text)
    partes: list[str] = []
    atual = ""
    for frase in frases:
        candidato = f"{atual} {frase}".strip() if atual else frase
        if len(candidato) <= max_chars:
            atual = candidato
        else:
            if atual:
                partes.append(atual)
            atual = frase
    if atual:
        partes.append(atual)
    return partes or [text]


def split_message(
    text: str, *, max_parts: int = _MAX_PARTS, max_chars: int = _MAX_CHARS_PER_PART
) -> list[str]:
    """Quebra em até `max_parts` mensagens, cortando em parágrafo ou frase.
    O bloco excedente (se sobrar mais que `max_parts` pedaços) é anexado ao
    último — nunca descartamos texto."""
    texto = strip_unsupported_markdown(text).strip()
    if not texto:
        return []

    paragrafos = [p.strip() for p in texto.split("\n\n") if p.strip()]
    partes: list[str] = []
    atual = ""
    for paragrafo in paragrafos:
        candidato = f"{atual}\n\n{paragrafo}" if atual else paragrafo
        if len(candidato) <= max_chars:
            atual = candidato
        else:
            if atual:
                partes.append(atual)
            atual = paragrafo
    if atual:
        partes.append(atual)

    partes_finais: list[str] = []
    for parte in partes:
        if len(parte) <= max_chars:
            partes_finais.append(parte)
        else:
            partes_finais.extend(_split_by_sentence(parte, max_chars))

    if len(partes_finais) > max_parts:
        cabeca, cauda = partes_finais[: max_parts - 1], partes_finais[max_parts - 1 :]
        partes_finais = [*cabeca, "\n\n".join(cauda)]

    return partes_finais


def typing_delay_ms(text: str) -> int:
    """`250ms + 25ms/caractere`, com teto de 6 s (`CLAUDE.md` §4.5)."""
    return min(
        _TYPING_DELAY_CEIL_MS, _TYPING_DELAY_FLOOR_MS + _TYPING_DELAY_PER_CHAR_MS * len(text)
    )
