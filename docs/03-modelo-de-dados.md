# 03 — Modelo de Dados

PostgreSQL 16 com extensões `pgcrypto`, `pg_trgm`, `unaccent` e `vector`.

Convenções:

- PK `id UUID` default `gen_random_uuid()`.
- `created_at`/`updated_at` `TIMESTAMPTZ NOT NULL DEFAULT now()`.
- Toda tabela de negócio: `tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE`.
- Todo índice de consulta começa por `tenant_id`.
- Soft delete só onde indicado (`deleted_at`).
- Campos com segredo têm sufixo `_encrypted` (bytea, AES-GCM na aplicação com `APP_ENCRYPTION_KEY`).

---

## 1. Tenancy e configuração

### `tenants`
| coluna | tipo | notas |
|---|---|---|
| id | uuid PK | |
| slug | text UNIQUE | usado na URL do webhook |
| name | text | razão social / nome do cliente |
| status | text | `active`, `paused`, `churned` |
| timezone | text | default `America/Sao_Paulo` |
| plan | text | faixa contratada |
| monthly_conversation_limit | int | 0 = ilimitado |
| created_at, updated_at | timestamptz | |

### `tenant_configs`
Configuração viva do agente. Versionada para permitir rollback de prompt.

| coluna | tipo | notas |
|---|---|---|
| id | uuid PK | |
| tenant_id | uuid | |
| version | int | incremental |
| is_active | bool | apenas uma ativa por tenant |
| agent_name | text | como o agente se apresenta |
| company_description | text | vai para o prompt |
| offer_description | text | o que a empresa vende |
| icp_description | text | perfil de cliente ideal |
| tone | text | `consultivo`, `direto`, `informal`, `formal` |
| language | text | default `pt-BR` |
| custom_instructions | text | livre, do gestor |
| forbidden_topics | jsonb | lista de temas proibidos |
| qualification_fields | jsonb | ver §4 |
| disqualification_rules | jsonb | condições e resposta |
| handoff_rules | jsonb | gatilhos e destino |
| followup_cadence | jsonb | lista de offsets em minutos |
| max_followups | int | default 4 |
| debounce_seconds | int | default 8 |
| business_hours | jsonb | por dia da semana |
| out_of_hours_behavior | text | `responder`, `avisar_e_responder`, `so_avisar` |
| scheduling_threshold | int | score mínimo para ir a agendamento, default 45 |
| classification_bands | jsonb | faixas de `hot`/`warm`/`cold`, default `{"hot":70,"warm":45,"cold":20}` |
| handoff_sla_minutes | int | tempo até escalar o alerta, default 15 |
| handoff_transition_message | text | frase dita ao lead ao escalar |
| seller_assignment_mode | text | `single`, `round_robin`, `by_rule` |
| enable_vision | bool | interpretar imagens recebidas, default false |
| enable_audio_transcription | bool | default true |
| created_by, created_at | | auditoria |

### `channels`
Um número de WhatsApp.

| coluna | tipo | notas |
|---|---|---|
| id | uuid PK | |
| tenant_id | uuid | |
| provider | text | `meta_cloud`, `evolution` |
| phone_number | text | E.164 |
| display_name | text | |
| status | text | `active`, `disconnected`, `banned` |
| credentials_encrypted | bytea | token, phone_number_id, waba_id, apikey, base_url |
| webhook_verify_token_encrypted | bytea | |
| capabilities | jsonb | `{"templates": true, "buttons": true, "audio": true}` |

UNIQUE `(provider, phone_number)`.

### `users`
Operadores: equipe da Vertice e do cliente.

| coluna | tipo | notas |
|---|---|---|
| id, tenant_id | | `tenant_id` nulo = superadmin Vertice |
| email | text UNIQUE | |
| password_hash | text | argon2 |
| role | text | `superadmin`, `admin`, `manager`, `seller` |
| name, phone | text | |
| is_active | bool | |

### `sellers`
Vendedor que recebe as reuniões. Pode ou não ter login.

| coluna | tipo | notas |
|---|---|---|
| id, tenant_id | | |
| user_id | uuid null | |
| name, email, phone | text | |
| calendar_provider | text | `google`, `none` |
| calendar_credentials_encrypted | bytea | refresh token OAuth |
| calendar_id | text | default `primary` |
| timezone | text | |
| availability_rules | jsonb | ver `docs/07` |
| round_robin_weight | int | default 1 |
| is_active | bool | |

---

## 2. Conversa

### `contacts` (leads)
| coluna | tipo | notas |
|---|---|---|
| id, tenant_id | | |
| phone_e164 | text | |
| phone_hash | text | sha256 com pepper, usado em log |
| name | text | nome do WhatsApp ou informado |
| email | text null | |
| company | text null | |
| role_title | text null | |
| source | text | `anuncio_meta`, `site`, `indicacao`, `lista`, `desconhecido` |
| source_metadata | jsonb | ctwa_clid, campanha, utm |
| tags | text[] | |
| opted_out_at | timestamptz null | |
| first_contact_at, last_contact_at | timestamptz | |
| crm_external_id | text null | |

