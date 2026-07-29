# 12 — Deploy e Infraestrutura

## 1. Ambientes

| Ambiente | Onde | WhatsApp | Observações |
|---|---|---|---|
| local | docker-compose | Evolution API em container + número de teste | dados fictícios |
| homologação | VPS pequena ou Fly.io | Evolution ou número de teste da Meta | usado em demonstração |
| produção | VPS (Hetzner/Contabo) com Docker + Traefik, ou Fly.io | Meta Cloud API | backup diário, monitoramento |

Comece simples: uma VPS com Docker Compose e Traefik atende dezenas de clientes. Kubernetes só quando houver motivo real.

## 2. Serviços em produção

| Serviço | Réplicas | Notas |
|---|---|---|
| `api` (FastAPI/Uvicorn) | 2 | atrás do Traefik, TLS automático |
| `worker` (ARQ) | 2–4 | escala com volume de conversas |
| `scheduler` (ARQ cron) | 1 | follow-ups, lembretes, expurgo, resumos |
| `postgres` 16 + pgvector | 1 | gerenciado é preferível (Neon/Supabase/RDS) |
| `redis` 7 | 1 | com persistência AOF |
| `langfuse` | 1 | opcional self-hosted, ou nuvem |

## 3. docker-compose (dev) — serviços esperados

`api`, `worker`, `scheduler`, `postgres` (imagem `pgvector/pgvector:pg16`), `redis`, `evolution-api`, `mailhog` (opcional). Volumes nomeados para postgres e redis. Healthchecks em todos.

## 4. Variáveis de ambiente

Ver `.env.example` na raiz. Grupos:

- **App**: `APP_ENV`, `APP_SECRET_KEY`, `APP_ENCRYPTION_KEY`, `APP_BASE_URL`, `LOG_LEVEL`
- **Banco/Redis**: `DATABASE_URL`, `REDIS_URL`
- **LLM**: `ANTHROPIC_API_KEY`, `LLM_MODEL_MAIN`, `LLM_MODEL_FAST`, `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`
- **Transcrição**: `TRANSCRIPTION_PROVIDER`, `OPENAI_API_KEY` ou `DEEPGRAM_API_KEY`
- **Google**: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`
- **Observabilidade**: `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`, `SENTRY_DSN`
- **Operação**: `ALERT_WEBHOOK_URL`, `DEFAULT_TIMEZONE`, `PHONE_HASH_PEPPER`

Credenciais de WhatsApp e Google **não** vão em env — são por tenant, criptografadas no banco.

## 5. CI/CD

GitHub Actions:

1. **PR**: lint, mypy, testes, `pip-audit`.
2. **Merge em `main`**: build da imagem, push para o registry, deploy em homologação, migrações, teste de fumaça.
3. **Tag `v*`**: deploy em produção com aprovação manual.

Migrações rodam como job separado antes do rollout da nova versão. Regra: **toda migração precisa ser compatível com a versão anterior do código** (adicionar coluna nullable, preencher, só depois tornar obrigatória em outra release). Sem isso, deploy vira downtime.

## 6. Backup e recuperação

- Postgres: backup diário automatizado, retenção 30 dias, cópia off-site.
- Teste de restauração trimestral, documentado.
- Redis é descartável, exceto pelos buffers em trânsito — perder o Redis pode custar mensagens não processadas. Por isso todo evento fica em `webhook_events` e há um comando `make reprocess-events --since` para recuperar.

## 7. Onboarding de um cliente novo (runbook)

Tempo alvo: meio dia de trabalho.

1. **Descoberta** (reunião de 1 h): ICP, oferta, objeções comuns, critérios de qualificação, quem são os vendedores, horários, o que o agente nunca pode dizer.
2. Criar `tenant` e `tenant_config` pelo painel.
3. Configurar `qualification_fields`, regras de desqualificação, gatilhos de handoff e cadência de follow-up.
4. Subir a base de conhecimento: site, materiais de venda, FAQ, tabela de preços (se o cliente autorizar), objeções e respostas. Validar a ingestão.
5. Escrever `company_description`, `offer_description`, `icp_description` e `custom_instructions`.
6. Cadastrar vendedores e conectar Google Agenda de cada um.
7. Configurar o canal WhatsApp (checklist em `docs/06` §7).
8. Rodar 10 conversas de teste manuais cobrindo os casos difíceis. Ajustar prompt.
9. Rodar o script de fumaça.
10. Apresentar ao cliente uma conversa de exemplo gravada, colher ajustes.
11. Ativar com volume reduzido (por exemplo, 20 % dos leads) por 3 dias, revisando todas as conversas.
12. Abrir 100 %. Revisão semanal no primeiro mês.

## 8. Operação semanal

- Revisar handoffs por motivo e alimentar a base de conhecimento com o que faltou.
- Revisar conversas com nota baixa na avaliação automática.
- Verificar custo por tenant e por conversa.
- Verificar quality rating dos números na Meta.
- Aplicar ajustes de prompt como nova versão, com os cenários de teste rodando antes.

## 9. Custos estimados (ordem de grandeza, revisar antes de precificar)

| Item | Base |
|---|---|
| LLM | por conversa, medido em `agent_runs` — alvo abaixo de R$ 0,60 |
| WhatsApp Cloud API | por conversa iniciada, varia por categoria; conversas iniciadas pelo usuário costumam ser mais baratas |
| Transcrição de áudio | por minuto |
| Infraestrutura | VPS + banco gerenciado, custo fixo diluído entre tenants |

Instrumentar tudo desde a Fase 2. Precificar sem saber o custo por conversa é como a agência perde margem em cliente de volume alto.
