# 01 — Produto e Escopo

## 1. Problema

Empresas B2B e serviços de ticket médio-alto no Brasil recebem leads pelo WhatsApp e perdem a maioria por três motivos:

1. **Demora na primeira resposta.** Lead respondido em até 5 minutos converte muito mais que lead respondido em horas. Fora do horário comercial, ninguém responde.
2. **Vendedor gastando tempo com lead ruim.** Boa parte do tempo do time comercial vai para curioso, estudante, concorrente e gente sem orçamento.
3. **Agenda que não fecha.** O lead demonstra interesse, o vendedor manda link, o lead some. Cada etapa fora da conversa derruba a taxa.

## 2. Solução

Um agente de pré-vendas que atende no WhatsApp 24/7, conduz a conversa como um SDR humano bem treinado, qualifica, tira dúvidas com base na documentação real do cliente e agenda a reunião no calendário do vendedor sem sair da conversa.

**Promessa comercial da Vertice ao cliente final:** primeira resposta em menos de 30 segundos, qualificação padronizada de 100% dos leads e reunião marcada dentro do WhatsApp.

## 3. Personas

**Lead (quem conversa com o agente)**
Contato que chegou por anúncio, site, indicação ou lista. Escreve informalmente, em rajada, com áudio, com erro de digitação. Pode ser decisor ou não. Espera resposta rápida e objetiva. Detesta sentir que fala com robô burro — mas aceita bem falar com IA se ela for útil.

**Vendedor / closer (cliente do cliente)**
Quer receber só reunião com lead qualificado, com contexto pronto. Não quer abrir mais um sistema. Precisa poder assumir a conversa a qualquer momento.

**Gestor comercial (comprador do serviço)**
Quer ver volume de leads, taxa de qualificação, reuniões marcadas e no-show. Quer ajustar o discurso do agente sem depender da agência.

**Vertice (nós, operadores)**
Precisamos subir um cliente novo em poucas horas: número, prompt, base de conhecimento, agenda, testar e publicar. Sem tocar em código.

## 4. Escopo funcional — v1

### 4.1 Atendimento
- Receber mensagens de texto, áudio (transcrever) e imagem (descrever/ignorar conforme config).
- Agrupar rajada de mensagens em um único turno.
- Responder em linguagem natural, tom configurável por tenant.
- Manter contexto da conversa inteira, com resumo automático quando ficar longa.
- Reconhecer lead que volta depois de dias e retomar de onde parou.

### 4.2 Qualificação
- Coletar, de forma conversacional (nunca em formato de formulário), os campos definidos pelo tenant.
- Framework padrão BANT adaptado: necessidade/dor, urgência, orçamento/porte, autoridade de decisão.
- Calcular score e classificar em **quente / morno / frio / desqualificado**.
- Desqualificar educadamente quem está fora do ICP, com resposta configurável.

### 4.3 Dúvidas
- Responder com base na base de conhecimento do tenant (RAG).
- Assumir que não sabe quando não encontrar resposta, e escalar.
- Nunca inventar preço, prazo ou condição comercial.

### 4.4 Agendamento
- Consultar disponibilidade real do vendedor.
- Propor até 3 horários por vez, respeitando janela comercial, antecedência mínima e buffer entre reuniões.
- Criar evento com Google Meet, convidando lead e vendedor.
- Confirmar por mensagem, enviar lembrete 24 h e 1 h antes.
- Reagendar e cancelar pela conversa.

### 4.5 Handoff
- Escalar para humano por: pedido explícito do lead, dúvida sem resposta, sinal de irritação, tema sensível (jurídico, reclamação, cobrança), lead muito quente com pedido de proposta.
- Ao escalar, pausar o agente naquela conversa e notificar o time (WhatsApp/Slack/e-mail/webhook).
- Retomada manual pelo painel.

### 4.6 Follow-up
- Cadência configurável para lead que parou de responder (ex.: +1 h, +1 dia, +3 dias, +7 dias).
- Máximo de tentativas configurável. Encerrar educadamente ao esgotar.
- Respeitar janela de 24 h da Meta (usar template aprovado quando fora dela).
- Parar imediatamente com opt-out.

### 4.7 Painel administrativo (mínimo viável na v1)
- CRUD de tenant, canal, configuração e vendedores.
- Editor do prompt e dos critérios de qualificação com pré-visualização.
- Upload/gestão da base de conhecimento.
- Inbox de conversas com transcrição e botão "assumir conversa".
- Dashboard: leads, taxa de qualificação, reuniões marcadas, custo de LLM.

## 5. Fora de escopo na v1

- Negociação de preço e envio de proposta.
- Fechamento de venda / cobrança.
- Voz (ligação). Áudio só como entrada transcrita.
- Canais além do WhatsApp (Instagram DM e webchat ficam para v2, mas a abstração `ChannelAdapter` já prevê).
- Painel white-label para o cliente final personalizar visualmente.
- Treinamento/fine-tuning de modelo.

## 6. Métricas de sucesso

| Métrica | Alvo v1 |
|---|---|
| Tempo até a primeira resposta | < 30 s |
| Conversas atendidas sem intervenção humana | > 70 % |
| Leads com qualificação completa | > 80 % dos que responderam 3+ mensagens |
| Reuniões marcadas / leads qualificados | > 35 % |
| No-show nas reuniões marcadas pelo agente | < 25 % |
| Taxa de escalonamento por "não sei responder" | < 10 % |
| Custo de LLM por conversa | < R$ 0,60 |
| Reclamação de lead achando a conversa ruim | ~ 0 |

Todas devem ser instrumentadas desde a Fase 2. Ver `docs/10-observabilidade-e-testes.md`.

## 7. Modelo de entrega da Vertice

- **Setup**: implantação, configuração do número, base de conhecimento, treinamento do agente, integração com a agenda e o CRM do cliente.
- **Mensalidade**: operação, ajustes de prompt, suporte e infraestrutura.
- Precificação sugerida por faixa de volume de conversas/mês, com o custo de LLM e de conversa da Meta como custo variável repassado ou embutido. Rastrear custo por tenant é requisito de produto, não só de engenharia.
