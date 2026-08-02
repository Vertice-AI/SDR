"""Máquina de estados do agente (`docs/04-motor-de-conversa.md` §3,
roadmap 3.3) — sem rede, sem LLM."""

import pytest

from app.agent.state import (
    AGENDAR_REUNIAO,
    CANCELAR_REUNIAO,
    CONSULTAR_HORARIOS_DISPONIVEIS,
    DESQUALIFICAR,
    ENCERRAR_CONVERSA,
    ESCALAR_PARA_HUMANO,
    REAGENDAR_REUNIAO,
    REGISTRAR_DADOS_LEAD,
    REGISTRAR_QUALIFICACAO,
    ConversationState,
    TurnSignals,
    check_tool_allowed,
    decide_state,
    tools_for_state,
)
from app.core.errors import ToolNotAllowedError


class TestToolsForState:
    def test_novo_nao_libera_nenhuma_ferramenta(self) -> None:
        assert tools_for_state(ConversationState.NOVO) == frozenset()

    def test_abertura_libera_buscar_registrar_e_escalar(self) -> None:
        ferramentas = tools_for_state(ConversationState.ABERTURA)
        assert ferramentas == {"buscar_conhecimento", REGISTRAR_DADOS_LEAD, ESCALAR_PARA_HUMANO}

    def test_qualificando_acrescenta_qualificacao_e_desqualificar(self) -> None:
        ferramentas = tools_for_state(ConversationState.QUALIFICANDO)
        assert REGISTRAR_QUALIFICACAO in ferramentas
        assert DESQUALIFICAR in ferramentas
        assert REGISTRAR_DADOS_LEAD in ferramentas

    def test_agendando_acrescenta_horarios_e_agendar(self) -> None:
        ferramentas = tools_for_state(ConversationState.AGENDANDO)
        assert CONSULTAR_HORARIOS_DISPONIVEIS in ferramentas
        assert AGENDAR_REUNIAO in ferramentas
        assert REGISTRAR_QUALIFICACAO in ferramentas

    def test_agendado_acrescenta_reagendar_e_cancelar(self) -> None:
        ferramentas = tools_for_state(ConversationState.AGENDADO)
        assert REAGENDAR_REUNIAO in ferramentas
        assert CANCELAR_REUNIAO in ferramentas

    @pytest.mark.parametrize(
        "estado",
        [
            ConversationState.AGUARDANDO_LEAD,
            ConversationState.HANDOFF_HUMANO,
            ConversationState.DESQUALIFICADO,
            ConversationState.ENCERRADO,
            ConversationState.OPT_OUT,
        ],
    )
    def test_estados_terminais_nao_liberam_ferramenta(self, estado: ConversationState) -> None:
        assert tools_for_state(estado) == frozenset()

    def test_aceita_string_crua(self) -> None:
        assert tools_for_state("agendado") == tools_for_state(ConversationState.AGENDADO)


class TestCheckToolAllowed:
    def test_ferramenta_permitida_nao_levanta(self) -> None:
        check_tool_allowed("buscar_conhecimento", ConversationState.ABERTURA)

    def test_ferramenta_fora_do_estado_levanta(self) -> None:
        with pytest.raises(ToolNotAllowedError) as exc_info:
            check_tool_allowed(AGENDAR_REUNIAO, ConversationState.ABERTURA)
        assert exc_info.value.code == "tool_not_allowed"
        assert exc_info.value.details["tool_name"] == AGENDAR_REUNIAO

    def test_ferramenta_em_estado_silenciado_levanta(self) -> None:
        with pytest.raises(ToolNotAllowedError):
            check_tool_allowed(ESCALAR_PARA_HUMANO, ConversationState.HANDOFF_HUMANO)


