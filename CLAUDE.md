# CLAUDE.md — Agente SDR WhatsApp

Contexto operacional para o Claude Code trabalhar neste repositório. Leia este arquivo inteiro antes de escrever código. Os detalhes de cada área estão em `docs/`.

---

## 1. O que estamos construindo

Um **agente de IA de pré-vendas (SDR)** que atende leads no WhatsApp de forma autônoma. Ele:

1. Recebe o lead (inbound ou outbound), se apresenta e conduz a conversa.
2. **Qualifica** segundo um framework configurável por cliente (BANT/GPCT por padrão).
3. **Responde dúvidas** usando exclusivamente a base de conhecimento do cliente (RAG).
4. **Agenda a reunião** direto no Google Calendar do vendedor, dentro da conversa.
5. **Escala para humano** quando não sabe, quando o lead pede, ou quando detecta risco.
6. Faz **follow-up** de leads que sumiram, respeitando cadência e opt-out.

É um **produto multi-tenant**: uma única base serve vários clientes da agência, cada um com seu número de WhatsApp, prompt, ICP, critérios de qualificação, base de conhecimento e agenda.

**Nome interno do projeto:** `sdr-agent`
**Idioma de todo o produto e do código-fonte visível ao usuário:** português do Brasil.

---

## 2. Stack definida

| Camada | Escolha | Motivo |
|---|---|---|
| Linguagem | Python 3.12 | Ecossistema de IA maduro |
| API | FastAPI + Uvicorn | Async nativo, webhooks rápidos |
| Banco | PostgreSQL 16 + extensão `pgvector` | Dados relacionais + embeddings no mesmo lugar |
| ORM / Migrações | SQLAlchemy 2.0 (async) + Alembic | Padrão de mercado |
| Cache / Fila / Locks | Redis 7 | Buffer de mensagens, locks por conversa, rate limit |
| Workers | ARQ (async Redis queue) | Async nativo, mais simples que Celery |
| LLM | Anthropic Claude (Sonnet = conversa, Haiku = classificação/roteamento) | Melhor aderência a instruções em PT-BR |
| Abstração LLM | Interface própria `LLMProvider` | Trocar para OpenAI sem reescrever o agente |
| WhatsApp | Interface `ChannelAdapter` com 2 implementações: **Meta Cloud API** (produção) e **Evolution API** (dev/PoC) | Não amarrar o produto a um provedor |
| Agenda | Google Calendar API (freebusy + insert com Meet), fallback para link Cal.com | Agendamento real dentro da conversa |
| Observabilidade | Langfuse (traces de LLM) + structlog (JSON) + Prometheus | Custo e qualidade por conversa |
| Testes | pytest + pytest-asyncio + testcontainers | Integração real com Postgres/Redis |
| Qualidade | ruff (lint+format) + mypy (strict) | Padrão único |
| Deploy | Docker Compose (dev) / Docker + Fly.io ou VPS com Traefik (prod) | Simples de operar |

**Não introduza LangChain, LlamaIndex, CrewAI ou frameworks de agente.** O loop de tool calling é escrito à mão em `app/agent/`. É pouco código, totalmente controlável e evita quebras de versão. Isto é uma decisão firme — veja `docs/02-arquitetura.md`.

---

## 3. Estrutura do repositório

