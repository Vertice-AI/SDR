"""Renderização dos templates Jinja2 do agente (`docs/05-prompts.md`,
roadmap 3.2) — sem rede, sem LLM."""

import pytest

from app.agent.prompts.renderer import (
    ContactPrompt,
    QualificationFieldPrompt,
    SystemPromptContext,
    render_classify_intent,
    render_extract_fields,
    render_summarize,
    render_system_prompt,
)


def _ctx(**overrides: object) -> SystemPromptContext:
    defaults: dict[str, object] = {
        "agent_name": "Ana",
        "company_name": "Acme",
        "company_description": "Somos a Acme.",
        "offer_description": "Vendemos software.",
        "icp_description": "Empresas de médio porte.",
        "tone": "consultivo",
        "forbidden_topics": [],
        "qualification_fields": [],
        "now_local": "30/07/2026 14:00",
        "timezone": "America/Sao_Paulo",
        "within_business_hours": True,
        "state": "qualificando",
        "contact": ContactPrompt(),
        "conversation_summary": None,
        "custom_instructions": None,
    }
    defaults.update(overrides)
    return SystemPromptContext(**defaults)  # type: ignore[arg-type]


def test_render_system_prompt_inclui_dados_do_tenant() -> None:
    resultado = render_system_prompt(_ctx())

    assert "Você é Ana, do time de pré-vendas da Acme." in resultado
    assert "Somos a Acme." in resultado
    assert "Vendemos software." in resultado
    assert "Empresas de médio porte." in resultado
    assert "tom consultivo" in resultado


def test_render_system_prompt_lista_temas_proibidos() -> None:
    resultado = render_system_prompt(_ctx(forbidden_topics=["concorrente X", "política"]))

    assert "- Não fale sobre: concorrente X" in resultado
    assert "- Não fale sobre: política" in resultado


def test_render_system_prompt_campo_obrigatorio_e_ja_coletado() -> None:
    campos = [
        QualificationFieldPrompt(
            key="dor", label="Principal dor", question_hint="Descobrir o problema", required=True
        ),
        QualificationFieldPrompt(
            key="faturamento",
            label="Faturamento mensal",
            question_hint="Faixa de faturamento",
            required=True,
            captured="50k_200k",
        ),
    ]
    resultado = render_system_prompt(_ctx(qualification_fields=campos))

    assert "Principal dor (obrigatório): Descobrir o problema" in resultado
    assert "Faturamento mensal (obrigatório): Faixa de faturamento — JÁ COLETADO: 50k_200k" in (
        resultado.replace("\n", "")
    )


def test_render_system_prompt_campo_opcional_sem_marca_obrigatorio() -> None:
    campos = [
        QualificationFieldPrompt(
            key="urgencia", label="Urgência", question_hint="Quando precisa", required=False
        )
    ]
    resultado = render_system_prompt(_ctx(qualification_fields=campos))

    assert "Urgência: Quando precisa" in resultado
    assert "Urgência (obrigatório)" not in resultado


def test_render_system_prompt_contato_conhecido() -> None:
    resultado = render_system_prompt(
        _ctx(contact=ContactPrompt(name="João", source="anuncio_meta"))
    )

    assert "Nome do contato: João" in resultado
    assert "Origem do lead: anuncio_meta" in resultado


def test_render_system_prompt_contato_desconhecido_omite_linhas() -> None:
    resultado = render_system_prompt(_ctx(contact=ContactPrompt(name=None, source=None)))

    assert "Nome do contato" not in resultado
    assert "Origem do lead" not in resultado


def test_render_system_prompt_fora_do_horario_comercial() -> None:
    resultado = render_system_prompt(_ctx(within_business_hours=False))

    assert "Estamos fora do horário comercial." in resultado


def test_render_system_prompt_dentro_do_horario_nao_menciona() -> None:
    resultado = render_system_prompt(_ctx(within_business_hours=True))

    assert "Estamos fora do horário comercial." not in resultado


def test_render_system_prompt_resumo_da_conversa_quando_existe() -> None:
    resultado = render_system_prompt(_ctx(conversation_summary="Lead já disse que quer agendar."))

    assert "# Resumo do que já foi conversado" in resultado
    assert "Lead já disse que quer agendar." in resultado


def test_render_system_prompt_sem_resumo_omite_secao() -> None:
    resultado = render_system_prompt(_ctx(conversation_summary=None))

    assert "# Resumo do que já foi conversado" not in resultado


def test_render_system_prompt_orientacoes_especificas_quando_existem() -> None:
    resultado = render_system_prompt(_ctx(custom_instructions="Sempre mencionar o webinar."))

    assert "# Orientações específicas deste cliente" in resultado
    assert "Sempre mencionar o webinar." in resultado


def test_render_system_prompt_sem_orientacoes_omite_secao() -> None:
    resultado = render_system_prompt(_ctx(custom_instructions=None))

    assert "# Orientações específicas deste cliente" not in resultado


@pytest.mark.parametrize(
    ("estado", "trecho_esperado"),
    [
        ("abertura", "Este é o primeiro contato"),
        ("qualificando", "Continue entendendo a situação"),
        ("respondendo_duvidas", "Use buscar_conhecimento antes de responder"),
        ("agendando", "consultar_horarios_disponiveis"),
        ("agendado", "Não reabra a qualificação"),
        ("desqualificado", "Encerre com gentileza e respeito"),
    ],
)
def test_render_system_prompt_inclui_bloco_do_estado(estado: str, trecho_esperado: str) -> None:
    resultado = render_system_prompt(_ctx(state=estado))

    assert f"Estágio da conversa: {estado}" in resultado
    assert trecho_esperado in resultado


@pytest.mark.parametrize("estado", ["handoff_humano", "opt_out"])
def test_render_system_prompt_recusa_estado_silenciado(estado: str) -> None:
    with pytest.raises(ValueError, match=estado):
        render_system_prompt(_ctx(state=estado))


def test_render_summarize() -> None:
    resultado = render_summarize(previous_summary="resumo antigo", new_messages="lead disse oi")

    assert "resumo antigo" in resultado
    assert "lead disse oi" in resultado
    assert "até 200 palavras" in resultado


def test_render_extract_fields_lista_campos_com_opcoes() -> None:
    campos = [
        QualificationFieldPrompt(
            key="faturamento_mensal",
            label="Faturamento mensal",
            question_hint="",
            type="enum",
            options=["ate_50k", "50k_200k"],
        )
    ]
    resultado = render_extract_fields(
        qualification_fields=campos, messages="ganhamos 80 mil por mês"
    )

    assert "faturamento_mensal (enum: ate_50k, 50k_200k)" in resultado
    assert "ganhamos 80 mil por mês" in resultado


def test_render_classify_intent() -> None:
    resultado = render_classify_intent(message="quero falar com um atendente")

    assert "quero falar com um atendente" in resultado
    assert "pedido_humano" in resultado
