"""Renderização dos prompts do agente com Jinja2 — templates em
`app/agent/prompts/*.j2` (`docs/05-prompts.md`, roadmap 3.2).

`StrictUndefined`: uma variável de contexto esquecida no chamador deve
estourar na hora, nunca virar um prompt de sistema com um buraco silencioso
que só aparece quando o lead recebe uma resposta estranha.
"""

from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

_TEMPLATES_DIR = Path(__file__).parent

_ENV = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    undefined=StrictUndefined,
    autoescape=False,  # texto puro para o LLM, não HTML
    # Sem trim_blocks/lstrip_blocks: os templates de `docs/05` já controlam
    # espaço em branco manualmente com `{%- ... %}` nos pontos exatos onde
    # importa (ex.: linha "JÁ COLETADO"). Ligar os dois globalmente quebra
    # essa marcação — engole a quebra de linha entre iterações do loop.
)

# Estados em que o agente é silenciado (`docs/04` §3, `docs/05` §2) — não
# deveríamos nunca chegar a renderizar um prompt de sistema aqui; se
# chegarmos, é bug em quem decide o estado (tarefa 3.3), não algo a
# degradar silenciosamente.
_ESTADOS_SEM_RESPOSTA = frozenset({"handoff_humano", "opt_out"})


@dataclass(frozen=True, slots=True)
class QualificationFieldPrompt:
    """Um campo de `tenant_configs.qualification_fields` (`docs/03` §7),
    já resolvido para o formato que os templates precisam."""

    key: str
    label: str
    question_hint: str
    required: bool = False
    captured: str | None = None
    type: str = "text"
    options: list[str] | None = None


@dataclass(frozen=True, slots=True)
class ContactPrompt:
    name: str | None = None
    source: str | None = None


@dataclass(frozen=True, slots=True)
class SystemPromptContext:
    agent_name: str
    company_name: str
    company_description: str
    offer_description: str
    icp_description: str
    tone: str
    qualification_fields: list[QualificationFieldPrompt]
    now_local: str
    timezone: str
    within_business_hours: bool
    state: str
    contact: ContactPrompt
    forbidden_topics: list[str] = field(default_factory=list)
    conversation_summary: str | None = None
    custom_instructions: str | None = None


def render_system_prompt(ctx: SystemPromptContext) -> str:
    if ctx.state in _ESTADOS_SEM_RESPOSTA:
        raise ValueError(
            f"estado '{ctx.state}' silencia o agente (`docs/05` §2) — "
            "não deveria renderizar prompt de sistema aqui"
        )
    template = _ENV.get_template("system_sdr.j2")
    return template.render(
        agent_name=ctx.agent_name,
        company_name=ctx.company_name,
        company_description=ctx.company_description,
        offer_description=ctx.offer_description,
        icp_description=ctx.icp_description,
        tone=ctx.tone,
        forbidden_topics=ctx.forbidden_topics,
        qualification_fields=ctx.qualification_fields,
        now_local=ctx.now_local,
        timezone=ctx.timezone,
        within_business_hours=ctx.within_business_hours,
        state=ctx.state,
        contact=ctx.contact,
        conversation_summary=ctx.conversation_summary,
        custom_instructions=ctx.custom_instructions,
    ).strip()


def render_summarize(*, previous_summary: str, new_messages: str) -> str:
    template = _ENV.get_template("summarize.j2")
    return template.render(previous_summary=previous_summary, new_messages=new_messages).strip()


def render_extract_fields(
    *, qualification_fields: list[QualificationFieldPrompt], messages: str
) -> str:
    template = _ENV.get_template("extract_fields.j2")
    return template.render(qualification_fields=qualification_fields, messages=messages).strip()


def render_classify_intent(*, message: str) -> str:
    template = _ENV.get_template("classify_intent.j2")
    return template.render(message=message).strip()
