# 10 — Observabilidade e Testes

## 1. Métricas de produto (por tenant, no dashboard)

| Métrica | Como calcular |
|---|---|
| Conversas iniciadas | conversas com ≥ 1 inbound no período |
| Tempo até a 1ª resposta | p50/p95 de `first_outbound_at - first_inbound_at` |
| Taxa de resposta do lead | conversas com ≥ 2 mensagens do lead / total |
| Taxa de qualificação completa | qualificações com todos os campos obrigatórios / conversas com ≥ 3 inbounds |
| Distribuição de score | histograma de `qualifications.score` |
| Reuniões marcadas | `appointments` criados |
| Conversão qualificado → reunião | reuniões / leads `hot`+`warm` |
| No-show | `no_show` / reuniões passadas |
| Taxa de handoff | handoffs / conversas, quebrada por motivo |
| Taxa de opt-out | opt-outs / conversas |
| Custo de LLM por conversa | `SUM(agent_runs.cost_cents) / conversas` |
| Turnos por conversa | média de `agent_runs` por conversa |

Handoff por motivo é a métrica mais acionável: um pico em `sem_resposta_na_base` significa que falta conteúdo na base de conhecimento daquele cliente — e é uma oportunidade de melhoria concreta para mostrar na reunião mensal.

## 2. Métricas técnicas (Prometheus)

- `webhook_received_total{provider,tenant}`, `webhook_duration_seconds`
- `turn_processing_duration_seconds{tenant}` (histograma)
- `llm_request_duration_seconds{model}`, `llm_tokens_total{model,type}`, `llm_errors_total{model,type}`
- `tool_calls_total{tool,status}`, `tool_duration_seconds{tool}`
- `guardrail_triggered_total{rule}`
- `message_send_total{provider,status}`
- `queue_depth{queue}`, `queue_wait_seconds`
- `channel_status{tenant,channel}` (gauge 1/0)

## 3. Traces (Langfuse)

Um trace por turno, contendo: prompt renderizado (com variáveis), mensagens de contexto, cada chamada de LLM com tokens e custo, cada tool call com entrada e saída, guardrails disparados, resposta final. Tags: `tenant`, `state`, `model`, `prompt_version`.

Isso é o que permite responder "por que o agente respondeu isso?" quando o cliente reclamar — e vai acontecer.

Atenção: o trace contém conteúdo de conversa. Configurar retenção curta (30 dias), acesso restrito e mencionar o Langfuse como subprocessador no DPA.

## 4. Alertas

| Condição | Severidade |
|---|---|
| Canal desconectado / banido | crítico |
| Taxa de erro de LLM > 5 % em 5 min | crítico |
| Fila com > 100 itens ou espera > 60 s | crítico |
| Guardrail de dado entre tenants | crítico |
| p95 do turno > 45 s | alto |
| Handoff sem ser assumido além do SLA | alto |
| Custo diário de um tenant acima de 2x a média | médio |
| Documento da base falhou na ingestão | médio |

Destino: Slack/WhatsApp do time da Vertice.

## 5. Estratégia de testes

### 5.1 Unitários (`tests/unit/`)
Regras puras, sem I/O: cálculo de score, classificação, geração de slots, formatação e split de mensagem, debounce (com relógio falso), parsing de payload de cada provedor, guardrails, redação de log.

### 5.2 Integração (`tests/integration/`)
Postgres e Redis reais via testcontainers. APIs externas mockadas (respx/VCR).
Cobertura obrigatória:
- Isolamento entre tenants (RLS + repositórios).
- Idempotência de webhook: mesmo evento duas vezes → uma mensagem só.
- Lock de conversa: dois turnos simultâneos → um processa, outro reagenda.
- Debounce: 5 mensagens em 3 s → um `process_turn`.
- Reserva de slot: duas conversas disputando o mesmo horário.
- Follow-up respeitando janela de 24 h e horário comercial.
- Opt-out bloqueando envio em todos os caminhos.

### 5.3 Cenários de conversa (`tests/conversations/`)
O teste mais valioso do projeto. Cada cenário é um YAML com as falas do lead e as asserções esperadas:

```yaml
nome: lead_pergunta_preco_fora_da_base
tenant: fixture_padrao
turnos:
  - lead: "oi, vi o anúncio de vocês"
    espera:
      - nao_contem: ["R$", "reais", "custa"]
      - chamou_ferramenta_ou_nao: {buscar_conhecimento: false}
  - lead: "quanto custa o serviço de vocês?"
    espera:
      - chamou_ferramenta: buscar_conhecimento
      - chamou_ferramenta: escalar_para_humano
      - nao_contem_valor_monetario: true
      - estado_final: handoff_humano
```

Modos de execução:
- **`replay`** (padrão no CI): respostas de LLM gravadas. Rápido, determinístico, sem custo. Valida orquestração, estados, ferramentas e guardrails.
- **`live`** (nightly / antes de release): chama o modelo de verdade, com um LLM juiz avaliando aderência de tom e cumprimento das regras. Aceita variação de texto, não de comportamento.

Mínimo de 25 cenários cobrindo a tabela de casos difíceis de `docs/04` §8.

### 5.4 Carga
Simular 200 conversas simultâneas com rajada de mensagens. Verificar: ack de webhook < 300 ms, profundidade da fila estável, nenhuma resposta duplicada, nenhum deadlock.

### 5.5 Antes de subir cliente novo
Checklist de fumaça, executável por script: webhook responde, mensagem de teste ida e volta, base de conhecimento retorna resultado, `freebusy` responde, agendamento cria evento real em calendário de teste, handoff notifica, opt-out bloqueia.

## 6. CI

Em cada PR: `ruff check` → `ruff format --check` → `mypy --strict` → `pytest unit` → `pytest integration` → `pytest conversations` (modo replay) → `pip-audit`.
Cobertura mínima: 80 % geral, **95 % em `app/agent/` e `app/channels/`**.

Nightly: cenários em modo `live` contra um tenant de teste, com relatório de custo.

## 7. Avaliação contínua da qualidade

- Amostrar 20 conversas por semana por tenant e avaliar com LLM juiz: seguiu as regras, tom adequado, perguntou uma coisa por vez, não inventou informação, avançou a conversa.
- Registrar as notas e acompanhar a evolução por versão de prompt.
- Toda reclamação real de cliente vira um cenário novo em `tests/conversations/`. Sem exceção — é assim que a qualidade cresce em vez de oscilar.
