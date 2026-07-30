# 11 — Roadmap e Backlog

**Este é o ponto de partida do Claude Code.** Executar as fases em ordem. Cada tarefa tem critério de aceite. Marcar o checkbox e commitar ao concluir.

Estimativa total até um cliente em produção: 5 a 7 semanas de trabalho focado.

---

## Fase 0 — Fundação (2–3 dias)

- [x] **0.1** Estrutura do repositório conforme `CLAUDE.md` §3, `pyproject.toml` (ruff, mypy strict, pytest), `Makefile` com os alvos da §6.
  *Aceite:* `make lint` e `make test` rodam sem erro num projeto vazio.
- [x] **0.2** `docker-compose.yml` com postgres+pgvector, redis, evolution-api, api, worker. Healthchecks.
  *Aceite:* `make setup` sobe tudo e `/health` responde.
- [x] **0.3** `app/config.py` com pydantic-settings e `.env.example` completo.
  *Aceite:* app falha na inicialização com mensagem clara se faltar variável obrigatória.
- [x] **0.4** Logging estruturado com redação de dados pessoais (`docs/09` §6).
  *Aceite:* teste que falha se telefone completo ou conteúdo de mensagem aparecer no log.
- [x] **0.5** Camada de erros (`DomainError` e subclasses) e handler global do FastAPI.

## Fase 1 — Dados e multi-tenancy (3–4 dias)

- [x] **1.1** Models SQLAlchemy de todas as tabelas de `docs/03` + migração inicial Alembic.
  *Aceite:* `make upgrade` cria o schema completo, com índices.
- [x] **1.2** RLS habilitada com política por tenant; usuário da aplicação sem `BYPASSRLS`.
- [x] **1.3** `TenantContext` (contextvar) + dependência FastAPI + `SET LOCAL app.tenant_id` por transação.
- [x] **1.4** Repositórios base com filtro de tenant obrigatório.
  *Aceite:* `tests/integration/test_tenant_isolation.py` passa — contexto do tenant A não lê nada do tenant B, nem passando o id explicitamente.
- [x] **1.5** Criptografia de campos (`_encrypted`) com AES-GCM e `APP_ENCRYPTION_KEY`.
- [x] **1.6** Seed de tenant de demonstração (`make seed`).

## Fase 2 — Canal WhatsApp ponta a ponta (4–5 dias)

- [x] **2.1** `ChannelAdapter` (Protocol) e `InboundMessage` canônico.
- [x] **2.2** `EvolutionAdapter`: parse de `messages.upsert`, envio de texto, typing, `connection.update`.
- [x] **2.3** `MetaCloudAdapter`: verificação de webhook, validação HMAC do corpo cru, parse de mensagens e status, envio de texto, typing, templates, download de mídia.
  *Aceite:* testes com payloads reais de exemplo para os dois provedores.
- [x] **2.4** Endpoints de webhook com persistência do evento cru, dedupe e enfileiramento. Resposta 200 sem processamento síncrono.
  *Aceite:* p95 < 300 ms em teste local; evento duplicado não gera segunda mensagem.
- [x] **2.5** Worker `inbound_message`: resolve contato/conversa, persiste mensagem, aplica buffer com debounce.
  *Aceite:* 5 mensagens em 3 s disparam **um** `process_turn`.
- [x] **2.6** `sender.py`: opt-out, janela 24 h, rate limit, split, typing, delay, persistência e retry.
- [x] **2.7** Lock distribuído por conversa.
  *Aceite:* dois turnos simultâneos → um processa, o outro reagenda.
- [ ] **2.8** Eco de teste: agente responde repetindo a mensagem, sem LLM.
  *Bloqueado:* precisa de um número WhatsApp pareado no Evolution API (um número avulso serve — não precisa ser o definitivo). Retomar assim que houver um disponível.
  *Aceite:* mensagem real no WhatsApp de teste vai e volta.

## Fase 3 — Motor do agente (5–7 dias)

- [x] **3.1** `LLMProvider` com implementação Anthropic: tool calling, contagem de tokens, custo, prompt caching, retry.
- [x] **3.2** Templates Jinja2 dos prompts (`docs/05`) e renderização com contexto do tenant.
- [ ] **3.3** Máquina de estados e mapeamento estado → ferramentas permitidas.
- [ ] **3.4** Loop `run_turn` com `MAX_ITERATIONS`, timeouts, tratamento de falha e registro em `agent_runs`.
- [ ] **3.5** Ferramentas: `registrar_dados_lead`, `registrar_qualificacao`, `escalar_para_humano`, `desqualificar`, `encerrar_conversa`.
- [ ] **3.6** Cálculo de score e classificação a partir de `qualification_fields`.
- [ ] **3.7** Resumo rolante com Haiku a cada 15 mensagens.
- [ ] **3.8** Guardrails de entrada e saída (`docs/09` §1 e §2).
- [ ] **3.9** Infraestrutura de cenários de conversa em YAML, com modo `replay` e `live`.
  *Aceite:* 10 cenários passando em `replay`; conversa completa de qualificação funcionando no WhatsApp de teste.

