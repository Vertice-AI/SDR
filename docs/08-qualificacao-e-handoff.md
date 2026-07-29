# 08 — Qualificação, Handoff e Follow-up

## 1. Princípio

Qualificação boa não parece qualificação. O lead deve sentir que teve uma conversa útil, não que preencheu um formulário por WhatsApp. Três regras:

1. **Uma pergunta por mensagem.**
2. **Reagir antes de perguntar** — comentar o que a pessoa disse, depois avançar.
3. **Dar antes de pedir** — a cada duas perguntas, entregar algo (uma informação útil, um diagnóstico rápido, um exemplo).

## 2. Framework padrão (adaptável por tenant)

Ordem de coleta sugerida, não rígida:

| Ordem | Campo | Por que nessa posição |
|---|---|---|
| 1 | Dor / necessidade | Abre a conversa e é o que o lead quer falar |
| 2 | Contexto (porte, segmento, situação atual) | Natural depois da dor |
| 3 | Urgência / prazo | Só faz sentido depois de entender a dor |
| 4 | Autoridade (decisor) | Perguntar cedo soa desconfiado |
| 5 | Orçamento / faixa de investimento | Por último, e de forma indireta |

Nunca perguntar orçamento direto ("qual seu orçamento?"). Perguntar por faixa, ou inferir do porte. Em muitos ICPs, faturamento ou número de funcionários é um proxy melhor e menos invasivo.

Campos coletados de forma indireta contam igual: se o lead disse "somos 40 pessoas", registre o porte sem perguntar.

## 3. Score e classificação

Score = soma dos pesos conforme `qualification_fields[].scoring` (`docs/03` §7).

| Classificação | Faixa padrão | Ação |
|---|---|---|
| `hot` | ≥ 70 | Ir para agendamento imediatamente |
| `warm` | 45–69 | Agendar, mas com nutrição prévia se o tenant preferir |
| `cold` | 20–44 | Oferecer material/conteúdo, colocar em cadência longa |
| `disqualified` | < 20 ou regra disparada | Encerrar com gentileza |

Limiar de agendamento (`scheduling_threshold`) configurável por tenant; padrão 45.

**Score é recalculado a cada `registrar_qualificacao`.** Um lead pode subir ou descer de faixa no meio da conversa.

## 4. Desqualificação

`disqualification_rules`:

```json
[
  {"field": "faturamento_mensal", "operator": "in", "value": ["ate_50k"],
   "reason": "abaixo do porte mínimo",
   "response": "Pelo que você me contou, nosso serviço ainda não faz sentido para o momento da sua empresa — seria investimento sem retorno agora. Vou te mandar um material gratuito que ajuda nessa fase. Quando crescer, me chama."},
  {"field": "intencao", "operator": "eq", "value": "concorrente",
   "reason": "concorrente",
   "response": "Obrigado pelo interesse. Nesse caso, prefiro não avançar por aqui. Sucesso aí."}
]
```

Regras:
- Desqualificar **nunca** é maltratar. O lead desqualificado hoje indica alguém amanhã.
- Não dizer "você não se qualifica" nem explicar o critério interno.
- Sempre oferecer uma saída de valor quando fizer sentido (material, conteúdo, indicação).
- Registrar `qualifications.disqualification_reason` — esse dado alimenta o ajuste do ICP do cliente.

## 5. Handoff para humano

### Gatilhos

| Gatilho | Detecção | Urgência |
|---|---|---|
| Pedido explícito | intenção classificada / termos ("falar com alguém", "atendente", "pessoa de verdade") | imediata |
| Sem resposta na base | `buscar_conhecimento` retornou vazio em pergunta factual | imediata |
| Irritação | sentimento negativo forte (Haiku) ou palavrão dirigido | imediata |
| Tema sensível | jurídico, reclamação, cobrança, saúde, dado sensível | imediata |
| Pedido de desconto/proposta | intenção comercial fora do escopo | imediata |
| Lead muito quente | score ≥ 85 + intenção de compra, se o tenant configurar | normal |
| Loop do agente | `MAX_ITERATIONS` estourado ou 2 erros seguidos de LLM | imediata |
| Repetição | agente deu a mesma resposta 2 vezes e o lead reformulou | normal |