UNIQUE `(tenant_id, phone_e164)`.

### `conversations`
| coluna | tipo | notas |
|---|---|---|
| id, tenant_id | | |
| contact_id, channel_id | uuid | |
| status | text | `active`, `awaiting_lead`, `human_handoff`, `scheduled`, `disqualified`, `closed`, `opted_out` |
| state | text | estado da máquina — ver `docs/04` |
| assigned_seller_id | uuid null | |
| summary | text null | resumo rolante |
| summary_updated_at_message_id | uuid null | |
| last_inbound_at, last_outbound_at | timestamptz | |
| within_24h_window_until | timestamptz null | controle da janela Meta |
| followup_count | int | |
| next_followup_at | timestamptz null | |
| paused_until | timestamptz null | pausa automática após handoff |
| closed_reason | text null | |
| llm_cost_cents | numeric(10,4) | acumulado |

Índices: `(tenant_id, status)`, `(tenant_id, next_followup_at) WHERE next_followup_at IS NOT NULL`, `(tenant_id, contact_id)`.

### `messages`
| coluna | tipo | notas |
|---|---|---|
| id, tenant_id | | |
| conversation_id | uuid | |
| direction | text | `inbound`, `outbound` |
| sender_type | text | `lead`, `agent`, `human` |
| sender_user_id | uuid null | quando `human` |
| content_type | text | `text`, `audio`, `image`, `document`, `location`, `template`, `system` |
| content | text | texto ou transcrição |
| media_url, media_mime | text null | |
| transcription_confidence | numeric null | |
| provider_message_id | text null | |
| provider_status | text | `queued`, `sent`, `delivered`, `read`, `failed` |
| error_detail | text null | |
| turn_id | uuid null | agrupa mensagens do mesmo turno |
| created_at | timestamptz | |

UNIQUE `(tenant_id, provider_message_id)` onde não nulo.
Índice `(conversation_id, created_at)`.

### `message_templates`
Templates HSM aprovados na Meta. Só usados pelo `MetaCloudAdapter`.

| coluna | tipo | notas |
|---|---|---|
| id, tenant_id, channel_id | | |
| name | text | nome aprovado na Meta |
| language | text | `pt_BR` |
| category | text | `UTILITY`, `MARKETING`, `AUTHENTICATION` |
| body | text | corpo com placeholders `{{1}}` |
| variables | jsonb | descrição de cada variável |
| purpose | text | `retomada_conversa`, `lembrete_24h`, `lembrete_1h`, `confirmacao` |
| status | text | `pending`, `approved`, `rejected`, `paused` |
| rejection_reason | text null | |

UNIQUE `(tenant_id, channel_id, name, language)`.

### `webhook_events`
| coluna | tipo | notas |
|---|---|---|
| id, tenant_id | | tenant pode ser nulo se não resolvido |
| provider | text | |
| event_type | text | |
| payload | jsonb | cru |
| signature_valid | bool | |
| processed_at | timestamptz null | |
| processing_error | text null | |

Retenção: 30 dias (job de limpeza).

---

## 3. Qualificação e agendamento

### `qualifications`
Um registro por conversa, atualizado incrementalmente.

| coluna | tipo | notas |
|---|---|---|
| id, tenant_id, conversation_id | | UNIQUE em conversation_id |
| answers | jsonb | `{"campo": {"value": ..., "confidence": 0.9, "captured_at": ...}}` |
| score | int | 0–100 |
| classification | text | `hot`, `warm`, `cold`, `disqualified` |
| disqualification_reason | text null | |
| completed_at | timestamptz null | |

### `appointments`
| coluna | tipo | notas |
|---|---|---|
| id, tenant_id, conversation_id, contact_id, seller_id | | |
| status | text | `scheduled`, `rescheduled`, `cancelled`, `completed`, `no_show` |
| starts_at, ends_at | timestamptz | |
| timezone | text | |
| meeting_url | text null | Google Meet |
| calendar_event_id | text null | |
| reminder_24h_sent_at, reminder_1h_sent_at | timestamptz null | |
| cancelled_reason | text null | |
| rescheduled_from_id | uuid null | |

Índices: `(tenant_id, starts_at)`, `(seller_id, starts_at)`.

### `handoffs`
| coluna | tipo | notas |
|---|---|---|
| id, tenant_id, conversation_id | | |
| reason | text | `lead_pediu`, `sem_resposta_na_base`, `irritacao`, `tema_sensivel`, `lead_quente`, `manual`, `erro_tecnico` |
| trigger_message_id | uuid null | |
| notified_channels | jsonb | |
| assumed_by_user_id | uuid null | |
| assumed_at, resolved_at | timestamptz null | |
| resolution_note | text null | |

