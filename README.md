# sdr-agent

Agente de IA de pré-vendas (SDR) para WhatsApp. Qualifica leads, responde dúvidas com base na documentação do cliente e agenda reuniões direto na agenda do vendedor — sem intervenção humana.

Produto multi-tenant da **Vertice Consulting**: uma base atende vários clientes, cada um com seu número, prompt, ICP, base de conhecimento e agenda.

## Stack

Python 3.12 · FastAPI · PostgreSQL 16 + pgvector · Redis · ARQ · Claude (Anthropic) · WhatsApp Cloud API / Evolution API · Google Calendar

## Começando

```bash
cp .env.example .env     # preencha as chaves
make setup               # sobe containers, instala deps, roda migrações
make seed                # cria tenant de demonstração
make dev                 # API em http://localhost:8000
make worker              # em outro terminal
```

## Documentação

Comece por **[`CLAUDE.md`](CLAUDE.md)** — contexto completo, stack, convenções e regras invioláveis.

Depois, **[`docs/11-roadmap-e-backlog.md`](docs/11-roadmap-e-backlog.md)** — as fases de desenvolvimento em ordem, com critérios de aceite.

| Documento | Conteúdo |
|---|---|
| [01](docs/01-produto-e-escopo.md) | Produto, personas, escopo, métricas |
| [02](docs/02-arquitetura.md) | Arquitetura e decisões técnicas |
| [03](docs/03-modelo-de-dados.md) | Schema do banco |
| [04](docs/04-motor-de-conversa.md) | Buffer, estados, loop do agente, ferramentas |
| [05](docs/05-prompts.md) | Prompts |
| [06](docs/06-integracao-whatsapp.md) | WhatsApp |
| [07](docs/07-integracao-agenda.md) | Google Calendar |
| [08](docs/08-qualificacao-e-handoff.md) | Qualificação, handoff, follow-up |
| [09](docs/09-seguranca-lgpd-guardrails.md) | Segurança, LGPD, guardrails |
| [10](docs/10-observabilidade-e-testes.md) | Métricas e testes |
| [12](docs/12-deploy-e-infra.md) | Deploy, infra, onboarding de cliente |

## Status

Fase 0 (Fundação) concluída. Desenvolvimento na **Fase 1 — Dados e multi-tenancy**.
