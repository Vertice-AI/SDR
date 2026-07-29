# 07 — Integração com Agenda

## 1. Interface

`app/calendar/base.py`:

```python
class CalendarProvider(Protocol):
    async def get_busy(self, seller: Seller, start: datetime, end: datetime) -> list[Interval]: ...
    async def create_event(self, seller: Seller, ev: EventDraft) -> CreatedEvent: ...
    async def update_event(self, seller: Seller, event_id: str, ev: EventDraft) -> CreatedEvent: ...
    async def cancel_event(self, seller: Seller, event_id: str) -> None: ...
```

Implementação v1: `GoogleCalendarProvider`. Fallback: `LinkOnlyProvider`, que só devolve o link externo do tenant (Cal.com/Calendly) quando o cliente não quer dar acesso ao calendário.

## 2. OAuth Google

- Escopo: `https://www.googleapis.com/auth/calendar.events` + `calendar.readonly`. Não pedir escopo amplo.
- Fluxo no painel: vendedor clica em "Conectar Google Agenda", autoriza, guardamos o **refresh token** criptografado em `sellers.calendar_credentials_encrypted`.
- `access_token` em cache no Redis com TTL, renovado por refresh.
- Revogação (`invalid_grant`): marcar `sellers.calendar_provider = 'none'`, alertar o gestor e cair para o fallback de link. **Nunca** deixar o agente prometer horário sem conseguir consultar.
- App em produção do Google exige verificação (tela de consentimento). Para poucos usuários internos por cliente, o modo "External / Testing" tem limite; planejar a verificação com antecedência.

## 3. Regras de disponibilidade

`sellers.availability_rules`:

```json
{
  "timezone": "America/Sao_Paulo",
  "weekly": {
    "mon": [["09:00","12:00"],["14:00","18:00"]],
    "tue": [["09:00","12:00"],["14:00","18:00"]],
    "wed": [["09:00","12:00"],["14:00","18:00"]],
    "thu": [["09:00","12:00"],["14:00","18:00"]],
    "fri": [["09:00","12:00"],["14:00","17:00"]],
    "sat": [], "sun": []
  },
  "meeting_duration_minutes": 30,
  "buffer_before_minutes": 0,
  "buffer_after_minutes": 15,
  "min_notice_minutes": 120,
  "max_days_ahead": 14,
  "max_meetings_per_day": 6,
  "slot_granularity_minutes": 30,
  "blackout_dates": ["2026-12-24", "2026-12-25"]
}
```

Algoritmo de `consultar_horarios_disponiveis`:

1. Janela = `[agora + min_notice, agora + max_days_ahead]`.
2. Gerar slots candidatos pela grade semanal, na granularidade definida.
3. Remover blackout dates e feriados nacionais (biblioteca `holidays`, ajustável por tenant).
4. Buscar `freebusy` do Google no período e remover conflitos, aplicando os buffers.
5. Remover dias que já atingiram `max_meetings_per_day` (contar em `appointments`).
6. Remover slots já reservados por outra conversa em andamento (ver §4).
7. Aplicar a preferência do lead se houver ("de manhã" → antes de 12 h; "semana que vem" → deslocar a janela).
8. Retornar até 3 slots, distribuídos: preferir um hoje/amanhã, um em 2–3 dias, um mais adiante. Oferecer três horários no mesmo dia reduz a chance de encaixe.

Cachear o `freebusy` por 60 s por vendedor para não estourar a cota da API durante uma conversa.

## 4. Reserva temporária (evita conflito)

Entre "ofereci o horário" e "o lead confirmou" passam minutos. Dois leads podem estar sendo atendidos ao mesmo tempo.

- Ao oferecer, criar chave Redis `slotlock:{seller_id}:{iso_start}` com TTL de 10 minutos e o `conversation_id` como valor.
- Ao gerar slots para outra conversa, ignorar os que estiverem travados.
- Ao confirmar, revalidar disponibilidade real antes de criar o evento (o vendedor pode ter marcado algo direto no Google nesse meio-tempo). Se o slot caiu, retornar erro tratável — o agente pede desculpa e reoferece na mesma mensagem.

## 5. Criação do evento

```python
EventDraft(
  summary=f"{tenant.name} — Reunião com {contact.name}",
  description=(
     "Reunião agendada pelo agente de pré-vendas.\n\n"
     f"Origem: {contact.source}\n"
     f"Empresa: {contact.company}\n"
     f"Resumo: {conversation.summary}\n\n"
     "Respostas da qualificação:\n" + formatted_answers +
     f"\nConversa: {panel_url}"
  ),
  start=slot.start, end=slot.end, timezone=seller.timezone,
  attendees=[contact.email, seller.email],
  conference=True,        # conferenceDataVersion=1, createRequest com Meet
  reminders=[{"method":"popup","minutes":30}],
)
```

O vendedor precisa abrir o evento e já entender com quem vai falar. Isso é metade do valor percebido do produto.

`sendUpdates="all"` para o Google notificar por e-mail também.

## 6. Distribuição entre vendedores

Configurável por tenant:

- `single` — sempre o mesmo vendedor.
- `round_robin` — rodízio ponderado por `round_robin_weight`, pulando quem não tem slot.
- `by_rule` — regra em `tenant_configs` (por exemplo, faturamento acima de X vai para o vendedor sênior).

Registrar o vendedor escolhido em `conversations.assigned_seller_id` antes de oferecer horários — não trocar de vendedor no meio.

## 7. Confirmações e lembretes

| Momento | Ação |
|---|---|
| Imediato | Mensagem confirmando dia, hora e link |
| 24 h antes | Lembrete (template `lembrete_reuniao_24h` se fora da janela) |
| 1 h antes | Lembrete curto com o link |
| Após o horário | Marcar `completed`; o vendedor pode marcar `no_show` no painel |

Se o lead responder ao lembrete pedindo mudança, a conversa volta ao estado `agendado` com a ferramenta de reagendamento disponível.

## 8. Reagendar e cancelar

- Reagendar: cria novo `appointment` com `rescheduled_from_id`, atualiza o evento no Google, marca o anterior como `rescheduled`.
- Cancelar: cancela o evento, marca `cancelled` com motivo, e o agente pergunta se a pessoa quer remarcar depois (uma vez, sem insistir).
- Toda mudança notifica o vendedor.

## 9. Falhas

| Falha | Comportamento |
|---|---|
| Google fora do ar / timeout | Agente diz que vai confirmar o horário e escala; nunca inventa slot |
| Token revogado | Fallback para link, alerta ao gestor |
| Cota excedida | Backoff, cache mais agressivo, alerta |
| Slot tomado na confirmação | Reoferecer imediatamente, com desculpa curta |
| Lead sem e-mail | Pedir o e-mail antes de agendar; se recusar, criar sem convidado e enviar o link pelo WhatsApp |
