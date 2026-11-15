# Configuração do WhatsApp Business Cloud API (oficial da Meta)

O Corpo Sano usa **somente** a Cloud API oficial (Graph API). Não há automação de WhatsApp Web.
Se a integração estiver desativada ou indisponível, todos os módulos continuam funcionando.

## 1. Na Meta (developers.facebook.com / business.facebook.com)

1. Crie (ou use) o **Portfólio empresarial** da clínica e verifique a empresa.
2. Crie um **App** do tipo *Business* e adicione o produto **WhatsApp**.
3. Registre o número comercial (não pode estar ativo no aplicativo WhatsApp comum).
4. Anote: **Meta Business ID**, **WhatsApp Business Account ID (WABA)** e **Phone Number ID**.
5. Crie um **usuário do sistema** com permissões `whatsapp_business_messaging` e
   `whatsapp_business_management` e gere um **token permanente**.
6. Em *Configurações do app › Básico*, copie o **App Secret** (usado para validar a assinatura do webhook).
7. Crie os **templates** no Gerenciador do WhatsApp e aguarde aprovação, por exemplo:
   - `confirmacao_agendamento` (UTILITY): "Olá {{1}}, seu horário na {{2}} está confirmado para {{3}} às {{4}}."
   - `lembrete_agendamento` (UTILITY), `remarcacao_agendamento`, `cancelamento_agendamento`, `agradecimento` (UTILITY)
   - `aniversario`, `convite_retorno`, campanhas (MARKETING)

   **Não inclua informações de saúde** nos textos.

## 2. No Corpo Sano (WhatsApp › Configuração)

1. Informe Business ID, WABA ID, Phone Number ID, versão da Graph API, Access Token, App Secret e um
   **Verify Token** (texto aleatório criado por você). Tokens ficam criptografados no servidor e nunca
   retornam ao navegador.
2. Copie a **Webhook URL** exibida (`https://SEU_DOMINIO/api/v1/whatsapp/webhook`).
3. Clique em **Testar conexão**.
4. Ative a integração e escolha as automações (confirmação, lembrete com antecedência configurável,
   remarcação, cancelamento, agradecimento, aniversário).

## 3. Webhook (na Meta)

*App › WhatsApp › Configuração › Webhook*: cole a URL e o Verify Token, verifique e assine o campo
`messages`. Cada evento recebido é validado pelo cabeçalho `X-Hub-Signature-256` (HMAC-SHA256 com o
App Secret); eventos sem assinatura válida são rejeitados.

O webhook registra: status de **entrega/leitura/falha**, mensagens recebidas (identificando o cliente pelo
número, inclusive com/sem o 9º dígito), histórico no CRM e **opt-out** ("SAIR", "PARAR", "STOP"...),
que revoga automaticamente o consentimento de mensagens promocionais.

## 4. Templates no sistema

*WhatsApp › Templates › Sincronizar com a Meta*. Para cada template aprovado, configure:
- **Finalidade** (confirmação, lembrete, remarcação, cancelamento, agradecimento, aniversário, retorno, campanha);
- **Variáveis** `{{1}}, {{2}}...` mapeadas para dados permitidos: primeiro nome do cliente, data, hora,
  serviço, profissional, nome/telefone/endereço da clínica. Dados clínicos nunca estão disponíveis.

Finalidades de relacionamento/campanha exigem template **MARKETING**.

## 5. Regras de envio

- Fluxo: evento (ex.: agendamento) → registro → preparação → fila → envio → registro do resultado → status.
- Fila com até 5 tentativas e espera progressiva (1, 5, 15, 60, 180 min) para erros temporários; erros
  definitivos ficam como *Falhou* com o motivo e podem ser reenviados manualmente.
- Consentimento: mensagens de agendamento exigem consentimento "WhatsApp: confirmações e lembretes";
  aniversário, retorno e campanhas exigem "WhatsApp: relacionamento". Sem consentimento, a mensagem é
  registrada como *Bloqueada* e não é enviada.
- Mensagens iniciadas pela clínica usam sempre templates aprovados. Texto livre somente dentro da janela
  de 24 h após a última mensagem do cliente.
- Lembretes, confirmações e campanhas não se duplicam (chave de deduplicação por evento).