### Procedimento

1. Chamar `escalar_para_humano(motivo, resumo)`.
2. Enviar ao lead a frase de transição do tenant. Padrão: *"Vou chamar alguém do time aqui para te ajudar com isso. Já te retorno."* — sem prometer prazo específico, a menos que o tenant configure um.
3. `conversations.status = 'human_handoff'`, agente **silenciado** naquela conversa.
4. Notificar pelos canais configurados (WhatsApp do vendedor, Slack, e-mail, webhook), com: nome, telefone, resumo, motivo do handoff, link do painel.
5. Se ninguém assumir em X minutos (`handoff_sla_minutes`, padrão 15), escalar o alerta para o gestor.
6. Retomada: só manual, pelo painel ("devolver ao agente"), que registra `resolved_at`.

Enquanto em handoff, mensagens do lead continuam sendo persistidas e aparecem no painel, mas o agente não responde. Nada de agente e humano falando junto.

### Fora do horário
Se o handoff ocorre fora do horário comercial, o agente avisa com honestidade: *"Vou passar para o time; eles respondem a partir das 9h de amanhã."* Prometer resposta imediata de madrugada quebra a confiança.

## 6. Follow-up

### Cadência padrão (`followup_cadence`, em minutos após a última mensagem do lead)

```json
[60, 1440, 4320, 10080]
```
(1 h, 1 dia, 3 dias, 7 dias). `max_followups` padrão 4.

### Regras
- Só dispara se a **última mensagem foi do agente** e o lead não respondeu.
- Cancelado imediatamente se o lead responder.
- Não dispara em `handoff_humano`, `opt_out`, `desqualificado`, `agendado` (agendado usa lembretes, não follow-up).
- Respeita o horário comercial: um follow-up que cairia às 23h vai para as 9h do dia seguinte.
- Fora da janela de 24 h (Meta): só com template aprovado. Sem template, registra `skipped`.
- Cada tentativa muda de ângulo. Repetir "oi, tudo bem?" quatro vezes é a forma mais rápida de ser bloqueado:
  1. Retomar a última pergunta feita.
  2. Trazer uma informação nova ou um caso parecido.
  3. Perguntar diretamente se o momento não é bom.
  4. Encerrar: *"Vou parar de te chamar por aqui. Se quiser retomar, é só me mandar mensagem."*

### Reengajamento de lead antigo
Lead que volta depois de dias: o agente reconhece ("que bom te ver de volta"), usa o resumo e **não** repete perguntas já respondidas. Se passaram mais de 30 dias, confirmar rapidamente se a situação mudou antes de reaproveitar os dados.

## 7. Opt-out

- Termos de parada: `sair`, `parar`, `pare`, `stop`, `descadastrar`, `não quero mais`, `me tira`, `remover`. Detecção por regex + classificação (Haiku) para pegar variações.
- Ação: `contacts.opted_out_at = now()`, `conversations.status = 'opted_out'`, cancelar follow-ups pendentes, enviar **uma** confirmação curta e nunca mais enviar nada.
- O bloqueio é por contato + tenant, verificado em `sender.py` antes de qualquer envio. Falha em respeitar isso é problema jurídico, não bug.

## 8. Saída para o CRM

Sincronizar quando: lead qualificado, reunião agendada, desqualificação, handoff, encerramento.

Payload canônico (usado no webhook genérico e mapeado para HubSpot):

```json
{
  "event": "meeting_scheduled",
  "tenant": "cliente-x",
  "occurred_at": "2026-07-29T14:03:00-03:00",
  "contact": {"name": "...", "phone": "+55...", "email": "...", "company": "...", "source": "anuncio_meta"},
  "qualification": {"score": 78, "classification": "hot", "answers": {...}},
  "appointment": {"starts_at": "...", "seller": "...", "meeting_url": "..."},
  "conversation_url": "https://painel.../conversas/<id>",
  "summary": "..."
}
```

Sempre assíncrono, com retry e registro em `crm_sync_log`. Falha de CRM **nunca** afeta a conversa com o lead.
