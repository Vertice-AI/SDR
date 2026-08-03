"""Score e classificação de qualificação (`app/services/qualification.py`,
`docs/08-qualificacao-e-handoff.md` §3, roadmap 3.5/3.6) — puro, sem banco."""

from app.services.qualification import (
    DEFAULT_CLASSIFICATION_BANDS,
    calculate_score,
    classify_score,
    required_fields_filled,
)

_CAMPOS = [
    {"key": "dor_principal", "required": True, "weight": 30, "scoring": {"has_value": 30}},
    {
        "key": "faturamento_mensal",
        "required": True,
        "weight": 30,
        "scoring": {"ate_50k": 0, "50k_200k": 15, "200k_1m": 30, "acima_1m": 30},
    },
    {
        "key": "decisor",
        "required": True,
        "weight": 20,
        "scoring": {"sim": 20, "influencia": 12, "nao": 3},
    },
    {
        "key": "urgencia",
        "required": False,
        "weight": 20,
        "scoring": {"imediata": 20, "3_meses": 12, "sem_prazo": 4},
    },
]


def _resposta(valor: str) -> dict[str, object]:
    return {"valor": valor, "confianca": 1.0}


class TestCalculateScore:
    def test_soma_pesos_dos_campos_respondidos(self) -> None:
        answers = {
            "dor_principal": _resposta("preciso de mais leads"),
            "faturamento_mensal": _resposta("200k_1m"),
            "decisor": _resposta("sim"),
        }
        assert calculate_score(answers, _CAMPOS) == 30 + 30 + 20

    def test_campo_nao_respondido_nao_pontua(self) -> None:
        answers = {"dor_principal": _resposta("x")}
        assert calculate_score(answers, _CAMPOS) == 30

    def test_sem_respostas_score_zero(self) -> None:
        assert calculate_score({}, _CAMPOS) == 0

    def test_valor_fora_das_opcoes_sem_has_value_nao_pontua(self) -> None:
        answers = {"decisor": _resposta("talvez")}
        assert calculate_score(answers, _CAMPOS) == 0

    def test_answers_aceita_valor_cru_sem_dict_de_confianca(self) -> None:
        answers = {"dor_principal": "preciso de mais leads"}
        assert calculate_score(answers, _CAMPOS) == 30


class TestClassifyScore:
    def test_score_hot(self) -> None:
        assert classify_score(80) == "hot"

    def test_score_warm(self) -> None:
        assert classify_score(50) == "warm"

    def test_score_cold(self) -> None:
        assert classify_score(25) == "cold"

    def test_score_abaixo_do_piso_e_disqualified(self) -> None:
        assert classify_score(10) == "disqualified"

    def test_limiares_sao_inclusivos(self) -> None:
        assert classify_score(DEFAULT_CLASSIFICATION_BANDS["hot"]) == "hot"
        assert classify_score(DEFAULT_CLASSIFICATION_BANDS["warm"]) == "warm"
        assert classify_score(DEFAULT_CLASSIFICATION_BANDS["cold"]) == "cold"

    def test_bandas_customizadas_por_tenant(self) -> None:
        bandas = {"hot": 90, "warm": 60, "cold": 30}
        assert classify_score(80, bandas) == "warm"


class TestRequiredFieldsFilled:
    def test_falso_quando_falta_campo_obrigatorio(self) -> None:
        answers = {"dor_principal": _resposta("x")}
        assert required_fields_filled(answers, _CAMPOS) is False

    def test_verdadeiro_quando_todos_obrigatorios_preenchidos(self) -> None:
        answers = {
            "dor_principal": _resposta("x"),
            "faturamento_mensal": _resposta("200k_1m"),
            "decisor": _resposta("sim"),
        }
        assert required_fields_filled(answers, _CAMPOS) is True

    def test_campo_opcional_ausente_nao_impede(self) -> None:
        answers = {
            "dor_principal": _resposta("x"),
            "faturamento_mensal": _resposta("200k_1m"),
            "decisor": _resposta("sim"),
        }
        assert "urgencia" not in answers
        assert required_fields_filled(answers, _CAMPOS) is True
