"""Score e classificação de qualificação — `docs/08-qualificacao-e-handoff.md`
§3, roadmap 3.5/3.6.

Puramente funcional: recebe `qualifications.answers` e o
`qualification_fields` do tenant (`docs/03` §7), sem tocar em banco. Quem
grava o resultado é `app/agent/tools/registrar_qualificacao.py`.
"""

from typing import Any

DEFAULT_CLASSIFICATION_BANDS: dict[str, int] = {"hot": 70, "warm": 45, "cold": 20}


def calculate_score(answers: dict[str, Any], qualification_fields: list[dict[str, Any]]) -> int:
    """Soma os pesos de `scoring` de cada campo respondido (`docs/08` §3).

    `answers[key]` é `{"valor": ..., "confianca": ...}` — o texto do valor é
    o que indexa `scoring`. Campos com resposta fora das opções configuradas
    caem no `has_value` do campo, se houver; senão não pontuam (dado
    inconsistente não deve derrubar o cálculo).
    """
    score = 0
    for field in qualification_fields:
        key = field.get("key")
        entry = answers.get(key) if key is not None else None
        if entry is None:
            continue
        valor = entry.get("valor") if isinstance(entry, dict) else entry
        scoring = field.get("scoring") or {}
        if valor in scoring:
            score += int(scoring[valor])
        elif "has_value" in scoring:
            score += int(scoring["has_value"])
    return score


def classify_score(score: int, classification_bands: dict[str, int] | None = None) -> str:
    """Faixa de classificação a partir do score (`docs/08` §3).

    Abaixo do piso de `cold` é `disqualified` só pelo score — a
    desqualificação por regra explícita é decisão do LLM via `desqualificar`,
    não deste cálculo.
    """
    bands = classification_bands or DEFAULT_CLASSIFICATION_BANDS
    hot = bands.get("hot", DEFAULT_CLASSIFICATION_BANDS["hot"])
    warm = bands.get("warm", DEFAULT_CLASSIFICATION_BANDS["warm"])
    cold = bands.get("cold", DEFAULT_CLASSIFICATION_BANDS["cold"])
    if score >= hot:
        return "hot"
    if score >= warm:
        return "warm"
    if score >= cold:
        return "cold"
    return "disqualified"


def required_fields_filled(
    answers: dict[str, Any], qualification_fields: list[dict[str, Any]]
) -> bool:
    """Todo campo `required` de `qualification_fields` já tem resposta."""
    return all(
        field.get("key") in answers for field in qualification_fields if field.get("required")
    )
