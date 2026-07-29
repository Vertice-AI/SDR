# 02 — Arquitetura

## 1. Visão geral

```
                    ┌──────────────────────────────────────────────┐
   WhatsApp         │                  sdr-agent                    │
   (lead)           │                                               │
      │             │  ┌────────────┐      ┌──────────────────┐     │
      ├─ webhook ──▶│  │  FastAPI   │─────▶│  Redis           │     │
      │             │  │  /webhooks │ push │  buffer + fila   │     │
      │             │  └────────────┘      └────────┬─────────┘     │
      │             │        │ persiste evento      │ consome       │
      │             │        ▼                      ▼               │
      │             │  ┌────────────┐      ┌──────────────────┐     │
      │             │  │ PostgreSQL │◀────▶│  Worker ARQ      │     │
      │             │  │ + pgvector │      │  turn_processor  │     │
      │             │  └────────────┘      └────────┬─────────┘     │
      │             │                               │               │
      │             │                       ┌───────▼─────────┐     │
      │             │                       │ Agent Runtime   │     │
      │             │                       │ loop tool call  │     │
      │             │                       └───┬────┬────┬───┘     │
      │             │                           │    │    │         │
      │             │            ┌──────────────┘    │    └──────┐  │
      │             │            ▼                   ▼           ▼  │
      │             │      ┌──────────┐      ┌────────────┐ ┌───────────┐
      │             │      │Knowledge │      │  Calendar  │ │   CRM     │
      │             │      │  (RAG)   │      │  (Google)  │ │ (HubSpot/ │
      │             │      └──────────┘      └────────────┘ │ webhook)  │
      │             │                                        └───────────┘
      │             │                       ┌─────────────────┐         │
      ◀─ resposta ──│───────────────────────│ ChannelAdapter  │         │
                    │                       │ meta / evolution│         │
                    └───────────────────────┴─────────────────┴─────────┘
                                   │
                            ┌──────▼──────┐
                            │  Langfuse   │  traces, custo, avaliação
                            └─────────────┘
```

## 2. Fluxo completo de uma mensagem

1. **Webhook** chega em `POST /webhooks/{provider}/{tenant_slug}`.
2. Valida assinatura (HMAC da Meta / token da Evolution). Assinatura inválida → 403 e log de segurança.
3. Persiste o payload cru em `webhook_events` (auditoria e reprocessamento).
4. Faz *dedupe* por `provider_message_id`. Duplicado → 200 imediato, nada a fazer.
5. Enfileira `inbound_message` no Redis. **Responde 200.** Tudo isso em < 200 ms.
6. Worker `inbound_message`:
   - Resolve ou cria `contact` e `conversation`.
   - Se for áudio, chama transcrição (Whisper/Deepgram) e substitui o conteúdo.
   - Persiste a `message`.
   - Verifica opt-out e pausa (handoff ativo) → se sim, apenas armazena e para.
   - Empilha o texto no buffer Redis `buf:{conversation_id}` e agenda `process_turn` para daqui a N segundos, cancelando o agendamento anterior (debounce).
7. Worker `process_turn`:
   - Adquire lock `lock:conv:{conversation_id}` (TTL 120 s). Se não conseguir, reagenda em 5 s.
   - Monta o contexto: config do tenant, perfil do lead, estado da qualificação, resumo + últimas N mensagens, horário atual no fuso do tenant.
   - Roda o **Agent Runtime** (loop de tool calling, máx. 6 iterações).
   - Aplica guardrails pós-geração.
   - Envia a resposta pelo `ChannelAdapter` (typing + delay + split).
   - Persiste mensagens de saída, atualiza estado, grava trace e custo.
   - Libera o lock.
8. Efeitos colaterais (CRM, notificação de handoff, agendamento de follow-up) são enfileirados como tasks separadas — nunca bloqueiam a resposta ao lead.

## 3. Decisões técnicas

### ADR-001 — Loop de agente escrito à mão, sem framework
**Decisão:** implementar o loop de tool calling diretamente sobre o SDK da Anthropic.
**Por quê:** o loop tem ~150 linhas. Frameworks de agente adicionam camadas de abstração que atrapalham exatamente onde precisamos de controle fino: injeção de contexto por tenant, guardrails entre a decisão e a execução, contabilidade de tokens por conversa e testes determinísticos. Também quebram com frequência entre versões.
**Consequência:** escrevemos e mantemos o loop, o retry e o parsing de tool use. Aceito.

### ADR-002 — Multi-tenant com banco único e RLS
**Decisão:** um banco, `tenant_id` em todas as tabelas, Row Level Security ativa, segredos por tenant criptografados na aplicação.
**Por quê:** dezenas de clientes de porte pequeno/médio. Banco por tenant multiplica custo de migração e operação sem ganho real nesse volume.
**Consequência:** disciplina obrigatória no acesso a dados. Todo repositório recebe o tenant no construtor. Teste automatizado que tenta vazar dados entre tenants é obrigatório.
**Revisitar quando:** um cliente exigir isolamento físico por contrato, ou passarmos de ~200 tenants.