## Fase 4 — Base de conhecimento (3–4 dias)

- [ ] **4.1** Ingestão: upload de PDF/DOCX/TXT/MD e captura de URL, com fila e status.
- [ ] **4.2** Chunking com sobreposição, preservando títulos de seção.
- [ ] **4.3** Embeddings + armazenamento em `knowledge_chunks` (HNSW).
- [ ] **4.4** Busca híbrida (vetorial + full-text português) com limiar de relevância e `faq_entries` com prioridade.
- [ ] **4.5** Ferramenta `buscar_conhecimento` integrada ao agente, retornando `encontrado: false` quando abaixo do limiar.
  *Aceite:* cenário "pergunta sem resposta na base" resulta em escalonamento, sem invenção.

## Fase 5 — Agendamento (4–5 dias)

- [ ] **5.1** `CalendarProvider` + OAuth Google (conexão, refresh, revogação).
- [ ] **5.2** Motor de disponibilidade com as regras de `docs/07` §3.
- [ ] **5.3** Reserva temporária de slot no Redis.
- [ ] **5.4** Ferramentas `consultar_horarios_disponiveis`, `agendar_reuniao`, `reagendar_reuniao`, `cancelar_reuniao`.
- [ ] **5.5** Criação do evento com Meet e descrição rica (resumo + qualificação).
- [ ] **5.6** Distribuição entre vendedores (single / round-robin / regra).
- [ ] **5.7** Lembretes de 24 h e 1 h.
  *Aceite:* conversa completa termina com evento real no Google Agenda e link enviado no WhatsApp.

## Fase 6 — Handoff, follow-up e CRM (3–4 dias)

- [ ] **6.1** Fluxo completo de handoff: gatilhos, silenciamento do agente, notificação multicanal, SLA e escalonamento.
- [ ] **6.2** Detecção de opt-out (regex + classificador) e bloqueio global de envio.
- [ ] **6.3** Follow-up com cadência, respeito ao horário comercial e à janela de 24 h, ângulo diferente por tentativa.
- [ ] **6.4** Exportador CRM: webhook genérico + HubSpot, com retry e `crm_sync_log`.
- [ ] **6.5** Transcrição de áudio.

## Fase 7 — Painel administrativo (5–7 dias)

- [ ] **7.1** Autenticação (JWT, argon2, MFA para superadmin) e autorização por papel e tenant.
- [ ] **7.2** CRUD de tenants, configs (com versionamento e rollback), canais, vendedores.
- [ ] **7.3** Editor de prompt e de campos de qualificação, com pré-visualização e teste em sandbox.
- [ ] **7.4** Gestão da base de conhecimento.
- [ ] **7.5** Inbox de conversas: transcrição, "assumir conversa", "devolver ao agente", enviar mensagem manual.
- [ ] **7.6** Dashboard com as métricas de `docs/10` §1.
  *Aceite:* subir um cliente novo do zero sem tocar em código nem em banco.

## Fase 8 — Produção (3–4 dias)

- [ ] **8.1** Métricas Prometheus e integração Langfuse.
- [ ] **8.2** Alertas de `docs/10` §4.
- [ ] **8.3** Jobs de expurgo e anonimização (LGPD).
- [ ] **8.4** Endpoints de direitos do titular (exportar, anonimizar).
- [ ] **8.5** CI/CD completo e deploy em produção.
- [ ] **8.6** Script de fumaça para novo cliente.
- [ ] **8.7** Teste de carga (200 conversas simultâneas).
- [ ] **8.8** Runbook de operação e de incidentes.

---

## Backlog pós-v1

- Instagram DM e webchat (a abstração de canal já prevê).
- Botões e listas interativas do WhatsApp em pontos-chave (escolha de horário vira um clique).
- Voz: recepção de ligação com agente falado.
- Testes A/B de prompt por tenant, com medição de conversão.
- Modo outbound com importação de lista, cadência e controle de consentimento.
- Enriquecimento de lead (CNPJ, LinkedIn) antes da conversa.
- Autoaprendizado: sugerir automaticamente novos itens de FAQ a partir dos handoffs por "sem resposta na base".
- Painel white-label para o cliente final.
- Integrações nativas: RD Station, Pipedrive, Kommo.

## O que não fazer

- Não colocar cliente pagante em produção na Evolution API.
- Não deixar o agente falar de preço sem a informação estar na base.
- Não implementar o painel antes do agente funcionar de ponta a ponta no WhatsApp.
- Não pular os cenários de conversa: sem eles, cada ajuste de prompt quebra algo em silêncio.
- Não subir para mais de um cliente antes de o primeiro rodar um mês estável.
