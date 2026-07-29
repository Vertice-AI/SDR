# 09 — Segurança, LGPD e Guardrails

## 1. Guardrails de entrada

Executados antes de chamar o LLM, em `app/agent/guardrails.py`:

| Verificação | Ação |
|---|---|
| Opt-out detectado | Curto-circuito: confirma e encerra, sem chamar o LLM |
| Tentativa de prompt injection | Não bloqueia a conversa; envolve o texto do lead em delimitador claro e registra flag. O prompt de sistema já instrui a ignorar |
| Mensagem gigante (> 4000 caracteres) | Trunca e registra |
| Flood (> 20 mensagens em 60 s) | Rate limit por contato; responde uma vez pedindo calma e para de processar |
| Mídia não suportada | Resposta padrão, sem chamar o LLM |
| Conteúdo ilegal/abusivo grave | Encerra, registra, notifica o gestor |

**Delimitação de conteúdo do usuário:** o texto do lead nunca é concatenado dentro de instruções. Vai sempre como `role: user`, e qualquer conteúdo recuperado do RAG entra marcado como referência, não como instrução.

## 2. Guardrails de saída

Executados sobre o texto gerado, antes do envio:

| Verificação | Ação |
|---|---|
| Valor monetário não presente no contexto recuperado | **Bloqueia**, regenera uma vez com aviso; persistindo, escala |
| Promessa de resultado ("garanto", "com certeza você vai") | Bloqueia e regenera |
| Menção a desconto/condição especial | Bloqueia e escala |
| Vazamento do prompt de sistema | Bloqueia, resposta padrão, alerta de segurança |
| Tema proibido do tenant | Bloqueia e escala |
| Mais de uma pergunta na mensagem | Flag (não bloqueia), registra para ajuste de prompt |
| Resposta vazia ou só pontuação | Regenera; falhando, escala |
| Dado pessoal de outro lead | Bloqueia e alerta — indica falha grave de isolamento |

Toda ativação vai para `agent_runs.guardrail_flags` e vira métrica. Guardrail que dispara muito é sintoma de prompt ruim, não de lead difícil.

## 3. Prompt injection

O lead é uma pessoa desconhecida e pode tentar manipular o agente. Defesas em camada:

1. Instrução explícita no prompt de sistema (ver `docs/05`).
2. Separação estrita entre instrução (system) e dado (user/tool result).
3. Ferramentas com efeito colateral só disponíveis no estado correto — o LLM não consegue chamar `agendar_reuniao` em `abertura`, mesmo se instruído.
4. Toda ferramenta valida seus próprios parâmetros contra o banco. `agendar_reuniao` revalida o slot; `registrar_qualificacao` valida o campo contra a configuração do tenant.
5. Guardrail de saída contra vazamento de prompt.

Nenhuma ferramenta executa comando de sistema, SQL livre, chamada HTTP arbitrária ou leitura de arquivo. Isso não é negociável.

## 4. LGPD

### Base legal
- **Inbound** (lead escreveu primeiro): legítimo interesse / execução de tratativas pré-contratuais.
- **Outbound** (lista importada): exige consentimento ou base legal demonstrável do cliente. Contratualmente, a responsabilidade pela origem da lista é do cliente, e isso deve estar no contrato de prestação de serviço.
- Registrar tudo em `consents` com evidência.

### Papéis
O cliente é **controlador**; a Vertice é **operadora**. É preciso contrato de operador (DPA) com cada cliente, definindo finalidade, prazo de retenção, subprocessadores (Anthropic, Meta, Google, provedor de transcrição, hospedagem) e procedimento em caso de incidente.

### Aviso ao titular
Na primeira mensagem, deixar claro que é um assistente virtual e que a conversa é registrada. Uma linha, sem juridiquês. Exemplo: *"Sou o assistente virtual da {empresa} — nossa conversa fica registrada para o time comercial."*

### Direitos do titular
Endpoints administrativos e procedimento documentado para:
- **Acesso/portabilidade**: exportar tudo do contato em JSON.
- **Eliminação**: anonimizar (`contacts` com telefone/nome/e-mail substituídos por hash, mensagens apagadas), preservando dados agregados sem identificação.
- **Revogação**: opt-out imediato.
Prazo de atendimento: 15 dias. Toda operação registrada em `audit_logs`.

### Retenção
| Dado | Prazo |
|---|---|
| Mensagens e conversas | 24 meses, depois anonimizar |
| `webhook_events` (payload cru) | 30 dias |
| Arquivos de áudio | apagar após a transcrição |
| Logs de aplicação | 90 dias |
| `audit_logs` | 5 anos |
| Dados de lead desqualificado | 12 meses |

Jobs de expurgo automáticos, com teste.

### Dados sensíveis
O agente não deve coletar CPF, dados de saúde, dados financeiros pessoais, biometria ou origem racial. Se o lead informar espontaneamente, não registrar em campo estruturado e escalar quando for relevante.

## 5. Segurança da aplicação

- **Segredos**: nunca em código nem em log. `.env` local, gerenciador de segredos em produção. Segredos por tenant criptografados em repouso (AES-GCM, chave em `APP_ENCRYPTION_KEY`, rotação documentada).
- **Autenticação do painel**: JWT curto + refresh, senha com argon2, MFA obrigatório para `superadmin`.
- **Autorização**: toda rota administrativa valida papel **e** tenant. Teste de autorização por rota é obrigatório.
- **Webhooks**: validação de assinatura sempre; comparação em tempo constante.
- **Rate limit**: por IP nos endpoints públicos, por contato no fluxo de conversa, por tenant nas rotas administrativas.
- **Isolamento entre tenants**: RLS + repositórios com tenant + teste automatizado de vazamento (`tests/integration/test_tenant_isolation.py`).
- **Dependências**: `pip-audit` no CI; atualização mensal.
- **Backup**: diário do Postgres com retenção de 30 dias e **restauração testada trimestralmente**. Backup não testado não é backup.

## 6. Logging seguro

`app/core/logging.py` — structlog em JSON com processador de redação:

- Telefone: só os 4 últimos dígitos + `phone_hash`.
- Conteúdo de mensagem: **nunca** em log de aplicação. Fica no banco, protegido por RLS, e no Langfuse (que precisa estar configurado com retenção curta e acesso restrito).
- E-mail: mascarado (`j***@empresa.com`).
- Tokens, chaves, headers de autorização: redigidos.
- Todo log carrega `tenant_id`, `conversation_id`, `turn_id`, `trace_id`.

Teste automatizado que grava logs de um turno completo e falha se encontrar telefone completo ou conteúdo de mensagem.

## 7. Incidentes

Plano mínimo documentado: detecção → contenção (pausar tenant afetado) → avaliação → notificação ao cliente em até 24 h e à ANPD quando aplicável → correção → post-mortem.

Alertas que exigem ação imediata: canal desconectado, taxa de erro de LLM acima de 5 %, guardrail de vazamento de dado entre tenants, fila de workers acima de 100 itens, queda de quality rating do número na Meta.
