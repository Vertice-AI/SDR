# 06 — Integração WhatsApp

## 1. Interface comum

`app/channels/base.py`:

```python
class ChannelAdapter(Protocol):
    provider: str

    async def verify_webhook(self, params, headers, body) -> bool: ...
    async def parse_inbound(self, payload: dict) -> list[InboundMessage]: ...
    async def send_text(self, to: str, text: str) -> SentMessage: ...
    async def send_typing(self, to: str, on: bool) -> None: ...
    async def send_template(self, to: str, name: str, params: list) -> SentMessage: ...
    async def send_buttons(self, to: str, text: str, buttons: list) -> SentMessage: ...
    async def download_media(self, media_id: str) -> bytes: ...
    async def mark_read(self, provider_message_id: str) -> None: ...
    def supports(self, capability: str) -> bool: ...
```

`InboundMessage` canônico:

```python
@dataclass
class InboundMessage:
    provider_message_id: str
    from_phone: str          # E.164 sempre COM "+" (normalizado no adaptador)
    to_phone: str
    profile_name: str | None
    content_type: Literal["text","audio","image","document","location","interactive","sticker","unknown"]
    text: str | None
    media_id: str | None
    media_mime: str | None
    timestamp: datetime      # sempre UTC
    context_message_id: str | None   # resposta a mensagem anterior
    referral: dict | None            # click-to-WhatsApp: campanha, anúncio
    raw: dict
```

Capacidades declaradas: `templates`, `buttons`, `lists`, `typing`, `read_receipts`, `audio_download`, `media_upload`.

---

## 2. Meta Cloud API (produção)

### Configuração
Por canal, em `channels.credentials_encrypted`:
`access_token` (permanente, de System User), `phone_number_id`, `waba_id`, `app_secret`, `api_version` (fixar `v21.0`).

### Webhook
`GET /webhooks/meta/{tenant_slug}` — verificação (`hub.mode`, `hub.verify_token`, `hub.challenge`).
`POST /webhooks/meta/{tenant_slug}` — eventos.

**Validação obrigatória** do header `X-Hub-Signature-256`: HMAC-SHA256 do corpo cru com o `app_secret`. Comparar com `hmac.compare_digest`. Assinatura inválida → 403 + log de segurança. É preciso guardar o corpo **cru** antes do parse JSON.

Um POST pode trazer várias mensagens e vários status. Iterar `entry[].changes[].value.messages[]` e `...statuses[]`.

**Status de entrega** (`sent`, `delivered`, `read`, `failed`) atualizam `messages.provider_status`. Falha recorrente com código de bloqueio → marcar `channels.status = 'banned'` e alertar.

### Janela de 24 horas
Só é possível enviar mensagem livre dentro de 24 h após a **última mensagem do lead**. Fora disso, apenas template aprovado.

Implementação:
- `conversations.within_24h_window_until` é atualizado a cada inbound (`last_inbound_at + 24h`).
- Antes de qualquer envio livre, checar. Fora da janela: usar template de reengajamento se existir; senão, `followups.status = 'skipped'` com `skip_reason = 'fora_janela_24h_sem_template'`.

### Templates
Cadastrar por tenant (aprovação da Meta leva de horas a dias). Mínimo recomendado:

| Nome | Categoria | Uso |
|---|---|---|
| `retomada_conversa` | MARKETING/UTILITY | follow-up fora da janela |
| `lembrete_reuniao_24h` | UTILITY | lembrete |
| `lembrete_reuniao_1h` | UTILITY | lembrete |
| `confirmacao_agendamento` | UTILITY | confirmação |

Guardar em `message_templates` (definida em `docs/03`). Nunca enviar template não aprovado — a API rejeita.

**Custo**: a Meta cobra por conversa iniciada, com preço diferente por categoria e país. Registrar em `agent_runs`/`conversations` para o custo por lead ficar visível.