```
sdr-agent/
├── CLAUDE.md                  # este arquivo
├── README.md
├── docs/                      # planejamento e especificação (leia antes de codar)
├── pyproject.toml
├── .env.example
├── docker-compose.yml
├── Dockerfile
├── alembic/                   # migrações
├── app/
│   ├── main.py                # FastAPI app factory
│   ├── config.py              # Settings via pydantic-settings
│   ├── deps.py                # dependências FastAPI (db, tenant, auth)
│   ├── api/
│   │   ├── webhooks/          # entrada: meta.py, evolution.py
│   │   ├── admin/             # CRUD de tenants, config, base de conhecimento
│   │   └── health.py
│   ├── agent/
│   │   ├── runtime.py         # loop de tool calling — o coração
│   │   ├── prompts/           # templates Jinja2 dos prompts de sistema
│   │   ├── tools/             # uma ferramenta por arquivo
│   │   ├── state.py           # máquina de estados da conversa
│   │   └── guardrails.py      # validações pré e pós geração
│   ├── channels/
│   │   ├── base.py            # ChannelAdapter (Protocol)
│   │   ├── meta_cloud.py
│   │   └── evolution.py
│   ├── calendar/
│   │   ├── base.py            # CalendarProvider (Protocol)
│   │   └── google.py
│   ├── knowledge/             # ingestão, chunking, embeddings, busca
│   ├── crm/                   # exportadores: hubspot.py, webhook.py, planilha.py
│   ├── models/                # SQLAlchemy models
│   ├── schemas/               # Pydantic
│   ├── services/              # regras de negócio (conversation, lead, scheduling)
│   ├── workers/               # tasks ARQ: debounce, follow-up, ingestão
│   └── core/                  # logging, security, errors, tenancy
└── tests/
    ├── unit/
    ├── integration/
    └── conversations/         # cenários de conversa end-to-end (golden tests)
```

---

## 4. Regras invioláveis

Estas regras existem porque cada uma delas, se quebrada, gera bug em produção com cliente real vendo.

### 4.1 Multi-tenancy
- **Toda** tabela de negócio tem `tenant_id NOT NULL` e índice começando por `tenant_id`.
- **Toda** query passa por um repositório que injeta o filtro de tenant. Nunca escreva `select(Model)` solto num handler.
- Row Level Security habilitada no Postgres como segunda linha de defesa.
- Segredos por tenant (tokens da Meta, refresh token do Google) ficam **criptografados** na coluna, com chave em `APP_ENCRYPTION_KEY`. Nunca em texto puro.

### 4.2 Webhooks
- Responder **HTTP 200 em menos de 3 segundos, sempre**. Validar assinatura, persistir o evento bruto, enfileirar, retornar. Zero processamento síncrono.
- **Idempotência obrigatória**: `UNIQUE(tenant_id, provider_message_id)`. O WhatsApp reenvia eventos; processar duas vezes = mandar mensagem duplicada para o lead.

### 4.3 Buffer de mensagens (crítico)
Pessoas escrevem no WhatsApp em rajada: "oi" / "vi seu anúncio" / "quanto custa?". Responder cada uma é o erro nº 1 de agentes de WhatsApp.
- Ao receber mensagem, empilhe no Redis e agende o processamento para **8 segundos depois** (configurável por tenant).
- Nova mensagem no intervalo **reinicia** o timer (debounce), até um teto de 30 s.
- Processe todas as mensagens acumuladas como **um único turno**.

### 4.4 Concorrência
- Lock distribuído no Redis por `conversation_id` antes de rodar o agente. Sem lock, duas respostas saem ao mesmo tempo e a conversa quebra.
- Lock com TTL e liberação garantida em `finally`.

### 4.5 Comportamento humano
- Enviar indicador de "digitando" antes da resposta.
- Delay proporcional ao tamanho do texto (~ 250 ms + 25 ms por caractere, teto de 6 s).
- Quebrar respostas longas em 2–3 mensagens curtas. **Nunca** mandar parágrafo de 10 linhas no WhatsApp.
- Sem emoji, sem markdown (`**negrito**` não renderiza no WhatsApp — use `*negrito*` do próprio WhatsApp, com moderação).

### 4.6 Antialucinação
- O agente **só** responde sobre produto/preço/prazo com base no que a busca na base de conhecimento retornou. Se não retornou nada relevante, ele diz que vai confirmar e usa `escalar_para_humano`.
- Preço, desconto, prazo contratual e promessa de resultado: **nunca** improvisar. Estão em `docs/09-seguranca-lgpd-guardrails.md`.
- Guardrail pós-geração verifica menção a valores monetários não presentes no contexto recuperado e bloqueia o envio.

### 4.7 Agendamento
- Sempre consultar disponibilidade real (`freebusy`) antes de oferecer horários. Nunca inventar horário.
- Oferecer **no máximo 3 opções** por vez, em linguagem natural ("amanhã às 10h ou 15h, ou quinta às 9h?").
- Criar o evento apenas após confirmação explícita do lead.
- Timezone sempre explícito (`America/Sao_Paulo` por padrão, configurável por tenant). Nunca usar `datetime.now()` sem tz — use `datetime.now(tz=UTC)` e converta na borda.