### ADR-003 — Abstração de canal com dois adaptadores
**Decisão:** `ChannelAdapter` como Protocol, com `MetaCloudAdapter` (produção) e `EvolutionAdapter` (desenvolvimento, PoC e cliente que não pode/não quer verificação Meta).
**Por quê:** a Evolution API é rápida de subir e não custa por conversa, mas usa WhatsApp não oficial — há risco de bloqueio do número e não há garantia de entrega. Colocar um cliente pagante em produção nela é assumir esse risco pelo cliente. A Cloud API é o caminho padrão para produção.
**Consequência:** capacidades diferem entre adaptadores (templates HSM só existem na Meta). O adaptador expõe `supports(capability)` e o agente degrada de forma controlada — sem template, um follow-up fora da janela de 24 h simplesmente não é enviado.
**Regra prática de operação:** homologação e demonstração na Evolution; contrato assinado, migra para Cloud API.

### ADR-004 — Debounce de 8 segundos no buffer de mensagens
**Decisão:** aguardar silêncio de 8 s (configurável, teto de 30 s) antes de processar.
**Por quê:** é o comportamento real do WhatsApp. Sem isso o agente responde três vezes a uma frase quebrada em três mensagens e a conversa vira lixo.
**Consequência:** +8 s na latência percebida — aceitável, e ainda muito abaixo de qualquer humano.

### ADR-005 — Google Calendar direto, com link como plano B
**Decisão:** integração nativa via OAuth, `freebusy.query` + `events.insert` com `conferenceData` (Meet). Link externo (Cal.com/Calendly) apenas como fallback configurável por tenant.
**Por quê:** o valor do produto está em fechar a agenda dentro da conversa. Mandar link é onde o funil vaza.
**Consequência:** gerenciar OAuth por vendedor, refresh token criptografado, tratar revogação de acesso.

### ADR-006 — pgvector em vez de banco vetorial dedicado
**Decisão:** embeddings em Postgres com `pgvector`, busca híbrida (vetorial + full-text em português).
**Por quê:** a base de conhecimento de um cliente de SDR tem dezenas a poucas centenas de documentos. Não justifica outro serviço para operar, e o filtro por `tenant_id` fica trivial e seguro.
**Revisitar quando:** algum tenant passar de ~50 mil chunks.

### ADR-007 — Anthropic Claude como provedor primário, com abstração
**Decisão:** Sonnet para a conversa, Haiku para tarefas baratas (classificação de intenção, extração de campos, detecção de sentimento, resumo). Interface `LLMProvider` isolando o SDK.
**Por quê:** melhor aderência a instruções longas em PT-BR e tool calling confiável. Dois modelos porque rodar tudo no modelo grande triplica o custo por conversa sem ganho.
**Consequência:** custo por conversa precisa ser medido desde o início e aparecer no dashboard por tenant.

## 4. Componentes

**API (`app/api`)** — só recebe, valida, persiste e enfileira. Nenhuma regra de negócio. Endpoints administrativos autenticados por JWT com escopo de tenant.

**Agent Runtime (`app/agent/runtime.py`)** — monta o prompt, chama o LLM, executa ferramentas, aplica guardrails, decide encerrar. Detalhado em `docs/04-motor-de-conversa.md`.

**Channels (`app/channels`)** — envio e normalização de entrada. Cada adaptador converte o payload do provedor para `InboundMessage` canônico e a resposta para o formato do provedor.

**Knowledge (`app/knowledge`)** — ingestão (PDF, DOCX, TXT, URL), chunking semântico com sobreposição, embeddings, busca híbrida com reranking simples. Retorna trechos com fonte para citação interna e rastreabilidade.

**Calendar (`app/calendar`)** — disponibilidade e eventos, com regras de janela comercial por vendedor.

**CRM (`app/crm`)** — saída de dados: HubSpot nativo, webhook genérico e Google Sheets. Sempre assíncrono e tolerante a falha; falha de CRM nunca derruba a conversa.

**Workers (`app/workers`)** — `inbound_message`, `process_turn`, `send_followup`, `send_reminder`, `ingest_document`, `summarize_conversation`, `sync_crm`.

## 5. Ambientes

| Ambiente | WhatsApp | Banco | Uso |
|---|---|---|---|
| local | Evolution API em Docker + número de teste | Postgres em container | desenvolvimento |
| homologação | Evolution API ou número de teste da Meta | instância separada | demonstração para prospect |
| produção | Meta Cloud API | instância gerenciada com backup | clientes |

## 6. Requisitos não funcionais

- Ack de webhook: p95 < 300 ms.
- Primeira resposta ao lead: p95 < 30 s (incluindo o debounce).
- Disponibilidade alvo: 99,5 %.
- Nenhuma mensagem perdida: todo evento recebido fica em `webhook_events` e pode ser reprocessado.
- Custo por conversa observável por tenant, em tempo quase real.
