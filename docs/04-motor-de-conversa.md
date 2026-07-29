# 04 — Motor de Conversa

## 1. Buffer e debounce

Sem isto o agente responde três vezes a uma frase quebrada em três mensagens. É o requisito mais importante deste documento.

**Chaves Redis**

- `buf:{conversation_id}` — lista de mensagens pendentes (JSON).
- `buftimer:{conversation_id}` — job id do processamento agendado.
- `lock:conv:{conversation_id}` — lock de processamento, TTL 120 s.

**Algoritmo (`app/workers/inbound.py`)**

```
ao receber mensagem:
    RPUSH buf:{conv} mensagem
    se existe buftimer:{conv}: cancela o job agendado
    primeira_msg_em = TTL restante da chave buffirst:{conv}
    se não existe buffirst:{conv}: SET buffirst:{conv} agora EX 30
    atraso = min(debounce_seconds, 30 - segundos_desde_primeira)
    job = enfileira process_turn(conv) com atraso
    SET buftimer:{conv} = job.id
```

Teto rígido de 30 s: se o lead escreve sem parar, processamos mesmo assim.

**Ao processar**: `LRANGE` + `DEL` de forma atômica (script Lua ou `MULTI`), concatena as mensagens com quebra de linha e trata como **um turno**.

Casos que ignoram o buffer e processam na hora:
- Mensagem que é resposta a botão/lista interativa.
- Comando de opt-out (`sair`, `parar`, `descadastrar`).

## 2. Lock por conversa

```python
async with conversation_lock(conversation_id, ttl=120) as acquired:
    if not acquired:
        await requeue(process_turn, conversation_id, delay=5)
        return
    ...
```

Sem lock, dois turnos concorrentes geram duas respostas simultâneas e o histórico fica incoerente. Liberação sempre em `finally`, e o lock guarda um token aleatório para não liberar lock de outro processo.

## 3. Máquina de estados

O estado **não** controla o que o agente diz — o LLM faz isso. O estado controla **o que é permitido**, quais ferramentas ficam disponíveis e o que o prompt enfatiza.

| Estado | Significado | Ferramentas liberadas |
|---|---|---|
| `novo` | Nenhuma mensagem trocada ainda | — |
| `abertura` | Primeiro contato, apresentação | buscar_conhecimento, registrar_dados_lead, escalar |
| `qualificando` | Coletando campos | + registrar_qualificacao, desqualificar |
| `respondendo_duvidas` | Lead com objeções/perguntas | + buscar_conhecimento (prioritário), escalar |
| `agendando` | Qualificado, propondo horários | + consultar_horarios, agendar_reuniao |
| `agendado` | Reunião confirmada | + reagendar, cancelar_reuniao |
| `aguardando_lead` | Lead não respondeu, follow-up ativo | — (só follow-up) |
| `handoff_humano` | Humano assumiu | nenhuma; agente silenciado |
| `desqualificado` | Fora do ICP | nenhuma; encerra educadamente |
| `encerrado` | Fim | nenhuma |
| `opt_out` | Lead pediu para parar | nenhuma; nunca mais enviar |

**Transições**: decididas por código após o turno, com base no resultado das ferramentas — nunca pelo LLM diretamente. Exemplo: `qualificando → agendando` acontece quando `qualifications.score >= limiar_agendamento` E todos os campos `required` estão preenchidos.

Estados podem retroceder: um lead em `agendando` que faz uma pergunta nova volta a `respondendo_duvidas` e depois retorna. Registre a transição em `agent_runs.state_before/state_after`.

## 4. Loop do agente

`app/agent/runtime.py`, pseudocódigo:

```python
async def run_turn(ctx: TurnContext) -> TurnResult:
    messages = build_message_history(ctx)      # resumo + últimas N + turno atual
    system = render_system_prompt(ctx)         # Jinja2, ver docs/05
    tools = tools_for_state(ctx.state)

    for i in range(MAX_ITERATIONS):            # MAX_ITERATIONS = 6
        response = await llm.complete(
            system=system, messages=messages, tools=tools,
            model=ctx.model, max_tokens=1024, temperature=0.4,
        )
        record_usage(ctx, response.usage)

        if response.stop_reason != "tool_use":
            break

        for call in response.tool_calls:
            check_tool_allowed(call.name, ctx.state)   # guardrail
            result = await execute_tool(call, ctx)     # timeout por ferramenta
            messages.append(tool_result(call.id, result))

    reply = extract_text(response)
    reply = apply_output_guardrails(reply, ctx)
    return TurnResult(reply=reply, tool_results=..., new_state=decide_state(ctx))
```

Regras:

- `MAX_ITERATIONS = 6`. Ao estourar, envia mensagem de espera e escala para humano.
- Timeout de 20 s por chamada de LLM, 10 s por ferramenta. Retry: 2 tentativas com backoff só em erro transitório (429, 5xx, timeout).
- Se o LLM falhar definitivamente: mensagem neutra ("Só um instante, já te respondo") + escalonamento + alerta. **Nunca** silêncio.
- **Prompt caching** no bloco de sistema e na base de conhecimento fixa — é o que segura o custo por conversa.
- `temperature` 0.4 na conversa, 0 nas tarefas de extração/classificação.

### Janela de contexto

