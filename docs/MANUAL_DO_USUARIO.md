# Manual de utilização — Corpo Sano

## Primeiros passos (administrador)

1. Entre com o usuário inicial e defina sua senha pessoal.
2. **Configurações › Clínica**: dados e **logotipo** (aparece no login, no menu e nos PDFs).
3. **Configurações › Agenda, salas e profissionais**: dias e horários de funcionamento (com intervalo),
   feriados, salas, profissionais (cor na agenda) e disponibilidade específica de cada profissional.
4. **Serviços**: cadastre os serviços (duração, intervalo após a sessão, preço, profissionais habilitados)
   e os **planos de pacote** (sessões, validade, regras de falta e cancelamento tardio).
5. **Configurações › Financeiro**: contas (caixa/banco), formas de pagamento, categorias, centros de custo.
6. **Usuários**: crie um usuário por pessoa. Perfis: Administrador, Recepcionista, Massoterapeuta
   (vincule ao profissional) e Contador. Personalize permissões por perfil ou por usuário.
7. **Contábil e Fiscal › Cadastro fiscal** e **WhatsApp › Configuração** (ver os guias específicos).

Barra superior: **pesquisa global** (Ctrl+K) por nome, telefone, CPF, nota; **Atalhos** (novo cliente,
novo agendamento, registrar atendimento, registrar pagamento, emitir nota, cadastrar despesa...);
**sino de alertas** (contas em atraso, certificado vencendo, obrigações fiscais, pacotes); tema claro/escuro;
e o **menu da conta** (clique no seu nome ou nas iniciais) com minha conta, tema e sair. No celular, uma
barra inferior leva direto a Dashboard, Agenda, Clientes, Financeiro e ao menu completo.
A sessão é encerrada após o tempo de inatividade configurado.

## Clientes

- Cadastro com CPF opcional (validado quando informado), contatos, endereço (preenchimento pelo CEP),
  origem, preferências e **consentimentos LGPD** (dados, WhatsApp de agendamento, relacionamento, e-mail).
- Filtros: novos, ativos, inativos, recorrentes. O **perfil** reúne agendamentos, serviços, pacotes,
  financeiro, notas fiscais, contatos e privacidade (exportação de dados e anonimização).

## Agenda

- Visões **lista** (agendamentos do dia em ordem de horário, padrão no celular), **dia** (colunas por
  profissional), **semana** e **mês**. Cada status tem cor e ícone; uma linha vermelha marca a hora atual.
- Clique em um horário livre para agendar. O formulário sugere **horários livres**, verifica conflitos em
  tempo real e permite usar sessão de **pacote**, avaliação inicial e **recorrência** (semanal, quinzenal,
  mensal, pulando datas ocupadas).
- O sistema impede conflito do mesmo profissional ou da mesma sala (inclusive intervalo entre sessões),
  fora do horário de funcionamento, feriados e horários bloqueados.
- No agendamento: confirmar presença, iniciar, **finalizar** (opcionalmente registrando o pagamento),
  remarcar, registrar falta ou cancelar (com motivo). Todo o histórico fica registrado.
- **Bloquear horário** para profissional, sala ou clínica inteira.

## Atendimentos e anamnese (dados de saúde)

- Acesso restrito (Administrador e Massoterapeuta). Cada leitura fica na auditoria.
- **Anamnese** versionada com **aceite eletrônico** (nome, data/hora, IP e código de integridade).
- **Ficha do atendimento**: técnica, duração, produtos, evolução relatada, recomendações e retorno sugerido
  (gera tarefa de retorno no CRM, sem detalhes clínicos). Fichas não são editáveis (registre complemento).
- Documentos anexos criptografados. O sistema **não** gera diagnóstico ou prescrição.

## Pacotes

- Venda a partir de plano ou personalizada, com parcelamento → gera contas a receber.
- Sessão é baixada **somente** quando o atendimento é concluído (ou pela regra de falta/cancelamento tardio).
- Alertas de saldo baixo e vencimento; reversão de baixa com motivo; cancelamento do pacote.

## CRM

- Funil (arraste os cartões): novo contato → interessado → avaliação agendada → primeiro atendimento →
  recorrente → pacote contratado → inativo. Estágios avançam automaticamente com os eventos reais.
- Retornos após 30/60/90 dias (configuráveis), aniversariantes, clientes sem agendamento futuro e inativos.
- Tarefas e lembretes, histórico de contatos (ligações, mensagens, WhatsApp), campanhas com consentimento.

## Financeiro

- **Visão geral**: receita contratada, faturada (NFS-e), recebida e pendente — agendamento nunca é receita.
- **Contas a receber**: geradas na conclusão do atendimento avulso, na venda do pacote ou manualmente;
  pagamentos parciais, descontos, parcelamento, cancelamento, emissão de NFS-e a partir do título.
- **Contas a pagar/despesas**: categorias, centros de custo, parcelas, comprovantes anexos.
- **Movimentações**: estornos e conciliação com o extrato. **Fluxo de caixa** realizado e previsto.
- **Fechamento diário** (bloqueia lançamentos retroativos), **conciliação** (pagamento × nota), **inadimplência**.

## Contábil e Fiscal

Emissão de NFS-e (a partir da receita ainda não faturada ou avulsa) → **prévia** → transmissão;
notas emitidas (consulta, DANFSe, XML, cancelamento, substituição, reprocessamento); notas recebidas;
tributos (regras e apurações estimadas); receitas e despesas (escrituração auxiliar); obrigações fiscais;
documentos contábeis; exportação mensal para o contador. Detalhes em [CONFIGURACAO_FISCAL.md](CONFIGURACAO_FISCAL.md).

## Relatórios

Operacionais, financeiros e fiscais (26 relatórios), com filtro por período, impressão e exportação
em **PDF, Excel e CSV**.

## WhatsApp

Histórico de mensagens enviadas e recebidas com status de entrega/leitura, reenvio de falhas,
envio manual (template aprovado ou texto dentro da janela de 24 h), templates e configuração.