### 4.8 LGPD
- Consentimento e opt-out registrados. "Sair", "parar", "não quero mais" → opt-out imediato, confirmação e nenhuma mensagem futura.
- Log **nunca** contém conteúdo de mensagem ou telefone completo. Use hash/máscara. Veja `app/core/logging.py`.

---

## 5. Convenções de código

- **Nomes de domínio em português** (`Conversa`? Não — veja abaixo), **código em inglês**. Padrão adotado: identificadores em inglês (`Conversation`, `Lead`, `Appointment`), textos voltados ao usuário e nomes de ferramentas do LLM em português (`agendar_reuniao`). O LLM performa melhor com ferramentas nomeadas no idioma da conversa.
- Type hints obrigatórios. `mypy --strict` precisa passar.
- Funções async por padrão; nada de I/O bloqueante no event loop.
- Erros de domínio herdam de `app.core.errors.DomainError`. Nunca `except Exception: pass`.
- Toda função que fala com serviço externo tem timeout explícito e retry com backoff (`tenacity`).
- Docstrings em português, curtas, explicando o *porquê*.
- Commits: Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`).

---

## 6. Comandos

```bash
make setup          # cria venv, instala deps, sobe docker-compose, roda migrações
make dev            # sobe a API com reload
make worker         # sobe o worker ARQ
make test           # pytest completo
make test-conv      # apenas os cenários de conversa (rápido, sem rede)
make lint           # ruff check + ruff format --check + mypy
make fix            # ruff format + ruff check --fix
make migrate m="descricao"   # gera migração alembic
make upgrade        # aplica migrações
make seed           # cria tenant de demonstração com dados fictícios
```

Antes de considerar qualquer tarefa concluída: `make lint && make test` precisa passar.

---

## 7. Fluxo de trabalho esperado do Claude Code

1. Leia `docs/11-roadmap-e-backlog.md` e pegue a próxima tarefa não concluída da fase atual.
2. Leia os documentos referenciados por aquela tarefa.
3. Implemente com testes. Teste primeiro quando for regra de negócio.
4. Rode `make lint && make test`.
5. Atualize o checkbox da tarefa no roadmap e faça o commit.
6. Se uma decisão de arquitetura precisar mudar, **pare e pergunte** — não mude a stack por conta própria.

Não crie arquivos fora da estrutura da seção 3 sem justificar. Não gere README para cada pasta. Não escreva código de exemplo em `docs/` que não vá para o repositório.

---

## 8. Índice da documentação

| Arquivo | Conteúdo |
|---|---|
| `docs/01-produto-e-escopo.md` | Problema, personas, escopo funcional, o que está fora, métricas de sucesso |
| `docs/02-arquitetura.md` | Diagrama, fluxo de uma mensagem, decisões técnicas com justificativa |
| `docs/03-modelo-de-dados.md` | Todas as tabelas, colunas, índices e RLS |
| `docs/04-motor-de-conversa.md` | Máquina de estados, loop de tool calling, buffer, ferramentas |
| `docs/05-prompts.md` | Prompt de sistema completo, variáveis por tenant, exemplos |
| `docs/06-integracao-whatsapp.md` | Meta Cloud API, Evolution API, janela 24h, templates, mídia |
| `docs/07-integracao-agenda.md` | Google Calendar, OAuth, freebusy, regras de disponibilidade |
| `docs/08-qualificacao-e-handoff.md` | Framework de qualificação, score, critérios de escalonamento, follow-up |
| `docs/09-seguranca-lgpd-guardrails.md` | Guardrails, prompt injection, LGPD, retenção, criptografia |
| `docs/10-observabilidade-e-testes.md` | Métricas, traces, custo por conversa, estratégia de testes |
| `docs/11-roadmap-e-backlog.md` | Fases, tarefas e critérios de aceite — **comece por aqui** |
| `docs/12-deploy-e-infra.md` | Ambientes, docker, CI/CD, onboarding de novo cliente |