class TestDecideState:
    def test_opt_out_vence_qualquer_coisa(self) -> None:
        sinais = TurnSignals(opt_out_detected=True, tools_called=frozenset({AGENDAR_REUNIAO}))
        assert decide_state(ConversationState.AGENDANDO, sinais) is ConversationState.OPT_OUT

    def test_escalar_leva_a_handoff(self) -> None:
        sinais = TurnSignals(tools_called=frozenset({ESCALAR_PARA_HUMANO}))
        assert (
            decide_state(ConversationState.QUALIFICANDO, sinais) is ConversationState.HANDOFF_HUMANO
        )

    def test_desqualificar_leva_a_desqualificado(self) -> None:
        sinais = TurnSignals(tools_called=frozenset({DESQUALIFICAR}))
        assert (
            decide_state(ConversationState.QUALIFICANDO, sinais) is ConversationState.DESQUALIFICADO
        )

    def test_encerrar_conversa_leva_a_encerrado(self) -> None:
        sinais = TurnSignals(tools_called=frozenset({ENCERRAR_CONVERSA}))
        assert (
            decide_state(ConversationState.RESPONDENDO_DUVIDAS, sinais)
            is ConversationState.ENCERRADO
        )

    def test_agendar_reuniao_leva_a_agendado(self) -> None:
        sinais = TurnSignals(tools_called=frozenset({AGENDAR_REUNIAO}))
        assert decide_state(ConversationState.AGENDANDO, sinais) is ConversationState.AGENDADO

    def test_cancelar_reuniao_volta_a_agendando(self) -> None:
        sinais = TurnSignals(tools_called=frozenset({CANCELAR_REUNIAO}))
        assert decide_state(ConversationState.AGENDADO, sinais) is ConversationState.AGENDANDO

    def test_reagendar_reuniao_permanece_agendado(self) -> None:
        sinais = TurnSignals(tools_called=frozenset({REAGENDAR_REUNIAO}))
        assert decide_state(ConversationState.AGENDADO, sinais) is ConversationState.AGENDADO

    def test_pergunta_aberta_durante_qualificacao_desvia_para_duvidas(self) -> None:
        sinais = TurnSignals(has_open_question=True)
        assert (
            decide_state(ConversationState.QUALIFICANDO, sinais)
            is ConversationState.RESPONDENDO_DUVIDAS
        )

    def test_pergunta_aberta_durante_agendando_desvia_para_duvidas(self) -> None:
        sinais = TurnSignals(has_open_question=True)
        assert (
            decide_state(ConversationState.AGENDANDO, sinais)
            is ConversationState.RESPONDENDO_DUVIDAS
        )

    def test_pergunta_aberta_em_agendado_nao_desvia(self) -> None:
        """`agendado.j2` responde dúvidas pontuais sem trocar de estado."""
        sinais = TurnSignals(has_open_question=True)
        assert decide_state(ConversationState.AGENDADO, sinais) is ConversationState.AGENDADO

    def test_score_acima_do_limiar_com_campos_completos_avanca_para_agendando(
        self,
    ) -> None:
        sinais = TurnSignals(
            qualification_score=70, required_fields_filled=True, scheduling_threshold=45
        )
        assert decide_state(ConversationState.QUALIFICANDO, sinais) is ConversationState.AGENDANDO

    def test_score_acima_do_limiar_sem_campos_obrigatorios_nao_avanca(self) -> None:
        sinais = TurnSignals(
            qualification_score=70, required_fields_filled=False, scheduling_threshold=45
        )
        assert (
            decide_state(ConversationState.QUALIFICANDO, sinais) is ConversationState.QUALIFICANDO
        )

    def test_progressao_nao_reabre_conversa_ja_agendada(self) -> None:
        sinais = TurnSignals(qualification_score=90, required_fields_filled=True)
        assert decide_state(ConversationState.AGENDADO, sinais) is ConversationState.AGENDADO

    def test_respondendo_duvidas_retorna_direto_a_agendando_se_ja_qualificado(
        self,
    ) -> None:
        sinais = TurnSignals(qualification_score=80, required_fields_filled=True)
        assert (
            decide_state(ConversationState.RESPONDENDO_DUVIDAS, sinais)
            is ConversationState.AGENDANDO
        )

    def test_respondendo_duvidas_retorna_a_qualificando_por_padrao(self) -> None:
        sinais = TurnSignals()
        assert (
            decide_state(ConversationState.RESPONDENDO_DUVIDAS, sinais)
            is ConversationState.QUALIFICANDO
        )

    def test_abertura_avanca_para_qualificando_ao_registrar_qualificacao(self) -> None:
        sinais = TurnSignals(tools_called=frozenset({REGISTRAR_QUALIFICACAO}))
        assert decide_state(ConversationState.ABERTURA, sinais) is ConversationState.QUALIFICANDO

    def test_abertura_sem_progresso_permanece_abertura(self) -> None:
        sinais = TurnSignals(tools_called=frozenset({REGISTRAR_DADOS_LEAD}))
        assert decide_state(ConversationState.ABERTURA, sinais) is ConversationState.ABERTURA

    def test_estado_sem_sinal_relevante_permanece_estavel(self) -> None:
        sinais = TurnSignals()
        assert (
            decide_state(ConversationState.QUALIFICANDO, sinais) is ConversationState.QUALIFICANDO
        )

    def test_aceita_string_crua_para_estado_atual(self) -> None:
        sinais = TurnSignals(tools_called=frozenset({ESCALAR_PARA_HUMANO}))
        assert decide_state("qualificando", sinais) is ConversationState.HANDOFF_HUMANO