### Limites
Rate limit por número e tier de mensagens (1k/10k/100k por dia, escalona com qualidade). Implementar rate limiter no Redis por `channel_id`, com fila e retry em 429. Monitorar a *quality rating* do número; queda de qualidade é sinal de conteúdo mal recebido.

---

## 3. Evolution API (desenvolvimento e PoC)

Self-hosted, baseada em Baileys (WhatsApp Web não oficial).

### Configuração
`base_url`, `api_key`, `instance_name`. Webhook configurado na instância apontando para `POST /webhooks/evolution/{tenant_slug}`. Autenticação por token no header (`apikey`), validado em tempo constante.

### Eventos relevantes
`messages.upsert` (entrada), `messages.update` (status), `connection.update` (queda/QR), `qrcode.updated`.

Ao receber `connection.update` com estado `close`: marcar `channels.status = 'disconnected'`, alertar imediatamente. Sem isso, o cliente fica sem atendimento e ninguém percebe.

### Diferenças e riscos
- **Sem templates.** Não há janela de 24 h, mas também não há garantia de entrega nem proteção contra bloqueio.
- **Risco de banimento** do número, principalmente com volume alto de mensagens ativas para contatos que nunca falaram com o número.
- Sessão pode cair e exigir novo QR.
- Não usar para outbound frio. Só inbound e continuidade de conversa.

**Regra de operação:** Evolution para dev, demonstração e homologação. Cliente pagante em produção vai para a Cloud API. Deixar isso claro em contrato.

---

## 4. Envio de mensagens

`app/channels/sender.py` centraliza:

1. Verifica opt-out do contato → aborta.
2. Verifica `channels.status` → se não `active`, enfileira e alerta.
3. Verifica janela de 24 h (só Meta).
4. Rate limit por canal.
5. Formata e divide o texto (`docs/04` §6).
6. Para cada parte: typing on → delay → envia → persiste `messages` → typing off.
7. Erro de envio: retry (2x, backoff) apenas em 5xx/429. Erro 4xx definitivo → grava `failed` com `error_detail` e alerta.

Toda mensagem enviada é persistida **antes** de considerar sucesso, com `provider_message_id` atualizado depois.

---

## 5. Click-to-WhatsApp (anúncios)

Mensagens vindas de anúncio trazem `referral` com `source_id`, `source_url`, `ctwa_clid`, `headline`, `body`. Gravar em `contacts.source_metadata` e definir `source = 'anuncio_meta'`.

Isso permite dizer ao cliente quanto cada campanha gerou de reunião marcada — é um dos argumentos de venda mais fortes do produto. Priorizar.

---

## 6. Áudio

1. `download_media(media_id)` — na Meta, exige duas chamadas (obter URL, depois baixar com o token).
2. Transcrever (provedor configurável: OpenAI Whisper ou Deepgram).
3. Salvar transcrição em `messages.content` e `transcription_confidence`.
4. Áudio maior que 5 minutos ou transcrição com confiança baixa: pedir que a pessoa escreva, sem culpá-la.
5. Não armazenar o arquivo de áudio além do necessário para transcrever (LGPD — ver `docs/09`).

---

## 7. Onboarding de um número novo (checklist operacional)

**Cloud API**
1. Meta Business verificado do cliente.
2. Criar/associar WABA e app.
3. Adicionar número (o número não pode estar ativo no app WhatsApp comum).
4. Verificar número, definir display name (passa por aprovação).
5. Gerar token permanente de System User com permissões `whatsapp_business_messaging` e `whatsapp_business_management`.
6. Configurar webhook e `verify_token`.
7. Submeter templates.
8. Enviar mensagem de teste ponta a ponta.
9. Registrar tudo em `channels` (criptografado) e rodar o cenário de fumaça.

**Evolution**
1. Subir instância, gerar QR, ler no celular do número.
2. Configurar webhook e apikey.
3. Testar entrada e saída.
4. Documentar quem tem acesso ao celular — a sessão depende dele.