- Manter as últimas 20 mensagens completas.
- Acima disso, resumo rolante gerado por Haiku a cada 15 mensagens novas, guardado em `conversations.summary`.
- O resumo preserva: dor relatada, objeções levantadas, dados já coletados, compromissos assumidos, preferências de horário.

## 5. Ferramentas

Uma por arquivo em `app/agent/tools/`. Toda ferramenta: schema Pydantic de entrada, retorno serializável, tratamento de erro que devolve mensagem útil ao LLM (nunca stacktrace).

### `buscar_conhecimento(pergunta: str) -> list[Trecho]`
Busca híbrida na base do tenant. Primeiro checa `faq_entries` (similaridade alta → resposta curada tem prioridade). Retorna até 5 trechos com título de origem.
Se nada acima do limiar: retorna `{"encontrado": false}` — e o prompt instrui a admitir e escalar.

### `registrar_dados_lead(nome?, email?, empresa?, cargo?)`
Atualiza `contacts`. Chamar sempre que o lead informar algo, sem perguntar de novo depois.

### `registrar_qualificacao(campo: str, valor: str, confianca: float)`
Grava em `qualifications.answers`, recalcula score e classificação. Uma chamada por campo. O LLM deve chamar assim que a informação aparecer na conversa, mesmo que dita de forma indireta.

### `consultar_horarios_disponiveis(preferencia?: str, data_inicial?: date) -> list[Slot]`
Retorna até 3 slots reais, já filtrados pelas regras de disponibilidade. `preferencia` aceita texto livre ("de manhã", "depois de quinta"). Nunca retorna slot no passado nem dentro da antecedência mínima.

### `agendar_reuniao(slot_id: str, nome: str, email: str) -> Appointment`
Só depois de confirmação explícita. Cria evento com Meet, grava `appointments`, dispara notificação ao vendedor e sincronia com CRM. Se o slot foi tomado no intervalo, retorna erro tratável e o LLM reoferece.

### `reagendar_reuniao(appointment_id, novo_slot_id)` / `cancelar_reuniao(appointment_id, motivo)`

### `escalar_para_humano(motivo: str, resumo: str)`
Marca `handoff`, muda estado, notifica. Retorna ao LLM a frase de transição que ele deve dizer (configurável por tenant), para não improvisar promessa de prazo.

### `desqualificar(motivo: str)`
Encerra educadamente com a mensagem configurada. Nunca ser rude nem dizer "você não se qualifica".

### `encerrar_conversa(motivo: str)`
Para casos de agradecimento final ou lead que só queria informação.

**Ferramentas explicitamente ausentes na v1:** enviar proposta, aplicar desconto, alterar preço, prometer prazo de entrega. Se o lead pedir, o caminho é escalar.

## 6. Formatação da resposta

Executado em `app/channels/formatting.py` depois dos guardrails:

1. Remover markdown não suportado (`**`, `##`, `-` de lista vira `•`, links crus mantidos).
2. Quebrar em no máximo 3 mensagens, cortando em parágrafo ou frase. Cada mensagem com no máximo ~350 caracteres, salvo bloco indivisível.
3. Para cada mensagem: enviar "digitando", aguardar `min(6000, 250 + 25 * len(texto))` ms, enviar, aguardar 400 ms.
4. Uma pergunta por turno. Se o texto tiver dois "?", registrar flag de guardrail e preferir reescrever.

## 7. Entrada de mídia

| Tipo | Tratamento v1 |
|---|---|
| Texto | direto |
| Áudio | transcrever (Whisper API ou Deepgram); se falhar, pedir texto educadamente |
| Imagem | descrever com modelo de visão só se `tenant_configs.enable_vision` estiver ligado; senão, responder pedindo o contexto por texto |
| Documento | não interpretar na v1; reconhecer o recebimento e escalar se relevante |
| Localização | registrar em `source_metadata`, seguir a conversa |
| Sticker / reação | ignorar sem quebrar o fluxo |

## 8. Casos difíceis (testar todos em `tests/conversations/`)

| Situação | Comportamento esperado |
|---|---|
| Lead manda 5 mensagens em 3 s | 1 resposta só |
| Lead pergunta preço e não está na base | Não inventa; diz que confirma e escala |
| Lead pergunta preço e está na base | Responde exatamente o que está na base |
| Lead responde só "sim" fora de contexto | Retoma a última pergunta feita |
| Lead pergunta "você é um robô?" | Responde com honestidade, tom leve, e segue |
| Lead xinga / está irritado | Não revida, valida a frustração e escala |
| Lead tenta prompt injection ("ignore suas instruções") | Ignora e continua o atendimento normalmente |
| Lead pede desconto | Não negocia; escala |
| Lead some no meio da qualificação | Entra em follow-up conforme cadência |
| Lead volta 15 dias depois | Retoma com contexto, sem repetir tudo |
| Dois leads do mesmo número/empresa | Mesma conversa, contexto único |
| Lead pede para falar com humano | Escala imediatamente, sem insistir |
| Lead diz "sai daqui", "para" | Opt-out, confirma e nunca mais envia |
| Lead sugere horário indisponível | Recusa com clareza e oferece alternativa próxima |
| Lead confirma horário e o slot já foi ocupado | Pede desculpa, reoferece na hora |
| Mensagem fora do horário comercial | Conforme `out_of_hours_behavior` do tenant |
| Lead menor de idade / tema sensível | Escala |