### `followups`
| coluna | tipo | notas |
|---|---|---|
| id, tenant_id, conversation_id | | |
| attempt_number | int | |
| scheduled_for | timestamptz | |
| sent_at | timestamptz null | |
| status | text | `pending`, `sent`, `skipped`, `cancelled` |
| skip_reason | text null | ex.: `fora_janela_24h_sem_template` |
| message_id | uuid null | |

---

## 4. Base de conhecimento

### `knowledge_documents`
| coluna | tipo | notas |
|---|---|---|
| id, tenant_id | | |
| title | text | |
| source_type | text | `upload`, `url`, `manual`, `faq` |
| source_ref | text | nome do arquivo ou URL |
| content_hash | text | evita reprocessar igual |
| status | text | `pending`, `processing`, `ready`, `failed` |
| chunk_count | int | |
| error | text null | |

### `knowledge_chunks`
| coluna | tipo | notas |
|---|---|---|
| id, tenant_id, document_id | | |
| chunk_index | int | |
| content | text | |
| content_tsv | tsvector | gerado, `portuguese` + unaccent |
| embedding | vector(1024) | modelo definido em config |
| metadata | jsonb | seção, página |

Índices: HNSW em `embedding`, GIN em `content_tsv`, ambos com `tenant_id` no filtro da query.

### `faq_entries`
Perguntas e respostas curadas, com prioridade sobre o RAG.

| coluna | tipo | notas |
|---|---|---|
| id, tenant_id | | |
| question, answer | text | |
| variations | text[] | |
| embedding | vector(1024) | |
| is_active | bool | |

---

## 5. Operação e auditoria

### `agent_runs`
Um registro por turno processado. Base do custo e da depuração.

| coluna | tipo | notas |
|---|---|---|
| id, tenant_id, conversation_id | | |
| turn_id | uuid | |
| model | text | |
| input_tokens, output_tokens, cached_tokens | int | |
| cost_cents | numeric(10,4) | |
| latency_ms | int | |
| iterations | int | voltas no loop de tool calling |
| tools_called | jsonb | |
| state_before, state_after | text | |
| guardrail_flags | jsonb | |
| error | text null | |
| trace_id | text null | Langfuse |

### `consents`
| coluna | tipo | notas |
|---|---|---|
| id, tenant_id, contact_id | | |
| type | text | `whatsapp_contact`, `data_processing` |
| granted | bool | |
| source | text | `optin_form`, `inbound_message`, `imported_list` |
| evidence | jsonb | |
| occurred_at | timestamptz | |

### `audit_logs`
Ações de operadores: mudança de config, assumir conversa, exportar dados, apagar lead.

| coluna | tipo | notas |
|---|---|---|
| id, tenant_id, user_id | | |
| action, entity_type, entity_id | text | |
| diff | jsonb | |
| ip, user_agent | text | |

### `crm_sync_log`
| coluna | tipo | notas |
|---|---|---|
| id, tenant_id, conversation_id | | |
| provider | text | |
| operation | text | |
| status | text | `success`, `failed` |
| request, response | jsonb | |
| attempts | int | |

---

## 6. Row Level Security

Habilitar RLS em todas as tabelas com `tenant_id`. Política padrão:

```sql
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON conversations
  USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
```

A aplicação executa `SET LOCAL app.tenant_id = '<uuid>'` no início de cada transação, via middleware/dependência. O usuário de migração tem `BYPASSRLS`; o usuário da aplicação **não**.

Teste obrigatório em `tests/integration/test_tenant_isolation.py`: com o contexto do tenant A, nenhuma query retorna linha do tenant B — mesmo passando o id explicitamente.

---

## 7. Estrutura de `qualification_fields`

```json
[
  {
    "key": "dor_principal",
    "label": "Principal dor",
    "type": "text",
    "required": true,
    "weight": 30,
    "question_hint": "Descobrir o problema concreto que motivou o contato",
    "scoring": {"has_value": 30}
  },
  {
    "key": "faturamento_mensal",
    "label": "Faturamento mensal",
    "type": "enum",
    "options": ["ate_50k", "50k_200k", "200k_1m", "acima_1m"],
    "required": true,
    "weight": 30,
    "scoring": {"ate_50k": 0, "50k_200k": 15, "200k_1m": 30, "acima_1m": 30}
  },
  {
    "key": "decisor",
    "label": "É o decisor",
    "type": "enum",
    "options": ["sim", "influencia", "nao"],
    "required": true,
    "weight": 20,
    "scoring": {"sim": 20, "influencia": 12, "nao": 3}
  },
  {
    "key": "urgencia",
    "label": "Urgência",
    "type": "enum",
    "options": ["imediata", "3_meses", "sem_prazo"],
    "required": false,
    "weight": 20,
    "scoring": {"imediata": 20, "3_meses": 12, "sem_prazo": 4}
  }
]
```

Score = soma dos pontos. Classificação padrão: ≥ 70 `hot`, 45–69 `warm`, 20–44 `cold`, < 20 ou regra de desqualificação disparada → `disqualified`. Faixas configuráveis por tenant.
